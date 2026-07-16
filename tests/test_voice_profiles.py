"""Phase 4 — per-firm voice cloning: consent gate, provider seam, agent
assignment, tenancy. The two hard rules under test: no clone without the
voice owner's consent, and no non-ready voice ever reaches a caller."""

import httpx
import pytest

from api.voice import CartesiaVoiceCloneProvider, MockVoiceCloneProvider, VoiceCloneError

SAMPLE_URI = "https://firm-assets.example.com/partner-voice-sample.wav"


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


def test_provider_failure_marks_profile_failed(v1_client, firm, platform):
    class ExplodingCloner(MockVoiceCloneProvider):
        def create_voice(self, name, sample_uri, description=None):
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
