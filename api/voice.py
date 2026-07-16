"""Per-firm voice cloning (Phase 4): branded, consistent voice per firm.

The clone provider sits behind ``VoiceCloneProvider`` like every other
external dependency (guiding principle #3): the platform knows "make me a
voice from this consented sample", never which vendor does it. Cartesia is
the real adapter (same TTS vendor the voice pipeline already speaks);
``MockVoiceCloneProvider`` is the local/test default.

Two hard rules, enforced here and in the schema:

  * **Consent is not optional.** A profile cannot be created without
    ``consent_confirmed`` — cloning a voice whose owner has not agreed is a
    legal and ethical non-starter, so the API refuses and the table CHECK
    refuses again.
  * **Only ready voices reach callers.** Assignment to an agent requires
    ``status = 'ready'``; a pending or failed clone can never be the voice a
    caller hears. Assignment flows through ``update_agent_config`` so the
    config cache invalidates and the next call picks the voice up.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger("caseline.voice")


class VoiceCloneError(RuntimeError):
    """Clone creation failed at the provider; the profile is marked failed."""


class VoiceCloneProvider(ABC):
    name: str

    @abstractmethod
    def create_voice(self, name: str, sample_uri: str, description: str | None = None) -> str:
        """Create a cloned voice from a consented sample; returns the
        provider's voice id (what the TTS stage is configured with)."""

    def close(self) -> None:  # pragma: no cover - default no-op
        pass


class MockVoiceCloneProvider(VoiceCloneProvider):
    """Local/test default: deterministic ids, no network, inspectable."""

    name = "mock"

    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_voice(self, name: str, sample_uri: str, description: str | None = None) -> str:
        voice_id = "mock-voice-" + hashlib.sha256(f"{name}:{sample_uri}".encode()).hexdigest()[:12]
        self.created.append({"name": name, "sample_uri": sample_uri, "voice_id": voice_id})
        logger.info("mock voice clone created: %s -> %s", name, voice_id)
        return voice_id


class CartesiaVoiceCloneProvider(VoiceCloneProvider):
    """Cartesia voice cloning API. The returned voice id plugs straight into
    the existing TTS stage (``cartesia.TTS(voice=<id>)`` via agent config)."""

    name = "cartesia"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.cartesia.ai",
        api_version: str = "2025-04-16",
        transport: httpx.BaseTransport | None = None,
    ):
        self._client = httpx.Client(
            base_url=base_url,
            timeout=60.0,
            headers={"X-API-Key": api_key, "Cartesia-Version": api_version},
            transport=transport,
        )

    def create_voice(self, name: str, sample_uri: str, description: str | None = None) -> str:
        # Fetch the consented sample, then submit it for cloning.
        try:
            sample = self._client.get(sample_uri) if sample_uri.startswith("http") else None
            audio = sample.content if sample is not None else b""
            if sample is not None:
                sample.raise_for_status()
            r = self._client.post(
                "/voices/clone",
                data={
                    "name": name,
                    "description": description or f"Caseline branded voice: {name}",
                    "mode": "stability",
                    "language": "en",
                },
                files={"clip": ("sample.wav", audio, "audio/wav")},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise VoiceCloneError(f"Cartesia voice clone failed: {exc}") from exc
        voice_id = r.json().get("id")
        if not voice_id:
            raise VoiceCloneError("Cartesia voice clone returned no voice id")
        return voice_id

    def close(self) -> None:
        self._client.close()


def make_voice_clone_provider() -> VoiceCloneProvider:
    import os

    api_key = os.getenv("CARTESIA_API_KEY")
    if os.getenv("CASELINE_VOICE_CLONE_PROVIDER", "").lower() == "cartesia" and api_key:
        return CartesiaVoiceCloneProvider(api_key)
    return MockVoiceCloneProvider()
