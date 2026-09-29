"""Interactively apply PostgreSQL migrations without echoing credentials."""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import DatabaseAdapter


def main() -> None:
    connection_url = os.getenv("DATABASE_MIGRATION_URL") or getpass.getpass(
        "Migration-owner PostgreSQL URL (hidden; include sslmode=require): "
    ).strip()
    if not connection_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Migration URL must use PostgreSQL")
    database = DatabaseAdapter(connection_url, auto_migrate=True)
    try:
        if not database.health():
            raise RuntimeError("Database health check failed after migration")
        with database.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            versions = [row["version"] for row in cursor.fetchall()]
        print("Schema is current:", ", ".join(versions))
    finally:
        database.close()


if __name__ == "__main__":
    main()
