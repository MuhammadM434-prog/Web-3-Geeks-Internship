"""VoiceAgentState: the single object every graph node reads and writes.

``conversation_history`` and ``execution_trace`` use ``operator.add`` reducers
so LangGraph appends to them on every node return; every other field is a
plain overwrite since only the latest value matters.
"""
from __future__ import annotations

import operator
from typing import Optional, TypedDict

from typing_extensions import Annotated


class Message(TypedDict):
    role: str  # "caller" | "agent"
    content: str


class ToolCallRecord(TypedDict):
    tool: str
    input: dict
    output: dict


class TraceEntry(TypedDict):
    node: str
    entered_intent: Optional[str]
    appointment_status: str
    note: str


class VoiceAgentState(TypedDict):
    call_id: str
    turn_mode: str  # "batch" (offline scripted test) | "live" (one HTTP turn)
    conversation_history: Annotated[list[Message], operator.add]
    execution_trace: Annotated[list[TraceEntry], operator.add]

    user_profile: dict            # client_name, client_phone
    property_preferences: dict    # city, area, property_type, bedrooms, purpose
    budget: Optional[int]

    intent: Optional[str]
    pending_clarification: Optional[str]

    matched_property_id: Optional[str]
    appointment_id: Optional[str]
    selected_slot: Optional[dict]
    appointment_status: str  # "none" | "booked" | "rescheduled" | "cancelled"
    last_action_result: Optional[str]  # reset every turn: "success" | "refused" | None

    tool_outputs: Annotated[list[ToolCallRecord], operator.add]

    # Stands in for the live STT stream so a single HTTP request can carry one
    # caller utterance at a time; each /agent/turn call pops the next queued
    # utterance for this call_id (see main.py's session store).
    utterance_queue: list[str]


def initial_state(call_id: str, client_name: str, client_phone: str,
                   turn_mode: str = "live") -> VoiceAgentState:
    return VoiceAgentState(
        call_id=call_id,
        turn_mode=turn_mode,
        conversation_history=[],
        execution_trace=[],
        user_profile={"client_name": client_name, "client_phone": client_phone},
        property_preferences={},
        budget=None,
        intent=None,
        pending_clarification=None,
        matched_property_id=None,
        appointment_id=None,
        selected_slot=None,
        appointment_status="none",
        last_action_result=None,
        tool_outputs=[],
        utterance_queue=[],
    )
