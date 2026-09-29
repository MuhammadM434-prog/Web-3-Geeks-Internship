"""Optional provider-backed intent classification with a deterministic local fallback."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_FALLBACK_PROVIDER,
    LLM_PROVIDER,
)

_ALLOWED_INTENTS = {
    "goodbye", "rescheduling", "cancellation", "booking", "rag_query",
    "objection", "recommendation_request", "unclear",
}


class LLMProviderError(RuntimeError):
    pass


class GeminiIntentClassifier:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def classify(self, utterance: str, state: dict[str, Any]) -> str | None:
        if not self.api_key:
            return None
        prompt = {
            "utterance": utterance,
            "current_intent": state.get("intent"),
            "has_appointment": bool(state.get("appointment_id")),
            "instruction": (
                "Classify this real-estate caller turn. Return only JSON with an intent field. "
                "Allowed values: goodbye, rescheduling, cancellation, booking, rag_query, "
                "objection, recommendation_request, unclear. Never execute tools."
            ),
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        response = httpx.post(
            url,
            json={"contents": [{"role": "user", "parts": [{"text": json.dumps(prompt)}]}]},
            timeout=8.0,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE).strip()
        intent = json.loads(text).get("intent")
        return intent if intent in _ALLOWED_INTENTS else None


class GroqIntentClassifier:
    """OpenAI-compatible Groq classifier used only when the primary fails."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def classify(self, utterance: str, state: dict[str, Any]) -> str | None:
        if not self.api_key:
            return None
        instruction = (
            "Classify this real-estate caller turn. Return only JSON with an intent field. "
            "Allowed values: goodbye, rescheduling, cancellation, booking, rag_query, "
            "objection, recommendation_request, unclear. Never execute tools."
        )
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": json.dumps({
                        "utterance": utterance,
                        "current_intent": state.get("intent"),
                        "has_appointment": bool(state.get("appointment_id")),
                    })},
                ],
            },
            timeout=5.0,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        intent = json.loads(text).get("intent")
        return intent if intent in _ALLOWED_INTENTS else None


class FallbackIntentClassifier:
    def __init__(self, primary: Any | None, fallback: Any | None) -> None:
        self.primary = primary
        self.fallback = fallback

    def classify(self, utterance: str, state: dict[str, Any]) -> str | None:
        if self.primary is not None:
            try:
                result = self.primary.classify(utterance, state)
                if result:
                    return result
            except Exception:
                pass
        if self.fallback is not None:
            try:
                return self.fallback.classify(utterance, state)
            except Exception:
                return None
        return None


def build_intent_classifier() -> FallbackIntentClassifier | None:
    primary = GeminiIntentClassifier(GEMINI_API_KEY, GEMINI_MODEL) if LLM_PROVIDER.casefold() == "gemini" else None
    if LLM_PROVIDER.casefold() == "groq":
        primary = GroqIntentClassifier(GROQ_API_KEY, GROQ_MODEL)
    fallback = (
        GroqIntentClassifier(GROQ_API_KEY, GROQ_MODEL)
        if primary is not None and LLM_FALLBACK_PROVIDER.casefold() == "groq"
        else None
    )
    if primary is None and fallback is None:
        return None
    return FallbackIntentClassifier(primary, fallback)
