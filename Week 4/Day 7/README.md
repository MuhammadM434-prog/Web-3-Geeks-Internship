# Real Estate Voice Agent — Production Service

This is the actual, integrated system: one FastAPI service that really invokes
a compiled LangGraph agent, which really calls a SQLite-backed calendar/
email/CRM layer and a real TF-IDF RAG index. It consolidates Days 2, 4, and 5
of the capstone into one running program instead of separate notebooks that
each re-simulated the same logic in isolation.

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

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

Six tests, all exercising the real stack end-to-end (FastAPI → LangGraph →
SQLite): health/ready, a full booking conversation including a real slot
conflict and a real retry, sold-property exclusion, RAG abstention on an
unsupported investment claim, prompt-injection resistance, and a metrics
sanity check.

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
- **CRM / dead-letter / monitoring** (`database.py`): a real SQLite database
  with real tables, not an in-memory list — it survives a process restart.
- **The agent itself** (`graph.py`): the actual compiled LangGraph state
  machine, invoked directly by FastAPI on every request. There is no
  fallback branch that returns a canned string.
- **Multi-turn state**: `main.py` keeps real per-`call_id` session state, so
  budget/area/matched-property/appointment context genuinely carries across
  separate HTTP requests — a real phone call, not a stateless one-shot.

## What's honestly still a gap (do not claim otherwise)

- **No real audio path.** This service accepts already-transcribed text
  turns. There is no STT/TTS integration — wiring a real Deepgram/Whisper +
  Fish Audio/ElevenLabs pair in front of `/agent/turn` is unbuilt work, not a
  hidden feature.
- **No real Google Calendar / Gmail connection.** The calendar/email layers
  are fully functional *local* implementations (real conflict detection,
  real persistence) but do not call Google's APIs. `GOOGLE_CALENDAR_CREDENTIALS_JSON`
  / `GMAIL_CREDENTIALS_JSON` are accepted as config but unused until that
  integration is written.
- **No Postgres driver.** `DatabaseAdapter` raises loudly if `DATABASE_URL`
  is a `postgresql://` URL, rather than silently downgrading to SQLite —
  intentional, so a misconfigured production deploy fails at startup instead
  of quietly running on a file no one is backing up.
- **Intent parsing is regex/keyword-based**, not an LLM call — the same
  convention every earlier day in this capstone used to stay runnable
  without an API key. `intent_detection_node` in `graph.py` is the single
  swap point for a real LLM call or native tool-calling.
