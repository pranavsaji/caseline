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

import base64
import hashlib
import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger("caseline.voice")


class VoiceCloneError(RuntimeError):
    """Clone creation failed at the provider; the profile is marked failed."""


def _decode_data_uri(uri: str) -> bytes:
    """Decode a ``data:<mime>;base64,<payload>`` URI to raw bytes. Raises
    VoiceCloneError on a malformed URI rather than returning empty audio."""
    try:
        header, _, payload = uri.partition(",")
        if not payload or ";base64" not in header:
            raise ValueError("expected a base64-encoded data URI")
        return base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise VoiceCloneError(f"Malformed inline audio data URI: {exc}") from exc


def _resolve_audio(sample_uri: str, client: httpx.Client) -> tuple[bytes, str | None]:
    """Turn a sample reference into ``(bytes, mime)``. Supports inline ``data:``
    URIs and ``http(s)`` URLs; every other scheme (``s3://``, bare paths, …)
    is refused loudly — the old behaviour silently cloned from empty bytes."""
    if sample_uri.startswith("data:"):
        mime = sample_uri[5:].split(";", 1)[0] or None
        return _decode_data_uri(sample_uri), mime
    if sample_uri.startswith(("http://", "https://")):
        resp = client.get(sample_uri)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type")
    scheme = sample_uri.split(":", 1)[0] if ":" in sample_uri else sample_uri
    raise VoiceCloneError(
        f"Unsupported sample reference {scheme!r}: provide an http(s) URL or"
        " upload/record audio (inline data URI). A pre-hosted http(s) URL is"
        " the only remote scheme fetched server-side."
    )


# Cartesia accepts flac, mp3, ogg/oga, wav, webm (and mpeg/mpga aliases). We
# label the multipart clip with the right filename + content-type so Cartesia's
# format detection works — the old code sent everything as "sample.wav", which
# silently broke mp3 / ogg / WhatsApp (opus-in-ogg) uploads.
_CLIP_FORMATS: dict[str, tuple[str, str]] = {
    "audio/wav": ("sample.wav", "audio/wav"),
    "audio/x-wav": ("sample.wav", "audio/wav"),
    "audio/mpeg": ("sample.mp3", "audio/mpeg"),
    "audio/mp3": ("sample.mp3", "audio/mpeg"),
    "audio/flac": ("sample.flac", "audio/flac"),
    "audio/x-flac": ("sample.flac", "audio/flac"),
    "audio/ogg": ("sample.ogg", "audio/ogg"),
    "application/ogg": ("sample.ogg", "audio/ogg"),
    "audio/opus": ("sample.ogg", "audio/ogg"),  # WhatsApp voice notes
    "audio/webm": ("sample.webm", "audio/webm"),
}


def _sniff_mime(data: bytes) -> str | None:
    """Best-effort container detection from magic bytes — reliable even when
    the browser reports no MIME type on an uploaded file."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:4] == b"fLaC":
        return "audio/flac"
    if data[:4] == b"OggS":  # ogg container — includes WhatsApp opus notes
        return "audio/ogg"
    if data[:4] == b"\x1aE\xdf\xa3":  # EBML → webm/mkv
        return "audio/webm"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def _clip_upload(audio: bytes, mime: str | None) -> tuple[str, bytes, str]:
    """Pick the (filename, bytes, content_type) tuple for the Cartesia clip,
    preferring sniffed bytes over the declared MIME, falling back to wav."""
    base = (_sniff_mime(audio) or (mime or "").split(";", 1)[0].strip().lower())
    filename, content_type = _CLIP_FORMATS.get(base, ("sample.wav", "audio/wav"))
    return filename, audio, content_type


class VoiceCloneProvider(ABC):
    name: str

    @abstractmethod
    def create_voice(
        self,
        name: str,
        sample_uri: str,
        description: str | None = None,
        audio: bytes | None = None,
        audio_mime: str | None = None,
    ) -> str:
        """Create a cloned voice from a consented sample; returns the
        provider's voice id (what the TTS stage is configured with).

        ``audio`` carries the raw sample bytes when the caller already has them
        (a browser recording or file upload); otherwise the provider resolves
        them from ``sample_uri``. ``audio_mime`` is the declared content type of
        those bytes, used to label the upload for the provider's format check."""

    def list_voices(self) -> list[dict]:
        """Preset/library voices the firm can pick alongside its own clones.
        Each entry: ``{id, name, description, language, gender}``. Default: none."""
        return []

    def close(self) -> None:  # pragma: no cover - default no-op
        pass


class MockVoiceCloneProvider(VoiceCloneProvider):
    """Local/test default: deterministic ids, no network, inspectable."""

    name = "mock"

    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_voice(
        self,
        name: str,
        sample_uri: str,
        description: str | None = None,
        audio: bytes | None = None,
        audio_mime: str | None = None,
    ) -> str:
        voice_id = "mock-voice-" + hashlib.sha256(f"{name}:{sample_uri}".encode()).hexdigest()[:12]
        self.created.append(
            {"name": name, "sample_uri": sample_uri, "voice_id": voice_id, "audio_bytes": len(audio or b"")}
        )
        logger.info("mock voice clone created: %s -> %s", name, voice_id)
        return voice_id

    def list_voices(self) -> list[dict]:
        # Plausible UUIDs so they pass the same validation as real Cartesia ids.
        return [
            {"id": "a0e99841-438c-4a64-b679-ae501e7d6091", "name": "Barbershop Man",
             "description": "Warm, friendly US male", "language": "en", "gender": "masculine"},
            {"id": "729651dc-c6c3-4ee5-97fa-350da1f88600", "name": "Sarah",
             "description": "Calm, professional US female", "language": "en", "gender": "feminine"},
        ]


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

    def create_voice(
        self,
        name: str,
        sample_uri: str,
        description: str | None = None,
        audio: bytes | None = None,
        audio_mime: str | None = None,
    ) -> str:
        # Resolve the consented sample to bytes (provided directly, inline
        # data URI, or fetched http(s) URL), then submit it for cloning.
        if audio is not None:
            clip, mime = audio, audio_mime
        else:
            clip, mime = _resolve_audio(sample_uri, self._client)
        if not clip:
            raise VoiceCloneError("Cannot clone from an empty audio sample")
        try:
            r = self._client.post(
                "/voices/clone",
                data={
                    "name": name,
                    "description": description or f"Caseline branded voice: {name}",
                    "mode": "stability",
                    "language": "en",
                },
                files={"clip": _clip_upload(clip, mime)},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise VoiceCloneError(f"Cartesia voice clone failed: {exc}") from exc
        voice_id = r.json().get("id")
        if not voice_id:
            raise VoiceCloneError("Cartesia voice clone returned no voice id")
        return voice_id

    def list_voices(self) -> list[dict]:
        try:
            r = self._client.get("/voices", params={"limit": 100})
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise VoiceCloneError(f"Cartesia list voices failed: {exc}") from exc
        voices = [
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "description": v.get("description"),
                "language": v.get("language"),
                "gender": v.get("gender"),
            }
            for v in r.json().get("data", [])
        ]
        return [v for v in voices if v["id"] and v["name"]]

    def close(self) -> None:
        self._client.close()


def make_voice_clone_provider() -> VoiceCloneProvider:
    import os

    api_key = os.getenv("CARTESIA_API_KEY")
    if os.getenv("CASELINE_VOICE_CLONE_PROVIDER", "").lower() == "cartesia" and api_key:
        return CartesiaVoiceCloneProvider(api_key)
    return MockVoiceCloneProvider()
