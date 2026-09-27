"""Monitoring: every turn's latency/success is persisted (not just printed)
and can be rolled up into alerts, the same thresholds Day 6's evaluation
notebook defined."""
from __future__ import annotations

import logging
from typing import Any

from app.database import DatabaseAdapter

Logger = logging.getLogger("RealEstateAgent")

ALERT_THRESHOLDS = {
    "p95_latency_ms": 2000,
    "minimum_success_rate": 0.90,
}


class MonitoringService:
    def __init__(self, db: DatabaseAdapter):
        self.db = db

    def record(self, event: str, call_id: str | None, latency_ms: float,
               success: bool, detail: dict[str, Any] | None = None) -> None:
        self.db.record_event(event, call_id, latency_ms, success, detail)
        Logger.info({"event": event, "call_id": call_id, "latency_ms": latency_ms, "success": success})

    def summary(self) -> dict[str, Any]:
        return self.db.monitoring_summary()

    def alerts(self) -> list[str]:
        summary = self.summary()
        if summary.get("events", 0) == 0:
            return []
        triggered = []
        if summary.get("max_latency_ms", 0) > ALERT_THRESHOLDS["p95_latency_ms"]:
            triggered.append("HIGH_LATENCY")
        if summary.get("success_rate", 1.0) < ALERT_THRESHOLDS["minimum_success_rate"]:
            triggered.append("LOW_SUCCESS_RATE")
        return triggered
