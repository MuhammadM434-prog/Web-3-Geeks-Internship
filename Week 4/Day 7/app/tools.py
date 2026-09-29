"""
Six tools, wrapped with LangChain's ``@tool`` decorator so they carry a schema
and can be bound to an LLM's native tool-calling. They call the configured
relational database for calendar/email/CRM, the TF-IDF RAG adapter, and the
filter+score recommendation engine; no fallback returns a canned success.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import tool

from app.calendar_service import CalendarService
from app.database import DatabaseAdapter
from app.email_service import EmailService
from app.knowledge_base import VectorDatabaseAdapter
from app.recommendation import RecommendationRequest, recommend

# Module-level singletons: one real SQLite connection pool / TF-IDF index per
# process, shared by every tool call and by main.py's health checks.
DB = DatabaseAdapter()
CALENDAR = CalendarService(DB)
EMAIL = EmailService(DB)
VECTOR_DB = VectorDatabaseAdapter()


@tool
def search_property_tool(city: str | None, area: str | None, bedrooms: int | None,
                          budget: int | None, purpose: str = "buyer") -> dict[str, Any]:
    """Search the property catalog by city, area, bedroom count, budget and purpose.
    May return properties that are not currently available -- pair with
    availability_checker_tool before recommending one to a caller."""
    request = RecommendationRequest(budget=budget, city=city, area=area, bedrooms=bedrooms, purpose=purpose)
    matches = recommend(request, only_available=False)
    return {"matches": matches}


@tool
def availability_checker_tool(property_id: str) -> dict[str, Any]:
    """Authoritative live-availability check for one property_id."""
    from app.knowledge_base import property_lookup
    prop = property_lookup(property_id)
    if prop is None:
        return {"available": False, "reason": "unknown_property"}
    return {"available": prop["status"] == "available", "status": prop["status"]}


@tool
def rag_search_tool(query: str) -> dict[str, Any]:
    """Search company knowledge (brochures/FAQs) for a grounded answer.
    Returns evidence_id=None when nothing is grounded, so the caller must abstain
    rather than invent an answer."""
    results = VECTOR_DB.search(query)
    if not results:
        return {"evidence_id": None, "evidence": None, "score": 0.0}
    top = results[0]
    return {"evidence_id": top.source_id, "evidence": top.evidence, "score": top.score}


@tool
def calendar_tool(action: str, call_id: str, client_name: str, client_phone: str,
                   property_id: str | None = None, start_time: str | None = None,
                   duration_minutes: int = 60, requirements: str = "",
                   appointment_id: str | None = None) -> dict[str, Any]:
    """Book, reschedule, or cancel a property visit. ``action`` is one of
    "book", "reschedule", "cancel". Times are ISO-8601 strings."""
    if action == "book":
        idempotency_key = f"{call_id}:{property_id}:{start_time}"
        return CALENDAR.book(
            call_id=call_id, client_name=client_name, client_phone=client_phone,
            property_id=property_id, start_time=datetime.fromisoformat(start_time),
            duration_minutes=duration_minutes, requirements=requirements,
            idempotency_key=idempotency_key,
        )
    if action == "reschedule":
        return CALENDAR.reschedule(appointment_id, datetime.fromisoformat(start_time), duration_minutes)
    if action == "cancel":
        return CALENDAR.cancel(appointment_id)
    return {"status": "refused", "reason": "unknown_action"}


@tool
def email_tool(appointment: dict[str, Any]) -> dict[str, Any]:
    """Notify the assigned employee about a booked/rescheduled/cancelled appointment."""
    return EMAIL.notify_employee(appointment)


@tool
def crm_tool(action: str, call_id: str, client_name: str = "", client_phone: str = "",
             transcript: str = "", intent: str | None = None,
             preferred_city: str | None = None, preferred_area: str | None = None,
             budget: int | None = None, property_type: str | None = None) -> dict[str, Any]:
    """Log a call transcript and/or update the client's accumulated preference
    profile. ``action`` is "log_call" or "update_preferences"."""
    if action == "log_call":
        DB.log_call_transcript(call_id, client_name, client_phone, transcript, intent)
        return {"status": "logged"}
    if action == "update_preferences":
        DB.upsert_client_preferences(client_phone, client_name, preferred_city,
                                      preferred_area, budget, property_type)
        return {"status": "updated"}
    return {"status": "refused", "reason": "unknown_action"}
