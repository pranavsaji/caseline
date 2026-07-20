"""The Config Studio provider catalog: what `configured` means per provider.

`llm_catalog()` must be importable without livekit (the API serves it), and its
`configured` flag drives whether the UI lets you pick a provider. The subtle
case is Ollama — it needs no API key, so a "no key required means ready" check
would mark it usable in production, where there is no Ollama server to reach and
selecting it silently breaks every call.
"""

from agent import providers


def _entry(catalog, provider):
    return next(p for p in catalog if p["provider"] == provider)


def test_hosted_provider_configured_only_with_its_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _entry(providers.llm_catalog(), "anthropic")["configured"] is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    anthropic = _entry(providers.llm_catalog(), "anthropic")
    assert anthropic["configured"] is True
    assert anthropic["requires"] == "ANTHROPIC_API_KEY"


def test_ollama_not_configured_without_a_server(monkeypatch):
    # No key, no server URL -> not selectable (the production footgun).
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    ollama = _entry(providers.llm_catalog(), "ollama")
    assert ollama["configured"] is False
    assert ollama["requires"] == "OLLAMA_BASE_URL"


def test_ollama_configured_when_pointed_at_a_server(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    assert _entry(providers.llm_catalog(), "ollama")["configured"] is True


def test_catalog_shape_is_stable():
    for entry in providers.llm_catalog():
        assert {"provider", "label", "env_key", "requires", "configured", "models"} <= entry.keys()
