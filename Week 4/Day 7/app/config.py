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
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
MAX_AUDIO_BYTES = int(os.getenv("MAX_AUDIO_BYTES", str(10 * 1024 * 1024)))
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]

# SQLite is the local default. PostgreSQL production settings, pooling, and
# migration-role separation are implemented by DatabaseAdapter.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/realestate_agent.db")
DATABASE_MIGRATION_URL = os.getenv("DATABASE_MIGRATION_URL", DATABASE_URL)
DATABASE_AUTO_MIGRATE = os.getenv(
    "DATABASE_AUTO_MIGRATE", "false" if APP_ENV == "production" else "true"
).lower() == "true"
DATABASE_POOL_MIN_SIZE = int(os.getenv("DATABASE_POOL_MIN_SIZE", "1"))
DATABASE_POOL_MAX_SIZE = int(os.getenv("DATABASE_POOL_MAX_SIZE", "10"))
TRANSCRIPT_RETENTION_DAYS = int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "365"))
SESSION_RETENTION_DAYS = int(os.getenv("SESSION_RETENTION_DAYS", "30"))
MONITORING_RETENTION_DAYS = int(os.getenv("MONITORING_RETENTION_DAYS", "90"))

VECTOR_DATABASE_URL = os.getenv("VECTOR_DATABASE_URL", "local://tfidf-vector-store")

STT_PROVIDER = os.getenv("STT_PROVIDER", "local-adapter")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "local-adapter")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local-adapter")
LLM_FALLBACK_PROVIDER = os.getenv("LLM_FALLBACK_PROVIDER", "groq")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY", "")
FISH_AUDIO_MODEL = os.getenv("FISH_AUDIO_MODEL", "s1")
FISH_AUDIO_REFERENCE_ID = os.getenv("FISH_AUDIO_REFERENCE_ID", "")

GOOGLE_CALENDAR_CREDENTIALS_JSON = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_JSON", "")
GMAIL_CREDENTIALS_JSON = os.getenv("GMAIL_CREDENTIALS_JSON", "")
GMAIL_OAUTH_CLIENT_SECRETS_JSON = os.getenv("GMAIL_OAUTH_CLIENT_SECRETS_JSON", "")
CALENDAR_PROVIDER = os.getenv("CALENDAR_PROVIDER", "local")
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "local")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GMAIL_SENDER = os.getenv("GMAIL_SENDER", "me")

# When set, calendar_service/email_service will refuse to start in "production"
# APP_ENV without real credentials, instead of silently falling back -- see
# calendar_service.py / email_service.py.
REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION = os.getenv(
    "REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION", "true"
).lower() == "true"
