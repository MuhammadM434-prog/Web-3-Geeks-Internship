"""Persistent relational storage with SQLite and pooled PostgreSQL backends.

SQLite initializes locally for tests. PostgreSQL uses psycopg connection
pooling, versioned migrations, native timestamps, and a restricted runtime
connection; production startup verifies migrations rather than applying DDL.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from app.config import (
    APP_ENV,
    DATABASE_URL,
    DATABASE_AUTO_MIGRATE,
    DATABASE_POOL_MAX_SIZE,
    DATABASE_POOL_MIN_SIZE,
    MONITORING_RETENTION_DAYS,
    SESSION_RETENTION_DAYS,
    TRANSCRIPT_RETENTION_DAYS,
)

try:
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
except ImportError:  # SQLite/local installations do not need PostgreSQL packages.
    dict_row = None
    ConnectionPool = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS call_transcripts (
    call_id TEXT PRIMARY KEY,
    client_name TEXT,
    client_phone TEXT,
    transcript TEXT NOT NULL,
    intent TEXT,
    logged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS client_preferences (
    client_phone TEXT PRIMARY KEY,
    client_name TEXT,
    preferred_city TEXT,
    preferred_area TEXT,
    budget_pkr INTEGER,
    property_type TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT PRIMARY KEY,
    calendar_event_id TEXT NOT NULL,
    call_id TEXT,
    client_name TEXT,
    client_phone TEXT,
    employee_id TEXT,
    property_id TEXT,
    start_time TEXT,
    end_time TEXT,
    status TEXT NOT NULL,
    requirements TEXT,
    idempotency_key TEXT
);

CREATE TABLE IF NOT EXISTS appointment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id TEXT NOT NULL REFERENCES appointments(appointment_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    detail TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emails_sent (
    message_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    related_appointment_id TEXT REFERENCES appointments(appointment_id) ON DELETE SET NULL,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    failed_node TEXT,
    error_message TEXT,
    failed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review'
);

CREATE TABLE IF NOT EXISTS monitoring_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    call_id TEXT,
    latency_ms REAL,
    success INTEGER,
    detail TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    call_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS appointments_idempotency_key_idx
    ON appointments(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS appointments_employee_time_idx
    ON appointments(employee_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS transcripts_logged_at_idx
    ON call_transcripts(logged_at);
CREATE INDEX IF NOT EXISTS sessions_updated_at_idx
    ON conversation_sessions(updated_at);
CREATE INDEX IF NOT EXISTS monitoring_occurred_at_idx
    ON monitoring_events(occurred_at);
"""

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class _PostgresCursor:
    """Adapt the adapter's SQLite-style placeholders to psycopg parameters."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    @staticmethod
    def _query(query: str, params: Any) -> str:
        if isinstance(params, dict):
            return re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", query)
        return query.replace("?", "%s")

    def execute(self, query: str, params: Any = None) -> Any:
        if isinstance(params, dict):
            params = {
                key: _as_datetime(value)
                if key in {"logged_at", "updated_at", "start_time", "end_time", "occurred_at", "sent_at", "failed_at", "applied_at"}
                and isinstance(value, str)
                else value
                for key, value in params.items()
            }
        return self._cursor.execute(self._query(query, params), params)

    def executemany(self, query: str, params: Any) -> Any:
        return self._cursor.executemany(self._query(query, params[0] if params else None), params)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> Any:
        return self._cursor.fetchall()


class DatabaseAdapter:
    """Pooled PostgreSQL or SQLite adapter with one service-facing API."""

    def __init__(self, connection_url: str = DATABASE_URL, auto_migrate: bool | None = None):
        self.connection_url = connection_url
        self.auto_migrate = DATABASE_AUTO_MIGRATE if auto_migrate is None else auto_migrate
        if connection_url.startswith("postgresql://") or connection_url.startswith("postgres://"):
            if ConnectionPool is None or dict_row is None:
                raise RuntimeError("Install psycopg[binary] and psycopg-pool for PostgreSQL")
            if (
                DATABASE_POOL_MIN_SIZE < 0
                or DATABASE_POOL_MAX_SIZE < 1
                or DATABASE_POOL_MIN_SIZE > DATABASE_POOL_MAX_SIZE
            ):
                raise ValueError("Invalid PostgreSQL connection pool size configuration")
            if APP_ENV == "production":
                ssl_mode = parse_qs(urlparse(connection_url).query).get("sslmode", [""])[0]
                if ssl_mode not in {"require", "verify-ca", "verify-full"}:
                    raise RuntimeError(
                        "Production PostgreSQL DATABASE_URL must specify sslmode=require or stricter"
                    )
            self.backend = "postgresql"
            self._pool = ConnectionPool(
                conninfo=connection_url,
                min_size=DATABASE_POOL_MIN_SIZE,
                max_size=DATABASE_POOL_MAX_SIZE,
                open=True,
            )
            try:
                if self.auto_migrate:
                    self.run_migrations()
                else:
                    self._verify_postgres_schema()
            except Exception:
                self._pool.close()
                raise
            return
        if not connection_url.startswith("sqlite:///"):
            raise RuntimeError(f"Unsupported DATABASE_URL scheme: {connection_url}")
        self.backend = "sqlite"
        self._pool = None
        path = connection_url[len("sqlite:///"):]
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._connect_target = path
            self._connect_uri = False
            self._memory_keeper = None
        else:
            self._connect_target = f"file:realestate-agent-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._connect_uri = True
            self._memory_keeper = sqlite3.connect(self._connect_target, uri=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                ("001_initial", _now()),
            )
            conn.commit()

    def _initialize_postgres(self) -> None:
        with self.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL)"
            )
        migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
        migration_paths = sorted(
            path for path in migrations_dir.glob("*.sql")
            if re.match(r"^\d+_[a-zA-Z0-9_-]+\.sql$", path.name)
        )
        for migration_path in migration_paths:
            version = migration_path.stem
            with self.cursor() as cur:
                cur.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,))
                if cur.fetchone():
                    continue
                migration_sql = "\n".join(
                    line for line in migration_path.read_text(encoding="utf-8").splitlines()
                    if not line.lstrip().startswith("--")
                )
                statements = [part.strip() for part in migration_sql.split(";")]
                for statement in statements:
                    if statement:
                        cur.execute(statement)
                cur.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, self._db_now()),
                )

    def run_migrations(self) -> None:
        if self.backend == "postgresql":
            self._initialize_postgres()

    def _verify_postgres_schema(self) -> None:
        try:
            with self.cursor() as cur:
                cur.execute("SELECT version FROM schema_migrations ORDER BY version")
                applied = {row["version"] for row in cur.fetchall()}
        except Exception as error:
            raise RuntimeError(
                "PostgreSQL schema is not initialized. Run `python -m app.migrate` "
                "using DATABASE_MIGRATION_URL before starting the app."
            ) from error
        pending = {
            path.stem for path in (Path(__file__).resolve().parent.parent / "migrations").glob("*.sql")
            if re.match(r"^\d+_[a-zA-Z0-9_-]+\.sql$", path.name)
        } - applied
        if pending:
            raise RuntimeError(
                f"PostgreSQL migrations are pending: {', '.join(sorted(pending))}. "
                "Run `python -m app.migrate` using the migration role."
            )

    def close(self) -> None:
        if self.backend == "postgresql" and self._pool is not None:
            self._pool.close()
        elif self.backend == "sqlite" and self._memory_keeper is not None:
            self._memory_keeper.close()

    def _db_now(self) -> datetime | str:
        return datetime.now(timezone.utc) if self.backend == "postgresql" else _now()

    def _db_time(self, value: datetime) -> datetime | str:
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized if self.backend == "postgresql" else normalized.isoformat()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._connect_target, uri=self._connect_uri)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        if self.backend == "postgresql":
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    yield _PostgresCursor(cur)
            return
        conn = self._connect()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        finally:
            conn.close()

    def health(self) -> bool:
        try:
            with self.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS row_count FROM appointments")
                appointments_accessible = cur.fetchone()["row_count"] if self.backend == "postgresql" else cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) AS row_count FROM schema_migrations")
                migrations_accessible = cur.fetchone()["row_count"] if self.backend == "postgresql" else cur.fetchone()[0]
                return appointments_accessible >= 0 and migrations_accessible >= 1
        except Exception:
            return False

    # --- CRM -----------------------------------------------------------
    def log_call_transcript(self, call_id: str, client_name: str, client_phone: str,
                             transcript: str, intent: str | None) -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO call_transcripts (call_id, client_name, client_phone,
                       transcript, intent, logged_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(call_id) DO UPDATE SET
                       transcript = excluded.transcript,
                       intent = excluded.intent,
                       logged_at = excluded.logged_at""",
                (call_id, client_name, client_phone, transcript, intent, self._db_now()),
            )

    def upsert_client_preferences(self, client_phone: str, client_name: str,
                                   preferred_city: str | None, preferred_area: str | None,
                                   budget_pkr: int | None, property_type: str | None) -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO client_preferences
                       (client_phone, client_name, preferred_city, preferred_area,
                        budget_pkr, property_type, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(client_phone) DO UPDATE SET
                       client_name = excluded.client_name,
                       preferred_city = COALESCE(excluded.preferred_city, client_preferences.preferred_city),
                       preferred_area = COALESCE(excluded.preferred_area, client_preferences.preferred_area),
                       budget_pkr = COALESCE(excluded.budget_pkr, client_preferences.budget_pkr),
                       property_type = COALESCE(excluded.property_type, client_preferences.property_type),
                       updated_at = excluded.updated_at""",
                (client_phone, client_name, preferred_city, preferred_area,
                 budget_pkr, property_type, self._db_now()),
            )

    def get_client_preferences(self, client_phone: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM client_preferences WHERE client_phone = ?", (client_phone,))
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Conversation sessions -----------------------------------------
    def save_session(self, call_id: str, state: dict[str, Any]) -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO conversation_sessions (call_id, state_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(call_id) DO UPDATE SET
                       state_json = excluded.state_json,
                       updated_at = excluded.updated_at""",
                (call_id, json.dumps(state, default=_json_default), self._db_now()),
            )

    def get_session(self, call_id: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT state_json FROM conversation_sessions WHERE call_id = ?", (call_id,))
            row = cur.fetchone()
            return json.loads(row["state_json"]) if row else None

    def delete_session(self, call_id: str) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM conversation_sessions WHERE call_id = ?", (call_id,))

    def book_appointment_if_available(self, appointment: dict[str, Any]) -> bool:
        """Atomically check employee overlap and insert booking plus audit row."""
        start = _as_datetime(appointment["start_time"])
        end = _as_datetime(appointment["end_time"])
        employee_id = appointment["employee_id"]
        if self.backend == "postgresql":
            with self._pool.connection() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as raw_cur:
                        raw_cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (employee_id,))
                        raw_cur.execute(
                            """SELECT start_time, end_time FROM appointments
                               WHERE employee_id = %s AND status != 'cancelled' FOR UPDATE""",
                            (employee_id,),
                        )
                        if any(
                            start < _as_datetime(row["end_time"])
                            and _as_datetime(row["start_time"]) < end
                            for row in raw_cur.fetchall()
                        ):
                            return False
                        cur = _PostgresCursor(raw_cur)
                        self._insert_appointment(cur, appointment)
                        cur.execute(
                            "INSERT INTO appointment_history (appointment_id, action, detail, occurred_at) "
                            "VALUES (?, ?, ?, ?)",
                            (appointment["appointment_id"], "booked",
                             f"Visit booked for {appointment['property_id']} at {appointment['start_time']}", self._db_now()),
                        )
            return True

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT start_time, end_time FROM appointments "
                "WHERE employee_id = ? AND status != 'cancelled'",
                (employee_id,),
            ).fetchall()
            if any(
                start < _as_datetime(row["end_time"])
                and _as_datetime(row["start_time"]) < end
                for row in rows
            ):
                conn.rollback()
                return False
            cur = conn.cursor()
            self._insert_appointment(cur, appointment)
            cur.execute(
                "INSERT INTO appointment_history (appointment_id, action, detail, occurred_at) "
                "VALUES (?, ?, ?, ?)",
                (appointment["appointment_id"], "booked",
                 f"Visit booked for {appointment['property_id']} at {appointment['start_time']}", self._db_now()),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _insert_appointment(cur: Any, appointment: dict[str, Any]) -> None:
        cur.execute(
            """INSERT INTO appointments
                   (appointment_id, calendar_event_id, call_id, client_name, client_phone,
                    employee_id, property_id, start_time, end_time, status, requirements,
                    idempotency_key)
               VALUES (:appointment_id, :calendar_event_id, :call_id, :client_name,
                       :client_phone, :employee_id, :property_id, :start_time, :end_time,
                       :status, :requirements, :idempotency_key)""",
            appointment,
        )

    def purge_expired_data(self, now: datetime | None = None) -> dict[str, int]:
        """Apply configured retention to transcripts, sessions, and telemetry."""
        now = now or datetime.now(timezone.utc)
        transcript_cutoff = self._db_time(now - timedelta(days=TRANSCRIPT_RETENTION_DAYS))
        session_cutoff = self._db_time(now - timedelta(days=SESSION_RETENTION_DAYS))
        monitoring_cutoff = self._db_time(now - timedelta(days=MONITORING_RETENTION_DAYS))
        counts: dict[str, int] = {}
        with self.cursor() as cur:
            cur.execute("DELETE FROM call_transcripts WHERE logged_at < ?", (transcript_cutoff,))
            counts["call_transcripts"] = cur.rowcount
            cur.execute("DELETE FROM conversation_sessions WHERE updated_at < ?", (session_cutoff,))
            counts["conversation_sessions"] = cur.rowcount
            cur.execute("DELETE FROM monitoring_events WHERE occurred_at < ?", (monitoring_cutoff,))
            counts["monitoring_events"] = cur.rowcount
        return counts

    def erase_customer_data(self, client_phone: str) -> dict[str, int]:
        """Erase caller profile/transcripts and anonymize retained appointment audit."""
        counts: dict[str, int] = {}
        with self.cursor() as cur:
            cur.execute("SELECT call_id FROM call_transcripts WHERE client_phone = ?", (client_phone,))
            call_ids = [row["call_id"] for row in cur.fetchall()]
            cur.execute("SELECT appointment_id FROM appointments WHERE client_phone = ?", (client_phone,))
            appointment_ids = [row["appointment_id"] for row in cur.fetchall()]
            cur.execute("DELETE FROM call_transcripts WHERE client_phone = ?", (client_phone,))
            counts["call_transcripts"] = cur.rowcount
            cur.execute("DELETE FROM client_preferences WHERE client_phone = ?", (client_phone,))
            counts["client_preferences"] = cur.rowcount
            if call_ids:
                placeholders = ",".join("?" for _ in call_ids)
                cur.execute(f"DELETE FROM conversation_sessions WHERE call_id IN ({placeholders})", tuple(call_ids))
                counts["conversation_sessions"] = cur.rowcount
                cur.execute(f"DELETE FROM dead_letter_queue WHERE call_id IN ({placeholders})", tuple(call_ids))
                counts["dead_letter_queue"] = cur.rowcount
                cur.execute(f"DELETE FROM monitoring_events WHERE call_id IN ({placeholders})", tuple(call_ids))
                counts["monitoring_events"] = cur.rowcount
            else:
                counts["conversation_sessions"] = 0
                counts["dead_letter_queue"] = 0
                counts["monitoring_events"] = 0
            if appointment_ids:
                placeholders = ",".join("?" for _ in appointment_ids)
                cur.execute(f"DELETE FROM emails_sent WHERE related_appointment_id IN ({placeholders})", tuple(appointment_ids))
                counts["emails_sent"] = cur.rowcount
            else:
                counts["emails_sent"] = 0
            cur.execute(
                "UPDATE appointments SET client_name = ?, client_phone = NULL, requirements = NULL "
                "WHERE client_phone = ?",
                ("[deleted]", client_phone),
            )
            counts["appointments_anonymized"] = cur.rowcount
        return counts

    def backup_sqlite(self, destination: str | Path) -> Path:
        if self.backend != "sqlite" or self._connect_uri:
            raise RuntimeError("Online SQLite backup is available only for file-backed SQLite databases")
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"SQLite backup integrity check failed: {result}")
        finally:
            target.close()
            source.close()
        return destination

    # --- Appointments ----------------------------------------------------
    def save_appointment(self, appointment: dict[str, Any]) -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO appointments
                       (appointment_id, calendar_event_id, call_id, client_name, client_phone,
                        employee_id, property_id, start_time, end_time, status, requirements,
                        idempotency_key)
                   VALUES (:appointment_id, :calendar_event_id, :call_id, :client_name,
                           :client_phone, :employee_id, :property_id, :start_time, :end_time,
                           :status, :requirements, :idempotency_key)
                   ON CONFLICT(appointment_id) DO UPDATE SET
                       calendar_event_id = excluded.calendar_event_id,
                       start_time = excluded.start_time,
                       end_time = excluded.end_time,
                       status = excluded.status""",
                appointment,
            )

    def abort_unconfirmed_appointment(self, appointment_id: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM appointment_history WHERE appointment_id = ? AND action = 'booked'",
                (appointment_id,),
            )

    def reschedule_appointment_if_available(
        self, appointment_id: str, new_start: datetime, new_end: datetime
    ) -> tuple[str, dict[str, Any] | None]:
        """Atomically verify employee overlap and update appointment history."""
        if self.backend == "postgresql":
            with self._pool.connection() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as raw_cur:
                        cur = _PostgresCursor(raw_cur)
                        cur.execute("SELECT employee_id FROM appointments WHERE appointment_id = ?", (appointment_id,))
                        employee = cur.fetchone()
                        if employee is None:
                            return "not_found", None
                        employee_id = employee["employee_id"]
                        raw_cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (employee_id,))
                        cur.execute("SELECT * FROM appointments WHERE appointment_id = ? FOR UPDATE", (appointment_id,))
                        appointment = cur.fetchone()
                        if appointment["status"] == "cancelled":
                            return "cancelled_appointment", dict(appointment)
                        raw_cur.execute(
                            """SELECT start_time, end_time FROM appointments
                               WHERE employee_id = %s AND status != 'cancelled'
                               AND appointment_id != %s FOR UPDATE""",
                            (employee_id, appointment_id),
                        )
                        if any(
                            new_start < _as_datetime(row["end_time"])
                            and _as_datetime(row["start_time"]) < new_end
                            for row in raw_cur.fetchall()
                        ):
                            return "slot_unavailable", dict(appointment)
                        previous = dict(appointment)
                        cur.execute(
                            "UPDATE appointments SET start_time = ?, end_time = ?, status = ? "
                            "WHERE appointment_id = ?",
                            (self._db_time(new_start), self._db_time(new_end), "rescheduled", appointment_id),
                        )
                        cur.execute(
                            "INSERT INTO appointment_history (appointment_id, action, detail, occurred_at) "
                            "VALUES (?, ?, ?, ?)",
                            (appointment_id, "rescheduled", f"Moved to {new_start.isoformat()}", self._db_now()),
                        )
                        previous["start_time"] = self._db_time(new_start)
                        previous["end_time"] = self._db_time(new_end)
                        previous["status"] = "rescheduled"
                        return "success", previous

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            cur.execute("SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return "not_found", None
            appointment = dict(row)
            if appointment["status"] == "cancelled":
                conn.rollback()
                return "cancelled_appointment", appointment
            cur.execute(
                "SELECT start_time, end_time FROM appointments WHERE employee_id = ? "
                "AND status != 'cancelled' AND appointment_id != ?",
                (appointment["employee_id"], appointment_id),
            )
            if any(
                new_start < _as_datetime(existing["end_time"])
                and _as_datetime(existing["start_time"]) < new_end
                for existing in cur.fetchall()
            ):
                conn.rollback()
                return "slot_unavailable", appointment
            cur.execute(
                "UPDATE appointments SET start_time = ?, end_time = ?, status = ? WHERE appointment_id = ?",
                (new_start.isoformat(), new_end.isoformat(), "rescheduled", appointment_id),
            )
            cur.execute(
                "INSERT INTO appointment_history (appointment_id, action, detail, occurred_at) "
                "VALUES (?, ?, ?, ?)",
                (appointment_id, "rescheduled", f"Moved to {new_start.isoformat()}", self._db_now()),
            )
            conn.commit()
            appointment["start_time"] = new_start.isoformat()
            appointment["end_time"] = new_end.isoformat()
            appointment["status"] = "rescheduled"
            return "success", appointment
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            cur.execute(
                "DELETE FROM appointments WHERE appointment_id = ? AND status = 'booked'",
                (appointment_id,),
            )

    def add_appointment_history(self, appointment_id: str, action: str, detail: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO appointment_history (appointment_id, action, detail, occurred_at) "
                "VALUES (?, ?, ?, ?)",
                (appointment_id, action, detail, self._db_now()),
            )

    def list_events_for_employee(self, employee_id: str) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM appointments WHERE employee_id = ? AND status != 'cancelled'",
                (employee_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_appointment(self, appointment_id: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def find_appointment_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM appointments WHERE idempotency_key = ?", (key,))
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Email -------------------------------------------------------------
    def save_email(self, message: dict[str, Any]) -> bool:
        """Returns False (no-op) if this idempotency_key was already used."""
        try:
            with self.cursor() as cur:
                cur.execute(
                    """INSERT INTO emails_sent
                           (message_id, idempotency_key, to_address, subject, body,
                            related_appointment_id, sent_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (message["message_id"], message["idempotency_key"], message["to_address"],
                     message["subject"], message["body"], message.get("related_appointment_id"),
                     self._db_now()),
                )
            return True
        except Exception as error:
            if isinstance(error, sqlite3.IntegrityError) or getattr(error, "sqlstate", None) == "23505":
                return False
            raise

    def find_email_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM emails_sent WHERE idempotency_key = ?", (key,))
            row = cur.fetchone()
            return dict(row) if row else None

    def count_emails(self) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM emails_sent")
            return cur.fetchone()[0]

    # --- Dead-letter / error handling ----------------------------------
    def dead_letter(self, call_id: str, failed_node: str, error_message: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO dead_letter_queue (call_id, failed_node, error_message, failed_at) "
                "VALUES (?, ?, ?, ?)",
                (call_id, failed_node, error_message, self._db_now()),
            )

    # --- Monitoring ------------------------------------------------------
    def record_event(self, event: str, call_id: str | None, latency_ms: float,
                      success: bool, detail: dict[str, Any] | None = None) -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO monitoring_events (event, call_id, latency_ms, success, detail, occurred_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event, call_id, latency_ms, int(success), json.dumps(detail or {}), self._db_now()),
            )

    def monitoring_summary(self) -> dict[str, Any]:
        with self.cursor() as cur:
            cur.execute("SELECT latency_ms, success FROM monitoring_events")
            rows = cur.fetchall()
        if not rows:
            return {"events": 0}
        latencies = [r["latency_ms"] for r in rows]
        ordered_latencies = sorted(latencies)

        def percentile(rank: float) -> float:
            index = max(0, min(len(ordered_latencies) - 1, int((len(ordered_latencies) * rank) - 1)))
            return ordered_latencies[index]

        failures = sum(1 for r in rows if not r["success"])
        return {
            "events": len(rows),
            "average_latency_ms": round(sum(latencies) / len(latencies), 2),
            "p50_latency_ms": percentile(0.50),
            "p95_latency_ms": percentile(0.95),
            "max_latency_ms": max(latencies),
            "failures": failures,
            "success_rate": round((len(rows) - failures) / len(rows), 4),
        }
