"""Restore a backup into an isolated target and verify the restored schema.

PostgreSQL restores require RESTORE_PGSERVICE and RESTORE_DATABASE_NAME. The
name must end in ``_restore_test`` to reduce the risk of targeting production.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path


def verify_sqlite(backup: Path) -> None:
    connection = sqlite3.connect(backup)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        required_tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        expected = {"appointments", "call_transcripts", "conversation_sessions", "schema_migrations"}
        if not expected.issubset(required_tables):
            raise RuntimeError(f"Backup is missing tables: {sorted(expected - required_tables)}")
    finally:
        connection.close()


def restore_postgres(backup: Path) -> None:
    service = os.getenv("RESTORE_PGSERVICE")
    database_name = os.getenv("RESTORE_DATABASE_NAME", "")
    if not service or not database_name.endswith("_restore_test"):
        raise RuntimeError(
            "Set RESTORE_PGSERVICE and RESTORE_DATABASE_NAME ending in _restore_test; "
            "never target the production database for a restore test"
        )
    pg_restore = shutil.which("pg_restore")
    psql = shutil.which("psql")
    if not pg_restore or not psql:
        raise RuntimeError("Install PostgreSQL client tools (pg_restore and psql)")
    target = f"service={service} dbname={database_name}"
    subprocess.run(
        [pg_restore, "--clean", "--if-exists", "--no-owner", "--dbname", target, str(backup)],
        check=True,
    )
    verification = subprocess.run(
        [psql, "--dbname", target, "--no-align", "--tuples-only", "--command",
         "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'appointments'"],
        check=True,
        capture_output=True,
        text=True,
    )
    if verification.stdout.strip() != "1":
        raise RuntimeError("Restored database is missing the appointments table")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--postgres", action="store_true", help="Restore custom-format PostgreSQL dump")
    args = parser.parse_args()
    if not args.backup.is_file():
        raise FileNotFoundError(args.backup)
    backup = args.backup.resolve()
    temporary_archive = None
    if backup.name.endswith(".age"):
        age = shutil.which("age")
        identity = os.getenv("BACKUP_AGE_IDENTITY_FILE")
        if not age or not identity:
            raise RuntimeError("Install age and set BACKUP_AGE_IDENTITY_FILE to decrypt this backup")
        with tempfile.NamedTemporaryFile(prefix="restore-check-", suffix=".dump", delete=False) as temporary:
            temporary_archive = Path(temporary.name)
        subprocess.run(
            [age, "--decrypt", "--identity", identity, "--output", str(temporary_archive), str(backup)],
            check=True,
        )
        backup = temporary_archive
    try:
        if args.postgres:
            restore_postgres(backup)
        else:
            verify_sqlite(backup)
    finally:
        if temporary_archive is not None:
            temporary_archive.unlink(missing_ok=True)
    print("Backup restore validation succeeded.")


if __name__ == "__main__":
    main()
