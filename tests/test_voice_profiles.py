"""Phase 4 — per-firm voice cloning: consent gate, provider seam, agent
assignment, tenancy. The two hard rules under test: no clone without the
voice owner's consent, and no non-ready voice ever reaches a caller."""

import base64

import httpx
import pytest

from api.voice import (
    CartesiaVoiceCloneProvider,
    MockVoiceCloneProvider,
    VoiceCloneError,
    make_voice_clone_provider,
)


def test_clone_provider_selection(monkeypatch):
    # The production footgun: a Cartesia key present but the provider not
    # explicitly turned on used to yield the mock cloner, whose fake
    # `mock-voice-…` ids the TTS stage rejects — so a "successful" clone never
    # spoke. Key presence alone must now select the real provider.
    monkeypatch.delenv("CASELINE_VOICE_CLONE_PROVIDER", raising=False)
    monkeypatch.setenv("CARTESIA_API_KEY", "sk-test")
    assert isinstance(make_voice_clone_provider(), CartesiaVoiceCloneProvider)

    # Explicit opt-out still forces the mock even with a key present.
    monkeypatch.setenv("CASELINE_VOICE_CLONE_PROVIDER", "mock")
    assert isinstance(make_voice_clone_provider(), MockVoiceCloneProvider)

    # No key -> mock (local/dev default, no network).
    monkeypatch.delenv("CASELINE_VOICE_CLONE_PROVIDER", raising=False)
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    assert isinstance(make_voice_clone_provider(), MockVoiceCloneProvider)

SAMPLE_URI = "https://firm-assets.example.com/partner-voice-sample.wav"
# A tiny inline sample, as the browser recorder/uploader sends it.
SAMPLE_DATA = "data:audio/webm;base64," + base64.b64encode(b"RIFFfakewav").decode()


def create_profile(v1_client, firm, **overrides):
    body = {
        "name": "Bluebonnet Brand Voice",
        "sample_uri": SAMPLE_URI,
        "consent_confirmed": True,
    } | overrides
    return v1_client.post("/v1/voice-profiles", json=body, headers=firm["headers"])


# ---------------------------------------------------------------------------
# consent is structural
# ---------------------------------------------------------------------------


def test_clone_without_consent_is_refused(v1_client, firm):
    r = create_profile(v1_client, firm, consent_confirmed=False)
    assert r.status_code == 422
    assert "consent" in r.json()["detail"].lower()
    assert v1_client.get("/v1/voice-profiles", headers=firm["headers"]).json() == []


def test_schema_rejects_unconsented_rows_even_from_code(db, firm):
    # Belt and suspenders: the table CHECK refuses what the API refuses.
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with db.firm(firm["firm_id"]) as conn:
            conn.execute(
                "INSERT INTO voice_profiles (firm_id, name, consent_confirmed)"
                " VALUES (%s, 'sneaky', false)",
                (firm["firm_id"],),
            )


# ---------------------------------------------------------------------------
# clone lifecycle
# ---------------------------------------------------------------------------


def test_clone_creates_ready_profile_with_provider_voice_id(v1_client, firm, platform):
    r = create_profile(v1_client, firm)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["provider_voice_id"].startswith("mock-voice-")
    assert platform.voice_cloner.created[0]["sample_uri"] == SAMPLE_URI

    profiles = v1_client.get("/v1/voice-profiles", headers=firm["headers"]).json()
    assert len(profiles) == 1
    assert profiles[0]["status"] == "ready"
    assert profiles[0]["provider"] == "mock"


def test_clone_from_inline_recording_uploads_audio(v1_client, firm, platform):
    # Browser recording / file upload path: no pre-hosted URL, audio inline.
    r = create_profile(v1_client, firm, sample_uri=None, sample_data=SAMPLE_DATA)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    # The decoded bytes reached the provider; sample_uri is a compact marker,
    # never the raw base64 blob.
    created = platform.voice_cloner.created[0]
    assert created["audio_bytes"] == len(b"RIFFfakewav")
    assert created["sample_uri"].startswith("inline:audio/webm:")
    profiles = v1_client.get("/v1/voice-profiles", headers=firm["headers"]).json()
    assert "base64" not in (profiles[0]["sample_uri"] or "")


def test_create_without_any_sample_is_rejected(v1_client, firm):
    r = create_profile(v1_client, firm, sample_uri=None)
    assert r.status_code == 422


def test_provider_failure_marks_profile_failed(v1_client, firm, platform):
    class ExplodingCloner(MockVoiceCloneProvider):
        def create_voice(self, name, sample_uri, description=None, audio=None, audio_mime=None):
            raise VoiceCloneError("provider melted")

    platform.voice_cloner = ExplodingCloner()
    r = create_profile(v1_client, firm)
    assert r.status_code == 502
    profiles = v1_client.get("/v1/voice-profiles", headers=firm["headers"]).json()
    assert profiles[0]["status"] == "failed"
    assert "melted" in profiles[0]["error"]


# ---------------------------------------------------------------------------
# assignment: only ready voices reach callers
# ---------------------------------------------------------------------------


def test_ready_voice_assigns_to_agent_and_reaches_agent_config(v1_client, firm):
    profile = create_profile(v1_client, firm).json()
    r = v1_client.post(
        f"/v1/agents/{firm['agent_id']}/voice",
        json={"voice_profile_id": profile["voice_profile_id"]},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["voice_id"] == profile["provider_voice_id"]
    # The worker fetches this at call start: the very next call speaks it.
    config = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    assert config["voice_id"] == profile["provider_voice_id"]


def test_delete_voice_profile_removes_it(v1_client, firm):
    profile = create_profile(v1_client, firm).json()
    pid = profile["voice_profile_id"]
    r = v1_client.delete(f"/v1/voice-profiles/{pid}", headers=firm["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted"
    assert r.json()["cleared_agent_voice"] is False
    assert v1_client.get("/v1/voice-profiles", headers=firm["headers"]).json() == []


def test_delete_in_use_voice_clears_agent_assignment(v1_client, firm):
    # Deleting the voice the agent currently speaks in must clear the assignment
    # so the next call reverts to the default rather than pointing at a gone voice.
    profile = create_profile(v1_client, firm).json()
    v1_client.post(
        f"/v1/agents/{firm['agent_id']}/voice",
        json={"voice_profile_id": profile["voice_profile_id"]},
        headers=firm["headers"],
    )
    assert v1_client.get("/v1/agent-config", headers=firm["headers"]).json()["voice_id"]

    r = v1_client.delete(
        f"/v1/voice-profiles/{profile['voice_profile_id']}", headers=firm["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["cleared_agent_voice"] is True
    # Agent voice is cleared -> reverts to platform default.
    assert not v1_client.get("/v1/agent-config", headers=firm["headers"]).json()["voice_id"]


def test_delete_unknown_voice_is_404(v1_client, firm):
    import uuid as _uuid
    r = v1_client.delete(f"/v1/voice-profiles/{_uuid.uuid4()}", headers=firm["headers"])
    assert r.status_code == 404


def test_cannot_delete_another_firms_voice(v1_client, firm, second_firm):
    profile = create_profile(v1_client, firm).json()
    # RLS hides it from firm B, so the delete 404s and firm A's row survives.
    r = v1_client.delete(
        f"/v1/voice-profiles/{profile['voice_profile_id']}", headers=second_firm["headers"]
    )
    assert r.status_code == 404
    assert len(v1_client.get("/v1/voice-profiles", headers=firm["headers"]).json()) == 1


def test_non_ready_voice_cannot_be_assigned(v1_client, firm, db):
    with db.firm(firm["firm_id"]) as conn:
        row = conn.execute(
            "INSERT INTO voice_profiles (firm_id, name, consent_confirmed, status)"
            " VALUES (%s, 'still cooking', true, 'pending') RETURNING id",
            (firm["firm_id"],),
        ).fetchone()
    r = v1_client.post(
        f"/v1/agents/{firm['agent_id']}/voice",
        json={"voice_profile_id": str(row["id"])},
        headers=firm["headers"],
    )
    assert r.status_code == 409
    assert v1_client.get("/v1/agent-config", headers=firm["headers"]).json()["voice_id"] is None


def test_cross_tenant_profile_is_invisible_and_unassignable(v1_client, firm, second_firm):
    profile = create_profile(v1_client, firm).json()
    assert v1_client.get("/v1/voice-profiles", headers=second_firm["headers"]).json() == []
    r = v1_client.post(
        f"/v1/agents/{second_firm['agent_id']}/voice",
        json={"voice_profile_id": profile["voice_profile_id"]},
        headers=second_firm["headers"],
    )
    assert r.status_code == 404  # RLS makes it not exist for firm B


# ---------------------------------------------------------------------------
# Cartesia adapter against a mocked transport (same posture as CMS adapters)
# ---------------------------------------------------------------------------


def _cartesia_transport(responses: dict[str, httpx.Response]):
    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, response in responses.items():
            if fragment in str(request.url):
                return response
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_cartesia_adapter_clones_via_api():
    transport = _cartesia_transport(
        {
            "/voices/clone": httpx.Response(201, json={"id": "cartesia-voice-42"}),
            "firm-assets": httpx.Response(200, content=b"RIFFfakewav"),
        }
    )
    provider = CartesiaVoiceCloneProvider("key", transport=transport)
    voice_id = provider.create_voice("Brand Voice", SAMPLE_URI)
    assert voice_id == "cartesia-voice-42"
    provider.close()


def test_cartesia_adapter_clones_from_inline_audio_without_fetching():
    # Direct bytes (browser recording / upload): no network fetch of a sample.
    transport = _cartesia_transport(
        {"/voices/clone": httpx.Response(201, json={"id": "cartesia-voice-inline"})}
    )
    provider = CartesiaVoiceCloneProvider("key", transport=transport)
    voice_id = provider.create_voice("Brand Voice", "inline:audio/webm", audio=b"RIFFfakewav")
    assert voice_id == "cartesia-voice-inline"
    provider.close()


def test_cartesia_adapter_decodes_inline_data_uri():
    transport = _cartesia_transport(
        {"/voices/clone": httpx.Response(201, json={"id": "cartesia-voice-datauri"})}
    )
    provider = CartesiaVoiceCloneProvider("key", transport=transport)
    assert provider.create_voice("Brand Voice", SAMPLE_DATA) == "cartesia-voice-datauri"
    provider.close()


def test_cartesia_adapter_refuses_unsupported_scheme_instead_of_empty_clone():
    # Regression: an s3:// (or any non-http) reference used to silently clone
    # from EMPTY bytes. It must now fail loudly rather than produce a dud voice.
    transport = _cartesia_transport(
        {"/voices/clone": httpx.Response(201, json={"id": "should-not-be-reached"})}
    )
    provider = CartesiaVoiceCloneProvider("key", transport=transport)
    with pytest.raises(VoiceCloneError, match="Unsupported sample reference"):
        provider.create_voice("Brand Voice", "s3://firm-assets/sample.wav")
    provider.close()


@pytest.mark.parametrize(
    "audio,mime,want_name,want_ct",
    [
        (b"ID3\x03fake-mp3-bytes", "audio/mpeg", "sample.mp3", "audio/mpeg"),
        (b"OggSfake-opus-note", "audio/ogg", "sample.ogg", "audio/ogg"),
        (b"RIFF....WAVEfake", "audio/wav", "sample.wav", "audio/wav"),
        # Browser reported no MIME (empty) — magic bytes still identify it.
        (b"OggSwhatsapp-voice", "", "sample.ogg", "audio/ogg"),
    ],
)
def test_cartesia_labels_clip_by_actual_format(audio, mime, want_name, want_ct):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/voices/clone" in str(request.url):
            # The multipart filename + content-type must reflect the real audio.
            body = request.content
            seen["name"] = want_name if want_name.encode() in body else None
            seen["ct"] = want_ct if want_ct.encode() in body else None
            return httpx.Response(201, json={"id": "cartesia-voice-fmt"})
        return httpx.Response(404)

    provider = CartesiaVoiceCloneProvider("key", transport=httpx.MockTransport(handler))
    provider.create_voice("Brand", "inline", audio=audio, audio_mime=mime)
    assert seen["name"] == want_name
    assert seen["ct"] == want_ct
    provider.close()


def test_cartesia_adapter_raises_clean_error_on_failure():
    transport = _cartesia_transport(
        {
            "/voices/clone": httpx.Response(500, json={"error": "boom"}),
            "firm-assets": httpx.Response(200, content=b"RIFFfakewav"),
        }
    )
    provider = CartesiaVoiceCloneProvider("key", transport=transport)
    with pytest.raises(VoiceCloneError):
        provider.create_voice("Brand Voice", SAMPLE_URI)
    provider.close()
