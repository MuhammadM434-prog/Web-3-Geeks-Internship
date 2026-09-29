"""
FastAPI service boundary.

The critical difference from the earlier Day 7 draft: ``/agent/turn`` invokes
``app.graph.COMPILED_GRAPH`` directly -- the real Day 5 LangGraph agent,
wired to real tools -- for every request. There is no ``if CompiledGraph is
not None`` fallback branch and no canned "request received" string; if the
graph raises, the endpoint returns a 500 and logs a dead-letter row instead
of pretending to succeed.

Conversation state is persisted per ``call_id`` in the configured database so a
multi-turn phone call carries context (budget, matched property, appointment)
across separate HTTP requests, worker restarts, and later replicas that share
the same database.
"""
from __future__ import annotations

import time
import base64
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import (
    ALLOWED_ORIGINS,
    API_AUTH_TOKEN,
    APP_ENV,
    MAX_AUDIO_BYTES,
    RATE_LIMIT_PER_MINUTE,
    REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION,
)
from app.graph import COMPILED_GRAPH
from app.monitoring import MonitoringService
from app.state import VoiceAgentState, initial_state
from app.tools import CALENDAR, DB, EMAIL, VECTOR_DB
from app.voice_service import SpeechProviderError, build_stt, build_tts

MONITORING = MonitoringService(DB)
SESSION_LOCKS: defaultdict[str, RLock] = defaultdict(RLock)
STT = build_stt()
TTS = build_tts()

app = FastAPI(title="Real Estate Voice Agent", version="1.0.0")
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

_rate_limit_lock = RLock()
_rate_limit_buckets: defaultdict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_security_middleware(request: Request, call_next):
    if API_AUTH_TOKEN and request.url.path not in {"/health", "/ready"}:
        supplied = request.headers.get("x-api-key", "")
        if not supplied:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if supplied != API_AUTH_TOKEN:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})

    if RATE_LIMIT_PER_MINUTE > 0 and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _rate_limit_lock:
            bucket = _rate_limit_buckets[client_key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= RATE_LIMIT_PER_MINUTE:
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
            bucket.append(now)
    return await call_next(request)


class TurnRequest(BaseModel):
    call_id: str
    text: str | None = None
    client_name: str | None = None
    client_phone: str | None = None


class TurnResponse(BaseModel):
    call_id: str
    responses: list[str]
    intent: str | None
    appointment_status: str
    latency_ms: float


class VoiceTurnRequest(BaseModel):
    call_id: str
    audio_base64: str
    mime_type: str = "audio/wav"
    client_name: str | None = None
    client_phone: str | None = None


class VoiceTurnResponse(BaseModel):
    call_id: str
    transcript: str
    response: str
    audio_base64: str
    audio_mime_type: str = "audio/mpeg"


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "real-estate-voice-agent", "environment": APP_ENV}


@app.get("/ready")
def ready() -> dict[str, Any]:
    checks = {
        "database": DB.health(),
        "vector_database": VECTOR_DB.health(),
        "calendar_service": CALENDAR.health(),
        "email_service": EMAIL.health(),
        "stt_provider": STT.health() or not (APP_ENV == "production" and REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION),
        "tts_provider": TTS.health() or not (APP_ENV == "production" and REQUIRE_LIVE_PROVIDERS_IN_PRODUCTION),
    }
    is_ready = all(checks.values())
    return {"status": "ready" if is_ready else "not_ready", "checks": checks}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return {"summary": MONITORING.summary(), "alerts": MONITORING.alerts()}


@app.post("/agent/turn", response_model=TurnResponse)
def agent_turn(request: TurnRequest) -> TurnResponse:
    started = time.perf_counter()
    success = True
    with SESSION_LOCKS[request.call_id]:
        try:
            state = DB.get_session(request.call_id)
            if state is None:
                state = initial_state(
                    call_id=request.call_id,
                    client_name=request.client_name or "Caller",
                    client_phone=request.client_phone or "unknown",
                    turn_mode="live",
                )
                saved_preferences = DB.get_client_preferences(request.client_phone or "unknown")
                if saved_preferences:
                    state["property_preferences"] = {
                        key: saved_preferences[key]
                        for key in ("preferred_city", "preferred_area", "property_type")
                        if saved_preferences.get(key)
                    }
                    state["budget"] = saved_preferences.get("budget_pkr")
            agent_message_count_before = sum(1 for m in state["conversation_history"] if m["role"] == "agent")
            if request.text:
                state["utterance_queue"] = [request.text]

            result_state = COMPILED_GRAPH.invoke(state, config={"recursion_limit": 25})
            DB.save_session(request.call_id, result_state)

            profile = result_state["user_profile"]
            preferences = result_state.get("property_preferences") or {}
            transcript = " | ".join(
                message["content"] for message in result_state["conversation_history"]
            )
            DB.log_call_transcript(
                request.call_id,
                profile.get("client_name", "Caller"),
                profile.get("client_phone", "unknown"),
                transcript,
                result_state.get("intent"),
            )
            DB.upsert_client_preferences(
                profile.get("client_phone", "unknown"),
                profile.get("client_name", "Caller"),
                preferences.get("city"),
                preferences.get("area"),
                result_state.get("budget"),
                preferences.get("property_type"),
            )

            new_agent_messages = [
                m["content"] for m in result_state["conversation_history"]
                if m["role"] == "agent"
            ][agent_message_count_before:]

        except Exception as error:
            success = False
            DB.dead_letter(request.call_id, "agent_turn", str(error))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            MONITORING.record("agent_turn", request.call_id, latency_ms, False, {"error": str(error)})
            raise HTTPException(status_code=500, detail="Agent processing failed") from error

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    MONITORING.record("agent_turn", request.call_id, latency_ms, success, {"intent": result_state.get("intent")})

    return TurnResponse(
        call_id=request.call_id,
        responses=new_agent_messages,
        intent=result_state.get("intent"),
        appointment_status=result_state["appointment_status"],
        latency_ms=latency_ms,
    )


@app.post("/agent/reset/{call_id}")
def reset_call(call_id: str) -> dict[str, str]:
    DB.delete_session(call_id)
    SESSION_LOCKS.pop(call_id, None)
    return {"status": "reset", "call_id": call_id}


@app.post("/voice/turn", response_model=VoiceTurnResponse)
def voice_turn(request: VoiceTurnRequest) -> VoiceTurnResponse:
    try:
        audio = base64.b64decode(request.audio_base64, validate=True)
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Audio payload is empty or too large")
        transcribe = getattr(STT, "transcribe")
        transcript = transcribe(audio, request.mime_type)
        if not transcript.strip():
            raise SpeechProviderError("Speech provider returned an empty transcript")
        result = agent_turn(TurnRequest(
            call_id=request.call_id,
            text=transcript,
            client_name=request.client_name,
            client_phone=request.client_phone,
        ))
        response_text = " ".join(result.responses)
        synthesize = getattr(TTS, "synthesize")
        audio_output = synthesize(response_text)
    except (ValueError, TypeError, SpeechProviderError, AttributeError) as error:
        raise HTTPException(status_code=503, detail="Voice providers are unavailable") from error
    return VoiceTurnResponse(
        call_id=request.call_id,
        transcript=transcript,
        response=response_text,
        audio_base64=base64.b64encode(audio_output).decode("ascii"),
    )
