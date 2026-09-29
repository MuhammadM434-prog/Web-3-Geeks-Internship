"""Optional provider-backed intent classification with a deterministic local fallback."""
from __future__ import annotations

import json
import logging
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
_LOGGER = logging.getLogger(__name__)
_NON_ROMAN_SCRIPT = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\u0900-\u097f]")


def _needs_romanization(text: str) -> bool:
    return bool(_NON_ROMAN_SCRIPT.search(text))


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

    def normalize_transcript(self, utterance: str) -> str | None:
        if not self.api_key or not _needs_romanization(utterance):
            return utterance
        prompt = {
            "transcript": utterance,
            "instruction": (
                "Transliterate this caller's Urdu/Hindustani speech into Roman Urdu. "
                "Do not translate or answer it. Preserve English words, names, numbers, "
                "and the original meaning. Return only the transliterated sentence."
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
        normalized = re.sub(r"^```(?:text)?|```$", "", text.strip(), flags=re.IGNORECASE).strip().strip('"')
        return normalized or None


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

    def normalize_transcript(self, utterance: str) -> str | None:
        if not self.api_key or not _needs_romanization(utterance):
            return utterance
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "max_tokens": 160,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Transliterate Urdu/Hindustani speech into Roman Urdu. "
                            "Do not translate or answer. Preserve English words, names, "
                            "numbers, and meaning. Return only the transliterated text."
                        ),
                    },
                    {"role": "user", "content": utterance},
                ],
            },
            timeout=5.0,
        )
        response.raise_for_status()
        normalized = response.json()["choices"][0]["message"]["content"].strip().strip('"')
        return normalized or None


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

    def normalize_transcript(self, utterance: str) -> str:
        if not _needs_romanization(utterance):
            return utterance
        for provider in (self.primary, self.fallback):
            normalize = getattr(provider, "normalize_transcript", None)
            if normalize is None:
                continue
            try:
                normalized = normalize(utterance)
                if normalized:
                    if _needs_romanization(normalized):
                        _LOGGER.warning(
                            "Transcript normalization returned non-Roman text from %s",
                            type(provider).__name__,
                        )
                        continue
                    return normalized
            except Exception as error:
                response = getattr(error, "response", None)
                _LOGGER.warning(
                    "Transcript normalization failed for %s (%s, status=%s)",
                    type(provider).__name__,
                    type(error).__name__,
                    getattr(response, "status_code", None),
                )
                continue
        return utterance


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
        _LOGGER.warning(
            "No LLM provider configured; non-Roman voice transcripts cannot be normalized"
        )
        return None
    return FallbackIntentClassifier(primary, fallback)
