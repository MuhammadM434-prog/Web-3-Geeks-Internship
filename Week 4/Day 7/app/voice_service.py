"""Provider-backed speech adapters for the text-first agent workflow."""
from __future__ import annotations

from typing import Protocol

import httpx

from app.config import (
    DEEPGRAM_API_KEY,
    DEEPGRAM_MODEL,
    FISH_AUDIO_API_KEY,
    FISH_AUDIO_MODEL,
    FISH_AUDIO_REFERENCE_ID,
    STT_PROVIDER,
    TTS_PROVIDER,
)


class SpeechProvider(Protocol):
    def health(self) -> bool: ...


class SpeechProviderError(RuntimeError):
    pass


class LocalSpeechProvider:
    def __init__(self, name: str):
        self.name = name

    def health(self) -> bool:
        return False


class DeepgramSTT:
    def __init__(self, api_key: str, model: str = "nova-3"):
        self.api_key = api_key
        self.model = model

    def health(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        if not self.api_key:
            raise SpeechProviderError("Deepgram API key is not configured")
        try:
            response = httpx.post(
                "https://api.deepgram.com/v1/listen",
                params={"model": self.model, "smart_format": "true", "language": "multi"},
                headers={"Authorization": f"Token {self.api_key}", "Content-Type": mime_type},
                content=audio,
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise SpeechProviderError("Deepgram could not transcribe the audio") from error


class FishAudioTTS:
    def __init__(self, api_key: str, model: str = "s1", reference_id: str = ""):
        self.api_key = api_key
        self.model = model
        self.reference_id = reference_id

    def health(self) -> bool:
        return bool(self.api_key)

    def synthesize(self, text: str) -> bytes:
        if not self.api_key:
            raise SpeechProviderError("Fish Audio API key is not configured")
        payload = {"text": text, "format": "mp3", "model": self.model}
        if self.reference_id:
            payload["reference_id"] = self.reference_id
        try:
            response = httpx.post(
                "https://api.fish.audio/v1/tts",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            if not response.content:
                raise SpeechProviderError("Fish Audio returned empty audio")
            return response.content
        except httpx.HTTPError as error:
            raise SpeechProviderError("Fish Audio could not synthesize the response") from error


def build_stt() -> DeepgramSTT | LocalSpeechProvider:
    if STT_PROVIDER.casefold() == "deepgram":
        return DeepgramSTT(DEEPGRAM_API_KEY, DEEPGRAM_MODEL)
    return LocalSpeechProvider(STT_PROVIDER)


def build_tts() -> FishAudioTTS | LocalSpeechProvider:
    if TTS_PROVIDER.casefold() in {"fish_audio", "fish-audio", "fishaudio"}:
        return FishAudioTTS(FISH_AUDIO_API_KEY, FISH_AUDIO_MODEL, FISH_AUDIO_REFERENCE_ID)
    return LocalSpeechProvider(TTS_PROVIDER)
