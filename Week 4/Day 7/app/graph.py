"""
The actual LangGraph orchestration layer -- nine nodes, compiled with
``StateGraph``, that call the real tools in ``tools.py`` (SQLite calendar/
CRM, TF-IDF RAG, the filter+score recommendation engine). This is what
main.py's FastAPI service invokes directly; there is no "if compiled graph
is available" fallback branch that returns a canned string.

Two turn modes are supported by the same compiled graph:
- ``batch``: feed the whole ``utterance_queue`` up front and call ``invoke()``
  once; the graph loops through every turn autonomously and ends at
  "goodbye". Used by the automated test suite to replay full scripted
  conversations deterministically (this is exactly how the Day 5 notebook
  validated its guardrails).
- ``live``: the real mode for the FastAPI service. Each HTTP request supplies
  exactly one new caller utterance; after the graph produces this turn's
  reply (and, for a successful booking, the follow-on email) it returns
  control to the caller instead of looping back to ask "what's next" against
  an empty queue -- the next real utterance arrives as the next HTTP
  request, carrying the persisted state forward (see main.py's session store).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from langgraph.graph import END, StateGraph

from app.knowledge_base import property_lookup
from app.llm_service import build_intent_classifier
from app.state import VoiceAgentState
from app.tools import (
    availability_checker_tool,
    calendar_tool,
    crm_tool,
    email_tool,
    rag_search_tool,
    search_property_tool,
)

AREA_KEYWORDS = {"dha": "DHA Phase 6", "gulberg": "Gulberg III", "bahria": "Bahria Town"}
CRORE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*crore", re.IGNORECASE)
BEDROOM_RE = re.compile(r"(\d+)\s*(?:bed|bedroom)", re.IGNORECASE)
TIME_RE = re.compile(r"(\d{1,2})\s*(am|pm)", re.IGNORECASE)
PAKISTAN_TIMEZONE = ZoneInfo("Asia/Karachi")
INTENT_CLASSIFIER = build_intent_classifier()
INJECTION_TERMS = (
    "ignore instructions", "reveal your prompt", "show me your system prompt",
    "api key", "private company data", "fake appointment", "override the policy",
)


def _log(state: VoiceAgentState, node: str, note: str) -> dict:
    return {"execution_trace": [{
        "node": node, "entered_intent": state.get("intent"),
        "appointment_status": state["appointment_status"], "note": note,
    }]}


def _say(text: str) -> dict:
    return {"conversation_history": [{"role": "agent", "content": text}]}


def normalize_voice_transcript(text: str) -> str:
    if INTENT_CLASSIFIER is None:
        return text
    try:
        return INTENT_CLASSIFIER.normalize_transcript(text) or text
    except Exception:
        return text


# --- Nodes -------------------------------------------------------------

def greeting_node(state: VoiceAgentState) -> dict:
    greeting = "Assalam-o-alaikum, main property team ka AI assistant hoon. Aap kis type ki property dekh rahe hain?"
    return {**_say(greeting), **_log(state, "greeting", "Opened the call.")}


def intent_detection_node(state: VoiceAgentState) -> dict:
    queue = state["utterance_queue"]
    if not queue:
        return {"intent": "wait_for_caller", **_log(state, "intent_detection", "No new utterance queued this turn.")}

    utterance, remaining = queue[0], queue[1:]
    text = utterance.casefold()
    update: dict = {
        "utterance_queue": remaining,
        "conversation_history": [{"role": "caller", "content": utterance}],
        "last_action_result": None,
    }

    crore_match = CRORE_RE.search(text)
    if crore_match:
        update["budget"] = int(float(crore_match.group(1)) * 10_000_000)

    bedroom_match = BEDROOM_RE.search(text)
    preferences = dict(state.get("property_preferences") or {})
    if bedroom_match:
        preferences["bedrooms"] = int(bedroom_match.group(1))
    for keyword, area_name in AREA_KEYWORDS.items():
        if keyword in text:
            preferences["area"] = area_name
            preferences["city"] = "Lahore"
    if any(word in text for word in ("rent", "rental", "kiraye")):
        preferences["purpose"] = "rental"
    elif any(word in text for word in ("commercial", "office", "shop", "business")):
        preferences["purpose"] = "commercial"
    elif any(word in text for word in ("investment", "invest")):
        preferences["purpose"] = "investment"
    elif any(word in text for word in ("buy", "sale", "kharid")):
        preferences["purpose"] = "buyer"
    update["property_preferences"] = preferences

    if any(term in text for term in INJECTION_TERMS):
        intent = "rag_query"
    elif any(w in text for w in ("shukriya", "thanks", "thank you", "bye", "khuda hafiz")):
        intent = "goodbye"
    elif any(w in text for w in ("reschedule", "change kar", "move kar")):
        intent = "rescheduling"
    elif "cancel" in text:
        intent = "cancellation"
    elif any(w in text for w in ("book", "visit book", "confirm")) or TIME_RE.search(text):
        intent = "booking"
    elif any(w in text for w in ("guarantee", "return", "document", "cnic", "schedule kaise", "policy")):
        intent = "rag_query"
    elif any(w in text for w in ("expensive", "mehnga", "trust", "sure nahi", "not sure", "maintenance", "builder")):
        intent = "objection"
    elif any(w in text for w in ("option", "dikhao", "chahiye", "ghar", "property", "recommend")):
        intent = "recommendation_request"
    else:
        intent = "unclear"

    # Provider-backed classification is optional. The local classifier remains
    # the deterministic fallback for offline tests and missing credentials.
    if INTENT_CLASSIFIER is not None and not any(term in text for term in INJECTION_TERMS):
        try:
            provider_intent = INTENT_CLASSIFIER.classify(utterance, state)
            if provider_intent:
                intent = provider_intent
        except Exception:
            pass

    update["intent"] = intent
    return {**update, **_log(state, "intent_detection", f"Parsed intent={intent}")}


def rag_node(state: VoiceAgentState) -> dict:
    last_utterance = state["conversation_history"][-1]["content"] if state["conversation_history"] else ""
    result = rag_search_tool.invoke({"query": last_utterance})
    if result["evidence_id"] is None:
        reply = "Maazrat, is baare mein confirmed information nahi hai — main aik specialist se callback arrange kar deta hoon."
    else:
        reply = f"Ji, {result['evidence']}"
    return {
        **_say(reply),
        "tool_outputs": [{"tool": "rag_search", "input": {"query": last_utterance}, "output": result}],
        **_log(state, "rag", f"evidence_id={result['evidence_id']}"),
    }


def objection_node(state: VoiceAgentState) -> dict:
    text = state["conversation_history"][-1]["content"].casefold()
    if any(word in text for word in ("expensive", "mehnga")):
        reply = "Ji, budget important hai. Main aapko lower-budget verified options bhi dikha sakta hoon."
    elif any(word in text for word in ("trust", "sure nahi", "not sure")):
        reply = "Bilkul, pehle property details aur verified viewing process review kar lete hain; aap kis concern par focus karna chahenge?"
    else:
        reply = "Ji, aapka concern samajh raha hoon. Thora detail batayein taake main verified information ke saath help kar sakoon."
    return {**_say(reply), **_log(state, "objection", "Acknowledged caller concern.")}


def recommendation_node(state: VoiceAgentState) -> dict:
    prefs = state.get("property_preferences") or {}
    search_result = search_property_tool.invoke({
        "city": prefs.get("city"), "area": prefs.get("area"),
        "bedrooms": prefs.get("bedrooms"), "budget": state.get("budget"),
        "purpose": prefs.get("purpose", "buyer"),
    })
    matches = search_result["matches"]

    available_match = None
    for candidate in matches:
        availability = availability_checker_tool.invoke({"property_id": candidate["property_id"]})
        if availability["available"]:
            available_match = candidate
            break

    tool_outputs = [{"tool": "search_property", "input": prefs, "output": search_result}]
    if available_match is None:
        reply = "Maazrat, abhi in requirements par koi verified available option nahi hai. Budget ya area adjust karna chahenge?"
        matched_id = None
    else:
        reply = (
            f"Ji, {available_match['name']} ({available_match['area']}) available hai — "
            f"{available_match['bedrooms']} bedroom, PKR {available_match['price']:,}. Visit book karwana chahenge?"
        )
        matched_id = available_match["property_id"]

    return {
        **_say(reply),
        "matched_property_id": matched_id,
        "shortlisted_property_ids": [candidate["property_id"] for candidate in matches[:3]],
        "rejected_property_ids": [
            candidate["property_id"] for candidate in matches
            if candidate["property_id"] != matched_id
        ],
        "tool_outputs": tool_outputs,
        **_log(state, "recommendation", f"matched={matched_id}"),
    }


def _resolve_start_time(text: str) -> str | None:
    match = TIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        if match.group(2).lower() == "pm" and hour != 12:
            hour += 12
    elif "tomorrow" in text.casefold() or "kal" in text.casefold():
        hour = 15 if any(word in text.casefold() for word in ("afternoon", "dopahar")) else 10
    else:
        return None
    now = datetime.now(PAKISTAN_TIMEZONE)
    day = now + timedelta(days=1) if any(word in text.casefold() for word in ("tomorrow", "kal")) else now
    return day.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def booking_node(state: VoiceAgentState) -> dict:
    last_utterance = state["conversation_history"][-1]["content"] if state["conversation_history"] else ""
    property_id = state.get("matched_property_id")
    if property_id is None:
        return {
            **_say("Pehle property select karte hain, phir visit book karta hoon."),
            "last_action_result": "refused",
            **_log(state, "booking", "No matched property to book yet."),
        }

    start_time = _resolve_start_time(last_utterance)
    if start_time is None:
        return {
            **_say("Kis time visit book karna chahenge?"),
            "last_action_result": "refused",
            **_log(state, "booking", "No time parsed from caller utterance."),
        }

    profile = state["user_profile"]
    result = calendar_tool.invoke({
        "action": "book", "call_id": state["call_id"],
        "client_name": profile["client_name"], "client_phone": profile["client_phone"],
        "property_id": property_id, "start_time": start_time,
        "requirements": str(state.get("property_preferences", {})),
    })

    if result["status"] in ("success", "already_booked"):
        appointment = result["appointment"]
        return {
            **_say(f"Ji, aapki visit {appointment['start_time']} par confirm ho gayi hai."),
            "appointment_id": appointment["appointment_id"],
            "appointment_status": "booked",
            "last_action_result": "success",
            "tool_outputs": [{"tool": "calendar", "input": {"action": "book"}, "output": result}],
            **_log(state, "booking", f"Booked {appointment['appointment_id']}"),
        }

    alternatives = result.get("alternatives", [])
    alt_text = ", ".join(alt.strftime("%I%p").lstrip("0") for alt in alternatives) if alternatives else "kal"
    return {
        **_say(f"Maazrat, yeh slot already booked hai. {alt_text} mein se koi time theek rahega?"),
        "last_action_result": "refused",
        "tool_outputs": [{"tool": "calendar", "input": {"action": "book"}, "output": result}],
        **_log(state, "booking", f"Refused: {result.get('reason')}"),
    }


def rescheduling_node(state: VoiceAgentState) -> dict:
    last_utterance = state["conversation_history"][-1]["content"] if state["conversation_history"] else ""
    appointment_id = state.get("appointment_id")
    start_time = _resolve_start_time(last_utterance)
    if appointment_id is None or start_time is None:
        return {
            **_say("Konsi appointment reschedule karni hai, aur kis naye time par?"),
            "last_action_result": "refused",
            **_log(state, "rescheduling", "Missing appointment_id or new time."),
        }
    result = calendar_tool.invoke({"action": "reschedule", "call_id": state["call_id"],
                                    "client_name": state["user_profile"]["client_name"],
                                    "client_phone": state["user_profile"]["client_phone"],
                                    "appointment_id": appointment_id, "start_time": start_time})
    if result["status"] == "success":
        appointment = result["appointment"]
        return {
            **_say(f"Ji, visit ab {appointment['start_time']} par reschedule ho gayi hai."),
            "appointment_status": "rescheduled", "last_action_result": "success",
            "tool_outputs": [{"tool": "calendar", "input": {"action": "reschedule"}, "output": result}],
            **_log(state, "rescheduling", "Rescheduled successfully"),
        }
    return {
        **_say("Maazrat, woh naya slot bhi unavailable hai. Koi aur time bataiye."),
        "last_action_result": "refused",
        "tool_outputs": [{"tool": "calendar", "input": {"action": "reschedule"}, "output": result}],
        **_log(state, "rescheduling", f"Refused: {result.get('reason')}"),
    }


def cancellation_node(state: VoiceAgentState) -> dict:
    appointment_id = state.get("appointment_id")
    if appointment_id is None:
        return {
            **_say("Aapki koi active booking mujhe nahi mil rahi."),
            "last_action_result": "refused",
            **_log(state, "cancellation", "No appointment_id in state."),
        }
    result = calendar_tool.invoke({"action": "cancel", "call_id": state["call_id"],
                                    "client_name": state["user_profile"]["client_name"],
                                    "client_phone": state["user_profile"]["client_phone"],
                                    "appointment_id": appointment_id})
    if result["status"] == "success":
        return {
            **_say("Ji, aapki visit cancel kar di gayi hai."),
            "appointment_status": "cancelled", "last_action_result": "success",
            "tool_outputs": [{"tool": "calendar", "input": {"action": "cancel"}, "output": result}],
            **_log(state, "cancellation", "Cancelled successfully"),
        }
    return {
        **_say("Maazrat, yeh cancel nahi ho saki."),
        "last_action_result": "refused",
        "tool_outputs": [{"tool": "calendar", "input": {"action": "cancel"}, "output": result}],
        **_log(state, "cancellation", f"Refused: {result.get('reason')}"),
    }


def email_node(state: VoiceAgentState) -> dict:
    appointment_id = state.get("appointment_id")
    from app.tools import DB
    appointment = DB.get_appointment(appointment_id) if appointment_id else None
    if appointment is None:
        return {**_log(state, "email", "No appointment to notify about.")}
    result = email_tool.invoke({"appointment": appointment})
    crm_tool.invoke({
        "action": "log_call", "call_id": state["call_id"],
        "client_name": state["user_profile"]["client_name"],
        "client_phone": state["user_profile"]["client_phone"],
        "transcript": " | ".join(m["content"] for m in state["conversation_history"]),
        "intent": state.get("intent"),
    })
    crm_tool.invoke({
        "action": "update_preferences", "call_id": state["call_id"],
        "client_name": state["user_profile"]["client_name"],
        "client_phone": state["user_profile"]["client_phone"],
        "preferred_city": (state.get("property_preferences") or {}).get("city"),
        "preferred_area": (state.get("property_preferences") or {}).get("area"),
        "budget": state.get("budget"),
    })
    return {
        "tool_outputs": [{"tool": "email", "input": {"appointment_id": appointment_id}, "output": result}],
        **_log(state, "email", f"Notification {result['status']}"),
    }


def goodbye_node(state: VoiceAgentState) -> dict:
    return {**_say("Shukriya, Allah Hafiz!"), **_log(state, "goodbye", "Call ended.")}


def clarification_node(state: VoiceAgentState) -> dict:
    return {
        **_say("Maazrat, main aapki baat samajh nahi saka. Kya aap apni baat dobara keh sakte hain?"),
        **_log(state, "clarification", "Asked caller to repeat an unclear turn."),
    }


def wait_node(state: VoiceAgentState) -> dict:
    """Live-mode terminal node: nothing new to process this turn."""
    return {**_log(state, "wait_for_caller", "Awaiting next caller utterance.")}


# --- Routing -------------------------------------------------------------

def route_entry(state: VoiceAgentState) -> str:
    """First-ever turn (no conversation history yet) opens with a greeting;
    every later turn -- including every live HTTP turn after the first --
    goes straight to intent parsing instead of re-greeting the caller."""
    return "greeting" if not state["conversation_history"] else "intent_detection"


def route_after_intent(state: VoiceAgentState) -> str:
    return {
        "goodbye": "goodbye",
        "rag_query": "rag",
        "objection": "objection",
        "recommendation_request": "recommendation",
        "booking": "booking",
        "rescheduling": "rescheduling",
        "cancellation": "cancellation",
        "wait_for_caller": "wait",
        "unclear": "clarification",
    }.get(state["intent"], "wait")


def route_after_info(state: VoiceAgentState) -> str:
    return "intent_detection" if state["turn_mode"] == "batch" else END


def route_after_action(state: VoiceAgentState) -> str:
    if state["last_action_result"] == "success":
        return "email"
    return "intent_detection" if state["turn_mode"] == "batch" else END


def route_after_email(state: VoiceAgentState) -> str:
    return "intent_detection" if state["turn_mode"] == "batch" else END


def build_graph():
    graph = StateGraph(VoiceAgentState)
    graph.add_node("greeting", greeting_node)
    graph.add_node("intent_detection", intent_detection_node)
    graph.add_node("rag", rag_node)
    graph.add_node("objection", objection_node)
    graph.add_node("recommendation", recommendation_node)
    graph.add_node("booking", booking_node)
    graph.add_node("rescheduling", rescheduling_node)
    graph.add_node("cancellation", cancellation_node)
    graph.add_node("email", email_node)
    graph.add_node("goodbye", goodbye_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("wait", wait_node)

    graph.set_conditional_entry_point(route_entry, {
        "greeting": "greeting", "intent_detection": "intent_detection",
    })
    graph.add_edge("greeting", "intent_detection")
    graph.add_conditional_edges("intent_detection", route_after_intent, {
        "goodbye": "goodbye", "rag": "rag", "objection": "objection", "recommendation": "recommendation",
        "booking": "booking", "rescheduling": "rescheduling", "cancellation": "cancellation",
        "intent_detection": "intent_detection", "clarification": "clarification", "wait": "wait",
    })
    graph.add_conditional_edges("rag", route_after_info, {"intent_detection": "intent_detection", END: END})
    graph.add_conditional_edges("objection", route_after_info, {"intent_detection": "intent_detection", END: END})
    graph.add_conditional_edges("recommendation", route_after_info, {"intent_detection": "intent_detection", END: END})
    graph.add_conditional_edges("booking", route_after_action, {"email": "email", "intent_detection": "intent_detection", END: END})
    graph.add_conditional_edges("rescheduling", route_after_action, {"email": "email", "intent_detection": "intent_detection", END: END})
    graph.add_conditional_edges("cancellation", route_after_action, {"email": "email", "intent_detection": "intent_detection", END: END})
    graph.add_conditional_edges("email", route_after_email, {"intent_detection": "intent_detection", END: END})
    graph.add_edge("goodbye", END)
    graph.add_conditional_edges("clarification", route_after_info, {"intent_detection": "intent_detection", END: END})
    graph.add_edge("wait", END)
    return graph.compile()


COMPILED_GRAPH = build_graph()
