# Week 4 --- Day 7: API Documentation

## 1. Purpose

The FastAPI service is the HTTP entry point for the real-estate
voice-agent application.

The exact route names and request models are defined by the deployed
`app.main` module. This document describes the contract at the system
level and should be kept synchronized with the route definitions
whenever the API changes.

## 2. Application

The application is imported from:

``` python
from app.main import app
```

The LangGraph workflow is imported from:

``` python
from app.graph import COMPILED_GRAPH
```

The operational database/tool layer is imported from:

``` python
from app.tools import DB
```

## 3. Request lifecycle

``` text
HTTP request
  -> validation
  -> conversation state
  -> LangGraph orchestration
  -> retrieval / database / calendar / email tools
  -> state update
  -> response
```

## 4. Expected API capabilities

The deployed API must support the application capabilities demonstrated
by the Day 7 validation flow:

-   Customer conversation / voice-agent interaction
-   Property inquiry
-   Property recommendation
-   Grounded RAG answers
-   Appointment availability checking
-   Appointment creation
-   Appointment rescheduling
-   Appointment cancellation
-   Calendar event creation
-   Employee notification
-   Safe refusal / abstention
-   Prompt-injection resistance
-   Non-Roman STT transcript normalization with provider fallback
-   Operational metrics / health monitoring

## 4.1 Exact endpoints

| Method | Path | Purpose | Success response |
|---|---|---|---|
| `GET` | `/health` | Liveness check. | Service status and environment. |
| `GET` | `/ready` | Dependency readiness check. | Per-provider checks and aggregate status. |
| `GET` | `/metrics` | Monitoring summary and alerts. | Event count, latency, failures, success rate, alerts. |
| `POST` | `/agent/turn` | Process one already-transcribed conversation turn. | Responses, intent, appointment status, latency. |
| `POST` | `/voice/turn` | Decode audio, call STT, process the graph, and synthesize TTS. | Transcript, UrduLish response, base64 MP3 audio. |
| `POST` | `/agent/reset/{call_id}` | Delete durable conversation state for a call. | Reset status and call ID. |

When `API_AUTH_TOKEN` is configured, all endpoints except `/health` and
`/ready` require either `X-API-Key: <token>` or `Authorization: Bearer <token>`.
POST requests are rate-limited by client address using `RATE_LIMIT_PER_MINUTE`.

### `/agent/turn` request

```json
{
  "call_id": "CALL-1",
  "text": "Budget 4 crore hai, Bahria Town mein ghar chahiye",
  "client_name": "Bilal Farooq",
  "client_phone": "+92-321-5551042"
}
```

### `/voice/turn` request

```json
{
  "call_id": "CALL-1",
  "audio_base64": "<base64 encoded WAV>",
  "mime_type": "audio/wav",
  "client_name": "Bilal Farooq",
  "client_phone": "+92-321-5551042"
}
```

Audio is rejected when empty or larger than `MAX_AUDIO_BYTES`. Provider
failures return a safe `503` response; internal credentials, stack traces, and
provider payloads are not returned to callers.

When the STT transcript contains Devanagari or another non-Roman script, the
service attempts Roman Urdu transliteration before conversation processing.
The normalizer uses the configured model IDs from `GEMINI_MODEL` and
`GROQ_MODEL`; those IDs are entered by the notebook setup cell or supplied as
environment variables before `app.main` is imported. A failed normalizer does
not fabricate text: the original transcript is retained, and the graph's
normal clarification or intent behavior applies.

## 5. Error behavior

Public errors should be actionable but must not expose:

-   stack traces
-   database credentials
-   provider credentials
-   hidden prompts
-   internal file paths
-   raw exception objects
-   private customer records

Typical public outcomes are:

  -----------------------------------------------------------------------
  Situation                           Expected behavior
  ----------------------------------- -----------------------------------
  Missing required input              Validation response

  Property not found                  Explain that no matching grounded
                                      record was found

  Insufficient RAG evidence           Abstain rather than invent

  Sold property                       Exclude from active recommendations

  Appointment conflict                Do not create the conflicting
                                      booking; offer another slot

  Calendar provider failure           Return a safe retry/escalation
                                      message

  Email failure                       Preserve appointment state and
                                      record notification failure

  Prompt injection                    Refuse the instruction and continue
                                      protecting system behavior
  -----------------------------------------------------------------------

## 6. Testing

The Day 7 notebook should be executed with the project dependencies
installed and the application importable. The important integration
assertions include:

-   application imports successfully;
-   compiled LangGraph workflow is available as `COMPILED_GRAPH`;
-   appointment creation creates the expected database row;
-   email notification creates the expected `emails_sent` record;
-   a seeded 3 PM conflict is detected;
-   retry at 4 PM succeeds;
-   sold properties are excluded;
-   unsupported RAG questions produce abstention;
-   prompt injection does not override the agent's rules;
-   metrics are produced.
-   non-Roman transcript normalization uses a provider result when available
  and retains the original text after provider failure.

The saved notebook also contains a real microphone client with 250 ms audio
chunks, speech detection, a silence timeout, a 15-second maximum turn, WAV
upload, and MP3 playback. It is a turn-based HTTP client, not a full-duplex
telephony implementation.

## 7. Deployment check

A deployment should not be called production-ready until the real
service, real database, retrieval layer, calendar integration, and email
integration have all been exercised in the target environment.

A notebook that merely imports the modules is an integration smoke test,
not proof of production uptime.
