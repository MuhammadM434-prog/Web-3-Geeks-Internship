"""Run the configured transcript/session/monitoring retention policy."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import DatabaseAdapter


def main() -> None:
    database = DatabaseAdapter()
    try:
        deleted = database.purge_expired_data()
        print("Expired data removed:", deleted)
    finally:
        database.close()


if __name__ == "__main__":
    main()
