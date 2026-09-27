"""Email adapter -- the swap point for a real Gmail API ``users.messages.send``
or Resend ``emails.send`` call. What's real here: idempotent sends persisted
to the database (a retried notification for the same appointment/action is a
true no-op, never a duplicate inbox email), and the notification body is
always generated fresh from the current appointment record, so it can never
drift from what's actually on the calendar."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.database import DatabaseAdapter
from app.knowledge_base import EMPLOYEES, property_lookup


def render_notification(appointment: dict[str, Any]) -> tuple[str, str]:
    prop = property_lookup(appointment["property_id"])
    property_name = prop["name"] if prop else appointment["property_id"]
    subject = f"Visit {appointment['status']}: {property_name} — {appointment['start_time']}"
    body = (
        f"A property visit has been {appointment['status']} on your calendar.\n\n"
        f"Property: {property_name} ({appointment['property_id']})\n"
        f"Date/Time: {appointment['start_time']} - {appointment['end_time']}\n"
        f"Client: {appointment['client_name']}\n"
        f"Client phone: {appointment['client_phone']}\n"
        f"Client requirements: {appointment.get('requirements', '')}\n"
        f"Calendar event: {appointment['calendar_event_id']}"
    )
    return subject, body


class EmailService:
    def __init__(self, db: DatabaseAdapter):
        self.db = db

    def health(self) -> bool:
        return self.db.health()

    def notify_employee(self, appointment: dict[str, Any]) -> dict[str, Any]:
        employee = EMPLOYEES.get(appointment["employee_id"])
        if employee is None:
            return {"status": "refused", "reason": "unknown_employee"}

        idempotency_key = f"{appointment['appointment_id']}:{appointment['status']}"
        existing = self.db.find_email_by_idempotency_key(idempotency_key)
        if existing:
            return {"status": "already_sent", "message": existing}

        subject, body = render_notification(appointment)
        message = {
            "message_id": f"MSG-{uuid.uuid4().hex[:10]}",
            "idempotency_key": idempotency_key,
            "to_address": employee["email"],
            "subject": subject,
            "body": body,
            "related_appointment_id": appointment["appointment_id"],
        }
        saved = self.db.save_email(message)
        if not saved:
            existing = self.db.find_email_by_idempotency_key(idempotency_key)
            return {"status": "already_sent", "message": existing}
        return {"status": "success", "message": message}
