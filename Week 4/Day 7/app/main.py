"""
FastAPI service boundary.

The critical difference from the earlier Day 7 draft: ``/agent/turn`` invokes
``app.graph.COMPILED_GRAPH`` directly -- the real Day 5 LangGraph agent,
wired to real tools -- for every request. There is no ``if CompiledGraph is
not None`` fallback branch and no canned "request received" string; if the
graph raises, the endpoint returns a 500 and logs a dead-letter row instead
of pretending to succeed.

Conversation state is kept per ``call_id`` in ``SESSIONS`` so a multi-turn
phone call actually carries context (budget, matched property, appointment)
across separate HTTP requests -- the earlier draft re-built a blank state on
every single call, which meant no real conversation could ever complete.
``SESSIONS`` is an in-memory dict, which is the right amount of "real" for a
single-process local/demo deployment; the production swap point is Redis or
the same SQLite/Postgres database already used for everything else (persist
serialized state keyed by call_id), not a code restructure.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import APP_ENV
from app.graph import COMPILED_GRAPH
from app.monitoring import MonitoringService
from app.state import VoiceAgentState, initial_state
from app.tools import CALENDAR, DB, EMAIL, VECTOR_DB

MONITORING = MonitoringService(DB)
SESSIONS: dict[str, VoiceAgentState] = {}

app = FastAPI(title="Real Estate Voice Agent", version="1.0.0")


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
    try:
        state = SESSIONS.get(request.call_id)
        if state is None:
            state = initial_state(
                call_id=request.call_id,
                client_name=request.client_name or "Caller",
                client_phone=request.client_phone or "unknown",
                turn_mode="live",
            )
        agent_message_count_before = sum(1 for m in state["conversation_history"] if m["role"] == "agent")
        if request.text:
            state["utterance_queue"] = [request.text]

        result_state = COMPILED_GRAPH.invoke(state, config={"recursion_limit": 25})
        SESSIONS[request.call_id] = result_state

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
    SESSIONS.pop(call_id, None)
    return {"status": "reset", "call_id": call_id}
