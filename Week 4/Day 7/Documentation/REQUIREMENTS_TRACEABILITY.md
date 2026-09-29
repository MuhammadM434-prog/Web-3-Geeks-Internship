# Requirements Traceability

This matrix is the acceptance record for the Week 4 real-estate voice-agent capstone. `COMPLETE` means implemented and verified locally. `PARTIAL` means the local implementation is real but an external provider, live credentials, or production-scale component still requires staging verification. `NOT TESTED` means the code path exists but cannot be verified without the external dependency. The Day 7 service is the current integration surface; earlier notebooks remain supporting design, evaluation, and simulation artifacts.

## Day 1

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| Voice-agent architecture: STT, LLM, tools, retrieval, memory, TTS, telephony, orchestration, streaming, interruption, latency | Architecture notebook and Day 7 service: `app/voice_service.py`, `app/graph.py`, FastAPI `/voice/turn` | PARTIAL | Telephony media streaming and provider TTFA require staging accounts | Day 3 notebook; Day 7 voice endpoint |
| Buyer, rental, commercial, investment, returning-customer, reschedule, cancellation flows | Day 1 flow diagrams; graph routing and appointment services | PARTIAL | Some conversational branches need live voice evaluation | Day 1 notebook; `tests/test_agent.py` |
| UrduLish persona and natural speech behavior | Day 1 prompt and graph responses | PARTIAL | Native-speaker scoring remains required | Day 3 rubric and microphone notebook |
| Fish Audio integration and provider comparison | `app/voice_service.py`, Day 1 evaluation | PARTIAL | Requires `FISH_AUDIO_API_KEY`, live latency and Urdu pronunciation benchmark | `/voice/turn`; Day 3 evaluation |
| Production system prompt, guardrails, persuasion, booking and escalation | Day 1 system prompt and server-side validation | COMPLETE locally | Live LLM structured-output regression required when Gemini is enabled | Injection and booking tests |

## Day 2

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| Properties, prices, locations, amenities, schools, hospitals, payment plans, developers, FAQs | Day 2 dataset and `app/knowledge_base.py` | COMPLETE locally | Replace catalog with approved client inventory before launch | Dataset integrity assertions |
| Document loading, cleaning, chunking, embeddings, vector store, retrieval, metadata, answer generation | TF-IDF vector index and RAG contract | PARTIAL | TF-IDF is local; hosted embeddings/vector DB and LLM answer generation require deployment choice | RAG abstention tests |
| Chunk-size evaluation | Day 2 notebook evaluation | PARTIAL | Benchmark must be rerun with final documents and embedding model | Day 2 notebook |
| Structured SQL versus semantic retrieval | `app/recommendation.py`, `app/database.py`, `app/knowledge_base.py` | COMPLETE locally | PostgreSQL migration required for production scale | Recommendation/RAG tests |
| Explainable property recommendation using budget, city, area, bedrooms, purpose, amenities, investment goals, type, availability | `app/recommendation.py`, graph recommendation node | COMPLETE locally | Client inventory freshness and live availability feed required | Sold-property and recommendation tests |
| Twenty-question hallucination evaluation | Day 2 notebook | COMPLETE as offline regression | Production LLM/native-speaker evaluation still required | Day 2 metrics |

## Day 3

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| Speech -> STT -> transcript normalization -> LangGraph -> TTS voice path | `/voice/turn`, Deepgram adapter, LLM normalizer with Gemini/Groq fallback, Fish Audio adapter, microphone notebook client | PARTIAL | Requires provider credentials, model access, and a live audio smoke test | Voice endpoint, normalization regression tests, and microphone cells |
| Streaming and under-two-second latency measurement | Day 3 async simulation and monitoring metrics | PARTIAL | Current HTTP voice path is turn-based, not full duplex; measure provider TTFA in staging | Day 3 benchmark |
| Interruptions, fillers, pauses, acknowledgements, turn-taking | Day 1 prompt, Day 3 pipeline simulation, graph responses | PARTIAL | Full-duplex barge-in requires a media gateway | Day 3 human evaluation |
| Context memory including profile, budget, location, bedrooms, purpose, preferences, rejected and shortlisted properties, appointment state, history | SQLite/PostgreSQL sessions and expanded `VoiceAgentState` | COMPLETE locally | Cross-call identity/consent policy needs client decision | Durable session recovery test |
| Price, trust, location, investment, builder, maintenance objections | Day 3 objection handler and graph responses | COMPLETE locally | Native-speaker quality review required | Objection tests/notebook |
| Human evaluation framework | CSV template and Day 3 rubric | PARTIAL | Real recordings and reviewer scores are still required | Human evaluation template |

## Day 4

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| Google Calendar event with client, phone, employee, property, date, time and notes | `CalendarService` local mode and optional Google API mode | PARTIAL | Configure service-account/OAuth credentials and staging calendar | Calendar unit tests; `/ready` in Google mode |
| Availability verification and double-booking prevention | SQLite overlap check plus Google FreeBusy query | COMPLETE locally / PARTIAL live | Concurrent production writes need PostgreSQL transaction/locking | Conflict/retry tests |
| Employee email notification | `EmailService` local persistence plus optional Gmail API sender | PARTIAL | Configure Gmail credentials and verify delivery | Email persistence tests; staging Gmail |
| Booking, rescheduling, cancellation and synchronized notifications | Calendar service, graph routes, email and appointment history | PARTIAL | Live provider synchronization and notification-failure replay need staging | Lifecycle tests |
| n8n Call -> Intent -> Property -> Appointment -> Calendar -> Email -> CRM workflow | Day 4 workflow JSON and retry/dead-letter simulation | PARTIAL | Import and execute workflow against deployed API/n8n instance | JSON import smoke test |
| CRM logging: call, transcript, customer, preferences, budget, interests, recommendations, appointments, reminders, timestamps, status | SQLite CRM tables, per-turn transcript/preferences logging, appointment history | COMPLETE locally | PostgreSQL/CRM connector and retention policy required for production | CRM queries and tests |

## Day 5

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| LangGraph state | `app/state.py` | COMPLETE locally | Add provider trace correlation in production | State and graph tests |
| Graph routing | `app/graph.py`, compiled `COMPILED_GRAPH` used by FastAPI | COMPLETE locally | Live LLM routing needs provider regression suite | FastAPI integration tests |
| Property, availability, Calendar, email, CRM, RAG and appointment tools | `app/tools.py` and service adapters | COMPLETE locally / PARTIAL live | External credentials and authorization policy required | Tool and integration tests |
| Validation and clarification | Eligibility, availability, abstention and refusal branches | COMPLETE locally | Expand ambiguous/unauthorized action tests | Security and lifecycle tests |
| State transition traces | `execution_trace`, monitoring events, dead-letter records | COMPLETE locally | Export traces to production observability backend | `/metrics` and graph tests |

## Day 6

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| At least 40 conversations across required categories | Day 6 deterministic evaluation suite | COMPLETE offline | Run against configured live voice stack | Day 6 notebook |
| Prompt-injection attacks and safe refusal | Day 6 suite and graph guardrails | COMPLETE locally | Add authenticated authorization and retrieved-document injection staging tests | Security regression tests |
| Latency, success, booking, tool failure, RAG, memory and hallucination metrics | Day 6 metrics and Day 7 monitoring | PARTIAL | Provider-dependent metrics must be measured, not simulated | `/metrics`; live benchmark |
| Monitoring and structured logging without secrets | `MonitoringService`, database events, auth/rate controls | COMPLETE locally | Connect metrics/logs to production backend and redact policy review | Monitoring tests |
| Docker, env, health, readiness, CI/CD, startup validation | Dockerfile, `.env.example`, CI workflow, `/health`, `/ready`, migration runner | PARTIAL | Pin dependencies and run managed PostgreSQL staging checks | CI and migration integration tests |

## Day 7

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| FastAPI, voice services, transcript normalization, LangGraph, vector layer, relational DB, monitoring, workflow automation | Day 7 app package and workflow artifacts | PARTIAL | Telephony, hosted vector DB, PostgreSQL operations, live n8n deployment, and provider acceptance remain environment work | Day 7 tests, Docker/CI, and integration tests |
| README and installation/configuration docs | Day 7 README, `.env.example`, notebook prompts, and handover package | COMPLETE locally | Add client-specific OAuth and deployment values | Documentation review |
| Exact API documentation | `Documentation/02_api_documentation.md`, FastAPI OpenAPI | PARTIAL | Keep generated OpenAPI artifact in release package | `/openapi.json` |
| User, admin, maintenance, troubleshooting guides | Documentation package | COMPLETE locally | Client-specific operational ownership required | Documentation review |
| Monitoring and maintenance plan | `05_maintenance_plan.md` | COMPLETE as policy | Calibrate thresholds using live baseline | Maintenance review |
| Ten-minute stakeholder demo | `07_stakeholder_demo.md` | PARTIAL | Live Calendar/Gmail/voice demo requires credentials | Demo checklist |
| Future enhancements | `08_future_enhancements.md` | COMPLETE as roadmap | Clearly marked as future | Documentation review |

## Cross-cutting security and quality

| Requirement | Implementation | Status | Gap / required acceptance | Verification |
|---|---|---|---|---|
| Secret management | Environment configuration, no committed `.env` | COMPLETE locally | Secret manager and rotation in deployment | Repository scan |
| API authentication | Optional bearer/API-key middleware | COMPLETE locally | Set `API_AUTH_TOKEN` in production and add identity/role provider | Auth tests |
| Rate limiting | Configurable per-client request limiter | COMPLETE locally | Replace process-local limiter with shared gateway/Redis at scale | Middleware tests |
| Input validation and safe errors | Pydantic requests, audio-size checks, provider error normalization, safe transcript-normalizer fallback | COMPLETE locally | Add schema fuzzing and authenticated authorization tests | API and normalization tests |
| SQL injection | Parameterized SQLite queries | COMPLETE locally | PostgreSQL driver must preserve parameterization | Database review |
| CORS | Explicit `ALLOWED_ORIGINS` middleware | COMPLETE locally | Configure exact production origins | Startup configuration |
| PII/transcript handling | Durable CRM tables, configurable retention purge, customer erasure/anonymization | PARTIAL | Set company-approved retention periods and verify managed storage encryption/access controls | Retention and erasure tests |
| Dependency and container security | Requirements, Dockerfile, PostgreSQL pooled driver | PARTIAL | Pin versions and run dependency/image scanning in CI | CI hardening |

| PostgreSQL backend, pool, migrations, concurrency constraints | psycopg pool, `migrations/001_initial.sql`, migration runner, atomic employee booking/reschedule locks | COMPLETE locally / PARTIAL managed | Apply migrations with owner role; verify provider TLS and runtime grants in staging | SQLite atomic tests; PostgreSQL staging smoke tests |
| Automated encrypted backup and restore verification | `scripts/backup_database.py`, `scripts/restore_test.py`, age encryption | COMPLETE tooling / NOT TESTED managed | Configure scheduled backups and run disposable PostgreSQL restore drill | SQLite integrity test; PostgreSQL restore acceptance |

## Release decision

The local capstone is testable and integrated: the current service includes
durable multi-turn state, transcript normalization fallback, provider-safe
errors, authentication/rate controls, calendar/email lifecycle handling, and
the documented regression suite. Production go-live still requires a staging
acceptance run with real Deepgram, Fish Audio, Gemini/Groq model access,
Google Calendar, Gmail, PostgreSQL roles, vector-store, n8n, telephony,
backups, and observability credentials. No local test result is presented as
proof of those external systems.
