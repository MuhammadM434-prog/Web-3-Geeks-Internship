# Real Estate Voice Agent — Production Service

This is the actual, integrated system: one FastAPI service that really invokes
a compiled LangGraph agent, which really calls a SQLite-backed calendar/
email/CRM layer locally or a pooled PostgreSQL layer in production, alongside
a real TF-IDF RAG index. It consolidates Days 2, 4, and 5
of the capstone into one running program instead of separate notebooks that
each re-simulated the same logic in isolation.

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

For the real microphone workflow, configure the provider-backed voice path
before starting the service:

```powershell
$env:STT_PROVIDER = "deepgram"
$env:DEEPGRAM_API_KEY = "your-deepgram-key"
$env:TTS_PROVIDER = "fish_audio"
$env:FISH_AUDIO_API_KEY = "your-fish-audio-key"
$env:LLM_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "your-gemini-key"
$env:LLM_FALLBACK_PROVIDER = "groq"
$env:GROQ_API_KEY = "your-groq-key"
```

Gemini is the primary reasoning provider in the recommended profile. If a
Gemini classification request fails, the configured Groq model is attempted
before the deterministic local classifier. The fallback never authorizes a
booking by itself; application-side availability, confirmation, and
idempotency checks remain authoritative.

Then execute the `Live microphone conversation` section in
`Week4Day7Task1_RealEstateVoiceAgent.ipynb`. It records WAV turns, sends them
to `/voice/turn`, plays the returned MP3, and reuses one `call_id` so customer
preferences and appointment context persist.

For PostgreSQL, create the schema with the migration-owner credential before
starting the app:

```powershell
python scripts/migrate_database.py
```

The app uses the runtime `DATABASE_URL` and requires the schema to exist when
`APP_ENV=production`. The migration command prompts for the privileged URL
without echoing it; the notebook prompts separately for the restricted runtime
URL. See [Documentation/INFRASTRUCTURE_SETUP.md](Documentation/INFRASTRUCTURE_SETUP.md)
for managed PostgreSQL roles, backups, restore validation, and retention.

SQLite backup and restore checks:

```powershell
python scripts/backup_database.py --output-dir backups
python scripts/restore_test.py backups/<backup-file>.sqlite3
```

Provider account creation, Google Calendar/Gmail setup, PostgreSQL, vector
database, n8n, telephony, and the release checklist are documented in
[Documentation/INFRASTRUCTURE_SETUP.md](Documentation/INFRASTRUCTURE_SETUP.md).

Then:

```bash
curl -X POST http://127.0.0.1:8000/agent/turn -H "Content-Type: application/json" \
  -d '{"call_id":"CALL-1","client_name":"Bilal Farooq","client_phone":"+92-321-5551042"}'

curl -X POST http://127.0.0.1:8000/agent/turn -H "Content-Type: application/json" \
  -d '{"call_id":"CALL-1","text":"Budget 4 crore hai, Bahria Town mein 3 bedroom ghar chahiye"}'

curl -X POST http://127.0.0.1:8000/agent/turn -H "Content-Type: application/json" \
  -d '{"call_id":"CALL-1","text":"4pm par visit book kar dain"}'
```

The second call returns a real matched, available property. The third call
creates a real row in the `appointments` table and a real notification row
in `emails_sent` — check `/metrics` or query `./data/realestate_agent.db`
directly to see it.

## Test it

```bash
pip install pytest httpx
pytest -v
```

The suite exercises the real stack end-to-end (FastAPI -> LangGraph ->
configured relational backend), including health/readiness, booking conflict and retry,
sold-property exclusion, RAG abstention, prompt-injection resistance,
durable session recovery, appointment lifecycle rules, objection handling,
and monitoring. Use the test count printed by pytest as the authoritative
result for the current checkout.

## Docker

```bash
docker build -t realestate-voice-agent .
docker run -p 8000:8000 -v $(pwd)/data:/app/data realestate-voice-agent
```

## What's genuinely real in this build

- **Recommendation engine** (`recommendation.py`): hard filters (budget,
  area, bedrooms, purpose) + transparent scoring, over a real property
  catalog.
- **RAG** (`knowledge_base.py`): a real scikit-learn TF-IDF index with cosine
  similarity and a relevance threshold — it actually returns no evidence
  (and the agent actually abstains) when nothing is grounded.
- **Calendar** (`calendar_service.py`): real overlap/conflict detection
  against persisted events, real idempotency (a retried booking is a true
  no-op), real alternative-slot suggestion.
- **Email** (`email_service.py`): real idempotent sends, persisted, generated
  fresh from the current appointment record so it can't drift from what's
  actually booked.
- **CRM / dead-letter / monitoring** (`database.py`): durable SQLite locally or
  pooled PostgreSQL in production, with versioned migrations, retention, and
  customer-data erasure support.
- **The agent itself** (`graph.py`): the actual compiled LangGraph state
  machine, invoked directly by FastAPI on every request. There is no
  fallback branch that returns a canned string.
- **Multi-turn state**: `main.py` persists real per-`call_id` session state, so
  budget/area/matched-property/appointment context genuinely carries across
  separate HTTP requests — a real phone call, not a stateless one-shot.

## What's honestly still a gap (do not claim otherwise)

- **Voice requires provider configuration.** `/voice/turn` accepts WAV audio
  and connects Deepgram STT to Fish Audio TTS, but local mode correctly refuses
  audio processing until those providers and credentials are enabled.
- **Live Calendar/Gmail require provider configuration.** Set
  `CALENDAR_PROVIDER=google` and `EMAIL_PROVIDER=gmail` with valid credentials
  for real external side effects; local mode remains deterministic for tests.
- **Production operations still need provisioning.** Create a managed
  PostgreSQL instance, run migrations with the migration role, configure the
  runtime DML-only role, and validate encrypted backups/restores before go-live.
- **Intent parsing is regex/keyword-based**, not an LLM call — the same
  convention every earlier day in this capstone used to stay runnable
  without an API key. `intent_detection_node` in `graph.py` is the single
  swap point for a real LLM call or native tool-calling.
