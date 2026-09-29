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
- Persistence: appointments live in the configured relational database,
  not a process-local list, so a restart doesn't lose bookings.
"""
from __future__ import annotations

import uuid
import json
from datetime import datetime, timedelta
from typing import Any

from app.database import DatabaseAdapter
from app.config import (
    CALENDAR_PROVIDER,
    GOOGLE_CALENDAR_CREDENTIALS_JSON,
    GOOGLE_CALENDAR_ID,
)
from app.knowledge_base import EMPLOYEES, property_lookup


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class CalendarService:
    def __init__(self, db: DatabaseAdapter):
        self.db = db
        self._google = None
        if CALENDAR_PROVIDER.casefold() == "google":
            self._google = self._build_google_client()

    @staticmethod
    def _build_google_client() -> Any:
        if not GOOGLE_CALENDAR_CREDENTIALS_JSON:
            raise RuntimeError("GOOGLE_CALENDAR_CREDENTIALS_JSON is required for CALENDAR_PROVIDER=google")
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as error:
            raise RuntimeError("Install Google Calendar dependencies for CALENDAR_PROVIDER=google") from error
        credentials_data = json.loads(GOOGLE_CALENDAR_CREDENTIALS_JSON)
        credentials = Credentials.from_service_account_info(
            credentials_data,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def health(self) -> bool:
        if not self.db.health():
            return False
        if self._google is None:
            return True
        try:
            self._google.calendars().get(calendarId=GOOGLE_CALENDAR_ID).execute()
            return True
        except Exception:
            return False

    def _google_event(self, appointment: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": f"Property visit: {appointment['property_id']}",
            "description": (
                f"Client: {appointment['client_name']}\n"
                f"Phone: {appointment['client_phone']}\n"
                f"Requirements: {appointment.get('requirements', '')}"
            ),
            "start": {"dateTime": appointment["start_time"], "timeZone": "Asia/Karachi"},
            "end": {"dateTime": appointment["end_time"], "timeZone": "Asia/Karachi"},
            "extendedProperties": {"private": {"realestate_appointment_id": appointment["appointment_id"]}},
        }

    def check_availability(self, employee_id: str, start_time: datetime, end_time: datetime,
                            exclude_appointment_id: str | None = None) -> bool:
        existing = self.db.list_events_for_employee(employee_id)
        for event in existing:
            if exclude_appointment_id and event["appointment_id"] == exclude_appointment_id:
                continue
            event_start = _parse_datetime(event["start_time"])
            event_end = _parse_datetime(event["end_time"])
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
            if existing["status"] != "cancelled":
                return {"status": "already_booked", "appointment": existing}
            idempotency_key = f"{idempotency_key}:rebook:{uuid.uuid4().hex[:8]}"

        prop = property_lookup(property_id)
        if prop is None:
            return {"status": "refused", "reason": "unknown_property"}
        employee_id = prop["employee_id"]
        end_time = start_time + timedelta(minutes=duration_minutes)

        alternatives = self.suggest_alternative_slots(employee_id, start_time, duration_minutes)

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
        if not self.db.book_appointment_if_available(appointment):
            alternatives = self.suggest_alternative_slots(employee_id, start_time, duration_minutes)
            return {"status": "refused", "reason": "slot_unavailable", "alternatives": alternatives}

        if self._google is not None:
            created_event_id = None
            try:
                freebusy = self._google.freebusy().query(body={
                    "timeMin": start_time.isoformat(),
                    "timeMax": end_time.isoformat(),
                    "items": [{"id": GOOGLE_CALENDAR_ID}],
                }).execute()
                busy = freebusy.get("calendars", {}).get(GOOGLE_CALENDAR_ID, {}).get("busy", [])
                if busy:
                    self.db.abort_unconfirmed_appointment(appointment_id)
                    alternatives = self.suggest_alternative_slots(employee_id, start_time, duration_minutes)
                    return {"status": "refused", "reason": "slot_unavailable", "alternatives": alternatives}
                event = self._google.events().insert(
                    calendarId=GOOGLE_CALENDAR_ID,
                    body=self._google_event(appointment),
                    sendUpdates="all",
                ).execute()
                created_event_id = event["id"]
                appointment["calendar_event_id"] = event["id"]
                self.db.save_appointment(appointment)
            except Exception:
                if created_event_id:
                    try:
                        self._google.events().delete(
                            calendarId=GOOGLE_CALENDAR_ID,
                            eventId=created_event_id,
                            sendUpdates="all",
                        ).execute()
                    except Exception:
                        self.db.dead_letter(
                            call_id,
                            "calendar_compensation",
                            "Calendar event may remain after local persistence failed",
                        )
                self.db.abort_unconfirmed_appointment(appointment_id)
                raise
        return {"status": "success", "appointment": appointment}

    def reschedule(self, appointment_id: str, new_start_time: datetime, duration_minutes: int) -> dict[str, Any]:
        original = self.db.get_appointment(appointment_id)
        if original is None:
            return {"status": "refused", "reason": "not_found"}
        if original["status"] == "cancelled":
            return {"status": "refused", "reason": "cancelled_appointment"}
        new_end_time = new_start_time + timedelta(minutes=duration_minutes)
        outcome, appointment = self.db.reschedule_appointment_if_available(
            appointment_id, new_start_time, new_end_time
        )
        if outcome == "not_found":
            return {"status": "refused", "reason": "not_found"}
        if outcome == "cancelled_appointment":
            return {"status": "refused", "reason": "cancelled_appointment"}
        if outcome == "slot_unavailable":
            alternatives = self.suggest_alternative_slots(
                original["employee_id"], new_start_time, duration_minutes
            )
            return {"status": "refused", "reason": "slot_unavailable", "alternatives": alternatives}
        if self._google is not None:
            try:
                self._google.events().patch(
                    calendarId=GOOGLE_CALENDAR_ID,
                    eventId=appointment["calendar_event_id"],
                    body=self._google_event(appointment),
                    sendUpdates="all",
                ).execute()
            except Exception:
                try:
                    self._google.events().patch(
                        calendarId=GOOGLE_CALENDAR_ID,
                        eventId=original["calendar_event_id"],
                        body=self._google_event(original),
                        sendUpdates="all",
                    ).execute()
                except Exception:
                    self.db.dead_letter(
                        original.get("call_id"),
                        "calendar_reschedule_compensation",
                        "Calendar event may differ from restored database appointment",
                    )
                self.db.save_appointment(original)
                self.db.add_appointment_history(appointment_id, "reschedule_rolled_back", "Calendar update failed; prior state restored")
                raise
        return {"status": "success", "appointment": appointment}

    def cancel(self, appointment_id: str) -> dict[str, Any]:
        appointment = self.db.get_appointment(appointment_id)
        if appointment is None:
            return {"status": "refused", "reason": "not_found"}
        if appointment["status"] == "cancelled":
            return {"status": "already_cancelled", "appointment": appointment}
        appointment["status"] = "cancelled"
        if self._google is not None:
            self._google.events().delete(
                calendarId=GOOGLE_CALENDAR_ID,
                eventId=appointment["calendar_event_id"],
                sendUpdates="all",
            ).execute()
        self.db.save_appointment(appointment)
        self.db.add_appointment_history(appointment_id, "cancelled", "Cancelled by caller")
        return {"status": "success", "appointment": appointment}
