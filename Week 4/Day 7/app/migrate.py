"""Apply checked-in PostgreSQL migrations using DATABASE_MIGRATION_URL."""
from __future__ import annotations

from app.config import DATABASE_MIGRATION_URL
from app.database import DatabaseAdapter


def main() -> None:
    database = DatabaseAdapter(DATABASE_MIGRATION_URL, auto_migrate=True)
    try:
        if database.backend != "postgresql":
            raise SystemExit("The migration command is for PostgreSQL; SQLite initializes automatically.")
        with database.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            versions = [row["version"] for row in cursor.fetchall()]
        print("Applied migrations:", ", ".join(versions) if versions else "none")
    finally:
        database.close()


if __name__ == "__main__":
    main()
