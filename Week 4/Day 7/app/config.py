"""
Environment-driven configuration.

Every external dependency (a real Postgres, a hosted vector DB, a real STT/TTS
provider, a real Google Calendar / Gmail account) is selected through an
environment variable. Nothing here is hardcoded, and nothing pretends a paid
provider is connected when it isn't -- the *local* backing implementation
(SQLite file, TF-IDF vector index) is real and fully functional on its own,
it's just not the hosted product named in the env var.
"""
from __future__ import annotations

import os

APP_ENV = os.getenv("APP_ENV", "local")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Real, working local default: a SQLite file on disk. Point DATABASE_URL at a
# postgresql:// URL in production and swap DatabaseAdapter's engine (see
# database.py) -- the call sites in tools.py/main.py do not change.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/realestate_agent.db")

VECTOR_DATABASE_URL = os.getenv("VECTOR_DATABASE_URL", "local://tfidf-vector-store")

STT_PROVIDER = os.getenv("STT_PROVIDER", "local-adapter")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "local-adapter")

GOOGLE_CALENDAR_CREDENTIALS_JSON = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_JSON", "")
GMAIL_CREDENTIALS_JSON = os.getenv("GMAIL_CREDENTIALS_JSON", "")

# When set, calendar_service/email_service will refuse to start in "production"
# APP_ENV without real credentials, instead of silently falling back -- see
# calendar_service.py / email_service.py.
REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION = os.getenv(
    "REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION", "true"
).lower() == "true"
