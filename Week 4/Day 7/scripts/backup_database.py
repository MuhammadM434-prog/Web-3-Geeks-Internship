"""Create and validate an online SQLite or PostgreSQL backup.

For PostgreSQL, configure a libpq service in PGSERVICE/PGSERVICEFILE and a
0600 PGPASSFILE (or an approved platform secret integration). Credentials are
never placed in process arguments.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import APP_ENV, DATABASE_URL
from app.database import DatabaseAdapter


def backup_sqlite(destination: Path) -> None:
    database = DatabaseAdapter(DATABASE_URL)
    try:
        database.backup_sqlite(destination)
    finally:
        database.close()


def backup_postgres(destination: Path) -> None:
    service = os.getenv("PGSERVICE")
    if not service:
        raise RuntimeError("Set PGSERVICE and PGSERVICEFILE for secret-free PostgreSQL backups")
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        raise RuntimeError("Install PostgreSQL client tools (pg_dump and pg_restore)")
    subprocess.run(
        [pg_dump, "--format=custom", "--no-owner", "--file", str(destination), "--dbname", f"service={service}"],
        check=True,
    )
    subprocess.run([pg_restore, "--list", str(destination)], check=True, capture_output=True, text=True)


def encrypt_backup(archive: Path) -> Path:
    recipient = os.getenv("BACKUP_AGE_RECIPIENT", "").strip()
    if not recipient:
        if APP_ENV == "production":
            archive.unlink(missing_ok=True)
            raise RuntimeError("BACKUP_AGE_RECIPIENT is required for production backup encryption")
        return archive
    age = shutil.which("age")
    if not age:
        archive.unlink(missing_ok=True)
        raise RuntimeError("Install age and add it to PATH to encrypt backup archives")
    encrypted = archive.with_name(archive.name + ".age")
    try:
        subprocess.run([age, "--recipient", recipient, "--output", str(encrypted), str(archive)], check=True)
    finally:
        archive.unlink(missing_ok=True)
    return encrypted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    is_postgres = DATABASE_URL.startswith(("postgresql://", "postgres://"))
    destination = args.output_dir / f"realestate-{timestamp}.{ 'dump' if is_postgres else 'sqlite3' }"
    if is_postgres:
        backup_postgres(destination)
    else:
        backup_sqlite(destination)
    destination = encrypt_backup(destination)
    print(f"Backup created, verified, and encrypted as configured: {destination.resolve()}")


if __name__ == "__main__":
    main()
