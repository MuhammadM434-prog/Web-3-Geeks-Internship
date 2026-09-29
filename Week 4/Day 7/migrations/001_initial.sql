-- PostgreSQL initial schema for the real-estate voice agent.
-- The application applies the equivalent idempotent schema at startup.

CREATE TABLE IF NOT EXISTS call_transcripts (
    call_id TEXT PRIMARY KEY,
    client_name TEXT,
    client_phone TEXT,
    transcript TEXT NOT NULL,
    intent TEXT,
    logged_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS client_preferences (
    client_phone TEXT PRIMARY KEY,
    client_name TEXT,
    preferred_city TEXT,
    preferred_area TEXT,
    budget_pkr BIGINT,
    property_type TEXT,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT PRIMARY KEY,
    calendar_event_id TEXT NOT NULL,
    call_id TEXT,
    client_name TEXT,
    client_phone TEXT,
    employee_id TEXT,
    property_id TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    status TEXT NOT NULL,
    requirements TEXT,
    idempotency_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS appointments_employee_time_idx
    ON appointments (employee_id, start_time, end_time);

CREATE TABLE IF NOT EXISTS appointment_history (
    id BIGSERIAL PRIMARY KEY,
    appointment_id TEXT NOT NULL REFERENCES appointments(appointment_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    detail TEXT,
    occurred_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS emails_sent (
    message_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    related_appointment_id TEXT REFERENCES appointments(appointment_id) ON DELETE SET NULL,
    sent_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id BIGSERIAL PRIMARY KEY,
    call_id TEXT,
    failed_node TEXT,
    error_message TEXT,
    failed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review'
);

CREATE TABLE IF NOT EXISTS monitoring_events (
    id BIGSERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    call_id TEXT,
    latency_ms DOUBLE PRECISION,
    success INTEGER,
    detail TEXT,
    occurred_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    call_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS call_transcripts_logged_at_idx
    ON call_transcripts (logged_at);
CREATE INDEX IF NOT EXISTS conversation_sessions_updated_at_idx
    ON conversation_sessions (updated_at);
CREATE INDEX IF NOT EXISTS monitoring_events_occurred_at_idx
    ON monitoring_events (occurred_at);
