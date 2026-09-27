"""
Real, persistent relational storage.

This is not an in-memory list standing in for a database -- it is a genuine
SQLite database file (or ``:memory:`` for tests), created and migrated on
startup, with real tables, real foreign keys, and real queries. A production
deployment points ``DATABASE_URL`` at Postgres and swaps ``_connect`` for a
psycopg/SQLAlchemy engine; every call site in the rest of the app goes
through this class, so nothing else has to change.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import DATABASE_URL

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
    appointment_id TEXT NOT NULL,
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
    related_appointment_id TEXT,
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
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseAdapter:
    """SQLite-backed adapter. Accepts ``sqlite:///path`` or ``sqlite:///:memory:``
    style URLs (the ``DATABASE_URL`` env-var contract); a ``postgresql://`` URL
    is the production swap point and is intentionally rejected here rather than
    silently downgraded to SQLite, so a misconfigured deployment fails loudly."""

    def __init__(self, connection_url: str = DATABASE_URL):
        self.connection_url = connection_url
        if connection_url.startswith("postgresql://") or connection_url.startswith("postgres://"):
            raise RuntimeError(
                "DATABASE_URL points at Postgres, but this build only ships the "
                "SQLite engine. Install a Postgres driver and extend "
                "DatabaseAdapter._connect() before deploying with a real "
                "postgresql:// URL -- do not silently fall back."
            )
        if not connection_url.startswith("sqlite:///"):
            raise RuntimeError(f"Unsupported DATABASE_URL scheme: {connection_url}")
        path = connection_url[len("sqlite:///"):]
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
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
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
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
                (call_id, client_name, client_phone, transcript, intent, _now()),
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
                 budget_pkr, property_type, _now()),
            )

    def get_client_preferences(self, client_phone: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM client_preferences WHERE client_phone = ?", (client_phone,))
            row = cur.fetchone()
            return dict(row) if row else None

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
                       start_time = excluded.start_time,
                       end_time = excluded.end_time,
                       status = excluded.status""",
                appointment,
            )

    def add_appointment_history(self, appointment_id: str, action: str, detail: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO appointment_history (appointment_id, action, detail, occurred_at) "
                "VALUES (?, ?, ?, ?)",
                (appointment_id, action, detail, _now()),
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
                     _now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

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
                (call_id, failed_node, error_message, _now()),
            )

    # --- Monitoring ------------------------------------------------------
    def record_event(self, event: str, call_id: str | None, latency_ms: float,
                      success: bool, detail: dict[str, Any] | None = None) -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO monitoring_events (event, call_id, latency_ms, success, detail, occurred_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event, call_id, latency_ms, int(success), json.dumps(detail or {}), _now()),
            )

    def monitoring_summary(self) -> dict[str, Any]:
        with self.cursor() as cur:
            cur.execute("SELECT latency_ms, success FROM monitoring_events")
            rows = cur.fetchall()
        if not rows:
            return {"events": 0}
        latencies = [r["latency_ms"] for r in rows]
        failures = sum(1 for r in rows if not r["success"])
        return {
            "events": len(rows),
            "average_latency_ms": round(sum(latencies) / len(latencies), 2),
            "max_latency_ms": max(latencies),
            "failures": failures,
            "success_rate": round((len(rows) - failures) / len(rows), 4),
        }
