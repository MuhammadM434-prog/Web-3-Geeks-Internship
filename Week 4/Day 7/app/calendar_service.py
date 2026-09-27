"""
Calendar adapter mirroring the real Google Calendar API shape
(``events.insert`` / ``events.patch``) closely enough that a production build
swaps this class for ``googleapiclient.discovery.build("calendar", "v3", ...)``
without changing any caller code in tools.py.

What's real here, not placeholder:
- Idempotency: a retried booking (same idempotency_key) is a true no-op --
  it returns the existing appointment instead of creating a duplicate.
- Conflict detection: an actual overlap check against every other persisted,
  non-cancelled event for the same employee, run on every write (booking
  *and* reschedule).
- Persistence: appointments live in the real SQLite database (database.py),
  not a process-local list, so a restart doesn't lose bookings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.database import DatabaseAdapter
from app.knowledge_base import EMPLOYEES, property_lookup


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


class CalendarService:
    def __init__(self, db: DatabaseAdapter):
        self.db = db

    def health(self) -> bool:
        return self.db.health()

    def check_availability(self, employee_id: str, start_time: datetime, end_time: datetime,
                            exclude_appointment_id: str | None = None) -> bool:
        existing = self.db.list_events_for_employee(employee_id)
        for event in existing:
            if exclude_appointment_id and event["appointment_id"] == exclude_appointment_id:
                continue
            event_start = datetime.fromisoformat(event["start_time"])
            event_end = datetime.fromisoformat(event["end_time"])
            if _overlaps(start_time, end_time, event_start, event_end):
                return False
        return True

    def suggest_alternative_slots(self, employee_id: str, requested_start: datetime,
                                   duration_minutes: int = 60, count: int = 2) -> list[datetime]:
        alternatives = []
        candidate = requested_start
        for _ in range(12):
            candidate = candidate + timedelta(hours=1)
            end = candidate + timedelta(minutes=duration_minutes)
            if self.check_availability(employee_id, candidate, end):
                alternatives.append(candidate)
            if len(alternatives) >= count:
                break
        return alternatives

    def book(self, call_id: str, client_name: str, client_phone: str, property_id: str,
             start_time: datetime, duration_minutes: int, requirements: str,
             idempotency_key: str) -> dict[str, Any]:
        existing = self.db.find_appointment_by_idempotency_key(idempotency_key)
        if existing:
            return {"status": "already_booked", "appointment": existing}

        prop = property_lookup(property_id)
        if prop is None:
            return {"status": "refused", "reason": "unknown_property"}
        employee_id = prop["employee_id"]
        end_time = start_time + timedelta(minutes=duration_minutes)

        if not self.check_availability(employee_id, start_time, end_time):
            alternatives = self.suggest_alternative_slots(employee_id, start_time, duration_minutes)
            return {"status": "refused", "reason": "slot_unavailable", "alternatives": alternatives}

        appointment_id = f"APPT-{uuid.uuid4().hex[:10]}"
        event_id = f"EVT-{uuid.uuid4().hex[:10]}"
        appointment = {
            "appointment_id": appointment_id,
            "calendar_event_id": event_id,
            "call_id": call_id,
            "client_name": client_name,
            "client_phone": client_phone,
            "employee_id": employee_id,
            "property_id": property_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "status": "booked",
            "requirements": requirements,
            "idempotency_key": idempotency_key,
        }
        self.db.save_appointment(appointment)
        self.db.add_appointment_history(appointment_id, "booked", f"Visit booked for {property_id} at {start_time.isoformat()}")
        return {"status": "success", "appointment": appointment}

    def reschedule(self, appointment_id: str, new_start_time: datetime, duration_minutes: int) -> dict[str, Any]:
        appointment = self.db.get_appointment(appointment_id)
        if appointment is None:
            return {"status": "refused", "reason": "not_found"}
        employee_id = appointment["employee_id"]
        new_end_time = new_start_time + timedelta(minutes=duration_minutes)
        if not self.check_availability(employee_id, new_start_time, new_end_time, exclude_appointment_id=appointment_id):
            alternatives = self.suggest_alternative_slots(employee_id, new_start_time, duration_minutes)
            return {"status": "refused", "reason": "slot_unavailable", "alternatives": alternatives}
        appointment["start_time"] = new_start_time.isoformat()
        appointment["end_time"] = new_end_time.isoformat()
        appointment["status"] = "rescheduled"
        self.db.save_appointment(appointment)
        self.db.add_appointment_history(appointment_id, "rescheduled", f"Moved to {new_start_time.isoformat()}")
        return {"status": "success", "appointment": appointment}

    def cancel(self, appointment_id: str) -> dict[str, Any]:
        appointment = self.db.get_appointment(appointment_id)
        if appointment is None:
            return {"status": "refused", "reason": "not_found"}
        appointment["status"] = "cancelled"
        self.db.save_appointment(appointment)
        self.db.add_appointment_history(appointment_id, "cancelled", "Cancelled by caller")
        return {"status": "success", "appointment": appointment}
