"""Email adapter -- the swap point for a real Gmail API ``users.messages.send``
or Resend ``emails.send`` call. What's real here: idempotent sends persisted
to the database (a retried notification for the same appointment/action is a
true no-op, never a duplicate inbox email), and the notification body is
always generated fresh from the current appointment record, so it can never
drift from what's actually on the calendar."""
from __future__ import annotations

import uuid
import base64
import json
from datetime import datetime, timezone
from typing import Any

from app.database import DatabaseAdapter
from app.config import (
    EMAIL_PROVIDER,
    GMAIL_CREDENTIALS_JSON,
    GMAIL_OAUTH_CLIENT_SECRETS_JSON,
    GMAIL_SENDER,
)
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
        self._gmail = None
        if EMAIL_PROVIDER.casefold() == "gmail":
            self._gmail = self._build_gmail_client()

    @staticmethod
    def _build_gmail_client() -> Any:
        if GMAIL_OAUTH_CLIENT_SECRETS_JSON:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                from googleapiclient.discovery import build
            except ImportError as error:
                raise RuntimeError("Install Gmail OAuth dependencies for EMAIL_PROVIDER=gmail") from error
            flow = InstalledAppFlow.from_client_config(
                json.loads(GMAIL_OAUTH_CLIENT_SECRETS_JSON),
                ["https://www.googleapis.com/auth/gmail.send"],
            )
            credentials = flow.run_local_server(
                host="localhost",
                port=8765,
                access_type="offline",
                prompt="consent",
                open_browser=True,
            )
            return build("gmail", "v1", credentials=credentials, cache_discovery=False)
        if not GMAIL_CREDENTIALS_JSON:
            raise RuntimeError(
                "GMAIL_OAUTH_CLIENT_SECRETS_JSON or GMAIL_CREDENTIALS_JSON is required "
                "for EMAIL_PROVIDER=gmail"
            )
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as error:
            raise RuntimeError("Install Gmail dependencies for EMAIL_PROVIDER=gmail") from error
        credentials = Credentials.from_service_account_info(
            json.loads(GMAIL_CREDENTIALS_JSON),
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def health(self) -> bool:
        """Check storage and provider configuration without Gmail read access."""
        if not self.db.health():
            return False
        return EMAIL_PROVIDER.casefold() != "gmail" or self._gmail is not None

    def _send_gmail(self, to_address: str, subject: str, body: str) -> str:
        raw = (
            f"To: {to_address}\r\n"
            f"Subject: {subject}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            f"{body}"
        )
        result = self._gmail.users().messages().send(
            userId=GMAIL_SENDER,
            body={"raw": base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")},
        ).execute()
        return result["id"]

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
        if self._gmail is not None:
            message["message_id"] = self._send_gmail(
                message["to_address"], message["subject"], message["body"]
            )
        saved = self.db.save_email(message)
        if not saved:
            existing = self.db.find_email_by_idempotency_key(idempotency_key)
            return {"status": "already_sent", "message": existing}
        return {"status": "success", "message": message}
