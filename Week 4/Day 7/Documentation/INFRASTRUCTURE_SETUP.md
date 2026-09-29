# Infrastructure Setup

This guide covers the external services that cannot be provisioned from the repository. Secrets must be entered through a secret manager, process environment, or the notebook's hidden runtime prompts. Never paste keys into source code, `.env` committed to Git, notebook output, or screenshots.

## 1. Local prerequisites

On Windows PowerShell:

```powershell
cd "f:\Web 3 Geeks Internship\Week 4\Day 7"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Grant the Python process microphone permission in Windows Privacy settings. The notebook microphone cell uses `sounddevice` and `soundfile`.

## 2. Deepgram STT

1. Create a Deepgram account and project.
2. Create a restricted API key with speech-to-text permission.
3. Select the Nova model required by the deployment.
4. Do not commit the key.
5. The notebook runtime configuration asks for it with hidden input.

The application setting is `STT_PROVIDER=deepgram`; the adapter sends WAV audio to the Deepgram listen endpoint with multilingual recognition enabled.

## 3. Fish Audio TTS

1. Create a Fish Audio account and API key.
2. Select an approved multilingual voice/model.
3. If using a cloned voice, obtain written voice-owner consent and configure the reference ID.
4. Test Pakistani names, place names, PKR amounts, Roman Urdu, Urdu, and English code-switching.

The application setting is `TTS_PROVIDER=fish_audio`. Do not claim Urdu pronunciation quality until native speakers score the selected voice.

## 4. Gemini intent classification

1. Create a Google AI Studio/Gemini project.
2. Create an API key with the minimum required model permission.
3. Select the approved model in `GEMINI_MODEL`.
4. In the Day 7 notebook, enter the model ID before the application import. The
	current default is `gemini-3.8-flash`; use the exact model enabled for the
	account if access differs.
5. Run the prompt-injection, booking, and transcript-normalization regression
	suite with the provider enabled.

The provider is used for intent classification and for transliterating
non-Roman STT output into Roman Urdu. The normalizer preserves English words,
names, numbers, and meaning; it does not translate or answer the caller. The
local classifier remains available for offline tests. Gemini must not be
allowed to authorize a consequential action; server-side availability,
confirmation, and idempotency checks remain authoritative.

## 4.1 Optional Groq fallback

1. Create a Groq account and a restricted API key.
2. Select an approved tool-capable model in `GROQ_MODEL`.
3. In the Day 7 notebook, enter the model ID before the application import.
	The current default is `openai/gpt-oss-120b`; use the exact model enabled
	for the account if access differs.
4. Set `LLM_FALLBACK_PROVIDER=groq`.
5. Enter the Groq key through the notebook's hidden runtime prompt or the deployment secret manager.

The recommended profile is Gemini primary plus Groq fallback. A failed Gemini
classification request is retried through Groq, then the application falls
back to its deterministic local classifier. Normalization uses the same
primary/fallback order; if both normalization calls fail or return non-Roman
text, the original transcript is retained and the failure is logged without
the transcript or credentials. Groq does not bypass server-side authorization,
calendar availability, booking confirmation, or idempotency.

## 5. Google Calendar

For a server-to-server property calendar, use a Google Cloud service account:

1. Create or select a Google Cloud project.
2. Enable the Google Calendar API.
3. Create a service account and download its JSON credentials securely.
4. Share the target Google Calendar with the service-account email and grant permission to manage events.
5. Set `GOOGLE_CALENDAR_ID` to the target calendar ID.
6. Select `CALENDAR_PROVIDER=google`.
7. In the notebook runtime configuration, select `google`, enter the local path to the JSON file, and enter the calendar ID. The notebook validates and loads the file into process memory without copying the secret into notebook source or output.
8. Run booking, conflict, rescheduling, and cancellation tests in a staging calendar.

The Google adapter uses FreeBusy, event insert, event patch, and event delete. A provider failure must be treated as an unconfirmed action.

## 6. Gmail

For a dedicated Gmail account, use an OAuth **Desktop app** client:

1. Enable the Gmail API in the same Google Cloud project.
2. Configure the OAuth consent screen and add the dedicated Gmail account as a test user while the app is in testing mode.
3. Create OAuth client credentials with application type **Desktop app**.
4. Download the OAuth client JSON file. Keep it outside the repository.
5. Set `EMAIL_PROVIDER=gmail` in the notebook runtime prompt.
6. Enter the local path to the OAuth client JSON when prompted.
7. A browser window opens on `http://localhost:8765/`; sign in to the dedicated Gmail account and approve the `gmail.send` scope.
8. Test booking, rescheduling, and cancellation notifications against an internal test mailbox.

The application keeps the OAuth credentials in process memory for the current
run. For a persistent server deployment, store an encrypted refresh token in a
secret manager rather than repeating interactive consent on every restart.

Service-account Gmail sending is only appropriate for Google Workspace with
domain-wide delegation. A normal consumer Gmail account should use the OAuth
Desktop app flow above.

The application persists the notification record only after the provider send succeeds. Configure retries and investigate orphaned provider messages during incident recovery.

## 7. Database

The local profile uses SQLite for reproducible tests. Production should use a managed PostgreSQL deployment with:

- private networking;
- TLS;
- encrypted storage;
- automated backups and restore tests;
- least-privilege application credentials;
- connection pooling;
- migration tooling;
- retention and deletion policies for transcripts and PII.

### Provision PostgreSQL

1. Create a managed PostgreSQL instance in a private network. Require TLS and use the provider's CA/hostname verification settings where supported.
2. Create a database and two login roles: `voice_agent_migrator` (schema owner/migration role) and `voice_agent_runtime` (application DML only). Enter passwords interactively with `\\password voice_agent_migrator` and `\\password voice_agent_runtime` in `psql`; do not put passwords in commands or this guide. Grant schema ownership/creation to the migration role, not the runtime role.
3. As the database owner, grant connection and migration schema rights:

```sql
GRANT CONNECT ON DATABASE realestate TO voice_agent_migrator;
GRANT CONNECT ON DATABASE realestate TO voice_agent_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO voice_agent_migrator;
```

4. Configure a protected libpq service file and password file for both roles. Set `PGSERVICEFILE` and `PGPASSFILE`; restrict the password file to the deployment account (Unix mode `0600`; use Windows ACLs on Windows).
5. Run the schema migration as the migration role. In the Day 7 notebook, choose PostgreSQL and enter the migration-role URL in the hidden prompt before app imports; for an initial smoke test, you can enter the same Neon URL for both migration and runtime prompts. For a standalone terminal migration, run the command below; it prompts for the URL without echoing it:

```powershell
python scripts/migrate_database.py
```

6. Apply runtime DML/default grants while connected as `voice_agent_migrator`. Set the psql variables first:

```text
\\set runtime_role voice_agent_runtime
\\set migration_role voice_agent_migrator
\\i migrations/runtime_role_grants.sql
```

The runtime role receives table DML and sequence privileges, not schema creation or migration rights. The migration role owns/creates schema objects. New migrations must be run as that owner so default privileges apply.

7. Configure `DATABASE_URL` for the runtime role with `sslmode=require` or stricter. Set `APP_ENV=production`, `DATABASE_AUTO_MIGRATE=false`, and tune `DATABASE_POOL_MIN_SIZE` / `DATABASE_POOL_MAX_SIZE` to the deployment connection budget.
8. Install dependencies and start the service only after migrations and grants are applied:

```powershell
python -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The migration command applies numbered SQL files in `migrations/` once and records versions in `schema_migrations`. The app uses a bounded psycopg connection pool, verifies all checked-in migrations are applied, requires TLS for production PostgreSQL URLs, and fails startup if the schema is behind.

### Backup and restore validation

Install the `age` utility and generate a public/private key pair for backups.
Store `BACKUP_AGE_RECIPIENT` (public key) in the scheduled-job configuration;
keep `BACKUP_AGE_IDENTITY_FILE` (private identity path) in a protected restore
environment only. In production, the backup script refuses to leave plaintext
archives if the recipient is not configured.

For SQLite, create and integrity-check an online backup (the output is encrypted
as `.age` when `BACKUP_AGE_RECIPIENT` is configured):

```powershell
python scripts/backup_database.py --output-dir backups
python scripts/restore_test.py backups/<backup-file>.sqlite3
```

For PostgreSQL, install the PostgreSQL client tools and configure a protected libpq service (`PGSERVICEFILE` / `PGSERVICE`) and password file (`PGPASSFILE`). The password must not be placed on the command line. Then:

```powershell
python scripts/backup_database.py --output-dir backups
```

The script creates a custom-format `pg_dump` archive, verifies it with `pg_restore --list`, then encrypts it with age. For a real restore drill, provision a disposable database whose name ends in `_restore_test`, configure `RESTORE_PGSERVICE`, `RESTORE_DATABASE_NAME`, and the protected `BACKUP_AGE_IDENTITY_FILE`, then run:

```powershell
python scripts/restore_test.py backups/<backup-file>.dump --postgres
```

The restore script refuses target names without the `_restore_test` suffix and uses `pg_restore --clean`; never point it at the production database.

### Schedule daily backups on Windows

1. Install `age` and PostgreSQL client tools if applicable. Generate an age key pair outside the repository with `age-keygen -o <protected-path>`. Store the printed public recipient in `BACKUP_AGE_RECIPIENT`; keep the private identity file protected and configure `BACKUP_AGE_IDENTITY_FILE` only for restore operators. Configure `PGSERVICEFILE`, `PGPASSFILE`, and `PGSERVICE` for the task account when using PostgreSQL.
2. Open **Task Scheduler** -> **Create Task**. Name it `RealEstateAgentDatabaseBackup` and choose a service account with write access to the backup directory and access to the required secret files.
3. Add a daily trigger at the approved low-traffic time.
4. Set **Program/script** to the project's Python executable, for example `F:\Web 3 Geeks Internship\Week 4\Day 7\.venv\Scripts\python.exe`.
5. Set **Arguments** to `scripts\backup_database.py --output-dir backups`.
6. Set **Start in** to `F:\Web 3 Geeks Internship\Week 4\Day 7`.
7. Run the task once manually, verify a `.age` artifact appears, and alert on a non-zero task result or stale latest-backup timestamp.
8. Schedule `python scripts/restore_test.py <latest-backup>.sqlite3.age` for SQLite verification, or `python scripts/restore_test.py <latest-backup>.dump.age --postgres` against a disposable `_restore_test` database at least monthly.

For container/cloud deployment, use the platform's scheduled job/CronJob with the same secret references; do not bake service files, PGPASSFILE, or age private identities into the image.

### Retention and deletion

Defaults are `TRANSCRIPT_RETENTION_DAYS=365`, `SESSION_RETENTION_DAYS=30`, and `MONITORING_RETENTION_DAYS=90`. Set these to the company-approved policy. Run the purge command on a controlled schedule (for example, a daily Windows Task Scheduler job or a daily container/Kubernetes CronJob):

```powershell
python scripts/purge_retained_data.py
```

`DatabaseAdapter.erase_customer_data(phone)` removes that customer's transcript and preferences, deletes sessions associated with their calls and email notification copies, and anonymizes retained appointment rows to preserve operational/audit history. Review legal retention requirements before enabling automated erasure in a client environment.

No database service can be provisioned from this repository. The service adapter, versioned schema, migration runner, online SQLite backup, PostgreSQL dump verification, restore test command, and retention operation are implemented; the managed instance, network policy, secret values, schedule, and successful staging restore remain deployment actions.

## 8. Vector database

The local profile builds a TF-IDF index at startup. For production:

1. Choose an approved hosted vector service or managed Postgres vector extension.
2. Store source documents and metadata in versioned object storage.
3. Attach property ID, source ID, language, effective date, approval state, and freshness metadata to every chunk.
4. Build the index in a staging namespace.
5. Run the 20-question grounding suite and compare retrieval results before promotion.
6. Refresh or invalidate vectors whenever approved brochures, FAQs, or descriptive property data changes.

Exact price, availability, appointment, and employee facts must continue to use structured retrieval.

## 9. n8n

1. Deploy n8n with its own persistent database and encrypted credential store.
2. Import `voice-agent-workflow.json` and the error-handler workflow.
3. Configure the FastAPI base URL and authentication header as n8n credentials, not plain text nodes.
4. Configure retry-on-fail with capped exponential backoff.
5. Route exhausted failures to the dead-letter/human-follow-up path.
6. Run one happy path, one transient failure, and one permanent failure in a staging workspace.

Do not connect production customer data until webhook authentication, replay protection, and retention are approved.

## 10. Telephony

The repository provides a microphone client and an HTTP `/voice/turn` contract. A real inbound-call deployment still needs a telephony/media provider:

1. Obtain a phone number and voice/media-stream capability.
2. Configure a secure webhook to the deployment.
3. Validate webhook signatures.
4. Convert media frames to the STT format or use the provider's supported stream.
5. Implement bidirectional media streaming, barge-in cancellation, call hangup, and retry behavior.
6. Pass a stable call ID into the agent for the lifetime of the call.
7. Test silence, noise, interruptions, duplicate webhooks, and call transfer.

## 11. Running the microphone notebook

1. Restart the notebook kernel.
2. Run cells from the beginning.
3. In the runtime configuration cell, choose providers and enter credentials when prompted. Input is hidden and values are held only in process memory.
4. Run the setup and validation cells.
5. Run the live microphone configuration cell.
6. Enter customer name and phone when prompted.
7. Run the conversation loop, press Enter, speak UrduLish, and wait for the spoken response.
8. Reuse the same loop for follow-ups such as budget, area, bedrooms, objections, and appointment requests.
9. Run the cleanup cell to stop a notebook-started server.

If a provider is unavailable, the notebook reports the failing stage and
returns to its prompt; it must not fabricate a transcript or audio response.
For normalization-only failures, the service safely retains the original STT
transcript so the turn can still follow the deterministic graph path.
If a provider is unavailable, the notebook reports the failing stage and
returns to its prompt; it must not fabricate a transcript or audio response.
For normalization-only failures, the service safely retains the original STT
transcript so the turn can still follow the deterministic graph path.

## 12. Production release checklist

- [ ] Secrets are in the deployment secret manager.
- [ ] No secret appears in Git, notebook source, outputs, logs, or screenshots.
- [ ] `/ready` is green with the intended provider profile.
- [ ] Voice smoke test passes with native UrduLish review.
- [ ] Calendar staging event is created, rescheduled, and cancelled.
- [ ] Internal employee email is delivered for each lifecycle action.
- [ ] PostgreSQL backup and restore test passes.
- [ ] Vector index grounding suite passes.
- [ ] n8n happy path and dead-letter path pass.
- [ ] Telephony signature and media-stream tests pass.
- [ ] Prompt-injection, authorization, rate-limit, and PII tests pass.
- [ ] Rollback artifact and incident owner are documented.
