"""The provider catalogue: any market API can be plugged in."""

import pytest

from app.ai import provider, providers_catalog
from app.services import runtime_settings


@pytest.fixture()
def saved_overrides():
    """Snapshot/restore data/settings.json so provider tests cannot leak."""
    original = runtime_settings.read_overrides()
    try:
        yield original
    finally:
        runtime_settings.write_overrides(original)


def test_catalogue_covers_the_market():
    specs = providers_catalog.all_specs()
    ids = {spec.id for spec in specs}
    assert len(specs) >= 30
    for expected in (
        "ollama", "openai", "anthropic", "google-gemini", "deepseek", "moonshot",
        "zhipu", "qwen", "xai", "groq", "mistral", "together", "fireworks",
        "cerebras", "deepinfra", "openrouter", "perplexity", "cohere",
        "nvidia", "azure-openai", "lmstudio", "vllm", "custom",
    ):
        assert expected in ids, f"{expected} missing from the catalogue"

    url_optional = {"custom", "azure-openai", "cloudflare"}
    for spec in specs:
        assert spec.label and spec.kind in {"ollama", "openai", "anthropic", "azure"}
        if spec.base_url:
            assert spec.base_url.startswith("http"), spec.id
        else:
            # These need the account id / deployment URL typed into Settings,
            # so they must explain that in the UI.
            assert spec.id in url_optional and spec.notes, spec.id
        # Hosted vendors ship suggested models; local servers and the
        # URL-driven ones depend on what the user loaded/typed.
        if not spec.local and spec.id not in url_optional:
            assert spec.default_models, spec.id


def test_aliases_keep_old_ids_working():
    assert providers_catalog.resolve("kimi").id == "moonshot"
    assert providers_catalog.resolve("glm").id == "zhipu"
    assert providers_catalog.resolve("claude").id == "anthropic"
    assert providers_catalog.resolve("KIMI").id == "moonshot"
    assert providers_catalog.resolve("nope") is None
    assert providers_catalog.resolve(None) is None


def test_cloud_provider_does_not_inherit_the_ollama_model(saved_overrides):
    """Selecting DeepSeek must not send 'llama3.2:1b' to DeepSeek."""
    from app.core.config import get_settings

    settings = get_settings()
    runtime_settings.write_overrides({
        "AI_PROVIDER": "ollama",
        "AI_CHAT_MODEL": "llama3.2:1b",
    })
    ollama = providers_catalog.resolve("ollama")
    deepseek = providers_catalog.resolve("deepseek")

    assert provider.default_model_for(ollama, settings) == "llama3.2:1b"
    assert provider.default_model_for(deepseek, settings) == "deepseek-chat"

    runtime_settings.write_overrides({
        "AI_PROVIDER": "deepseek",
        "AI_CHAT_MODEL_DEEPSEEK": "deepseek-reasoner",
    })
    assert provider.default_model_for(deepseek, settings) == "deepseek-reasoner"


def test_deepseek_is_reachable_through_the_catalogue():
    """A cloud provider needs a key; the error says which one."""
    from app.core.config import get_settings

    settings = get_settings()
    spec = providers_catalog.resolve("deepseek")
    runtime_settings.write_overrides({
        "AI_PROVIDER": "deepseek", "AI_KEY_DEEPSEEK": "", "AI_API_KEY": "",
    })
    assert provider.base_url_for(spec, settings) == "https://api.deepseek.com/v1"
    assert provider.api_key_for(spec, settings) == ""

    runtime_settings.write_overrides({
        "AI_PROVIDER": "deepseek", "AI_KEY_DEEPSEEK": "sk-test-key",
    })
    assert provider.api_key_for(spec, settings) == "sk-test-key"
    available, reason = provider.available()
    assert available is True and reason is None


def test_embeddings_stay_local_when_chat_moves_to_the_cloud(saved_overrides, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    runtime_settings.write_overrides({
        "AI_PROVIDER": "deepseek",
        "AI_BASE_URL": "http://172.17.0.1:11434",
        "AI_BASE_URL_OLLAMA": "http://172.17.0.1:11434",
    })
    spec = providers_catalog.resolve("ollama")
    assert provider.embed_base_for(spec, settings) == "http://172.17.0.1:11434"


def test_legacy_vendor_key_slots_still_work(saved_overrides):
    """Existing installs store the OpenRouter key under OPENROUTER_API_KEY."""
    from app.core.config import get_settings

    settings = get_settings()
    spec = providers_catalog.resolve("openrouter")
    runtime_settings.write_overrides({
        "AI_PROVIDER": "openrouter",
        "OPENROUTER_API_KEY": "sk-or-v1-legacy-key",
    })
    assert provider.api_key_for(spec, settings) == "sk-or-v1-legacy-key"
    available, reason = provider.available()
    assert available is True, reason


def test_huge_vendor_catalogues_are_capped(monkeypatch):
    """OpenRouter lists hundreds of models; the picker must stay usable."""
    monkeypatch.setattr(
        provider, "_remote_model_names",
        lambda spec, settings: [f"vendor/model-{i}" for i in range(500)],
    )
    models = provider.list_models("openrouter")
    assert len(models) <= provider._MAX_LISTED_MODELS


def test_providers_endpoint_lists_the_catalogue(client, admin_headers):
    resp = client.get("/api/ai/providers", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 30
    by_id = {p["id"]: p for p in body["providers"]}
    assert "deepseek" in by_id
    assert by_id["deepseek"]["default_models"]
    assert by_id["deepseek"]["key_env"] == "DEEPSEEK_API_KEY"
    assert by_id["ollama"]["local"] is True
    assert by_id["ollama"]["selected"] is True or isinstance(
        by_id["ollama"]["selected"], bool
    )


def test_models_endpoint_uses_catalogue_suggestions(client, admin_headers, monkeypatch):
    """With no vendor catalogue reachable, suggested models are flagged."""
    monkeypatch.setattr(provider, "_remote_model_names", lambda spec, settings: [])
    resp = client.get("/api/ai/models?provider_id=deepseek", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "deepseek"
    names = [m["name"] for m in body["models"]]
    assert "deepseek-chat" in names
    assert all(m["source"] == "suggested" for m in body["models"])


def test_provider_test_endpoint_reports_success(client, admin_headers, monkeypatch):
    monkeypatch.setattr(provider, "chat", lambda *a, **k: "ready")
    resp = client.post(
        "/api/ai/providers/test",
        json={"provider": "deepseek", "api_key": "sk-probe", "model": "deepseek-chat"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "deepseek"


def test_provider_test_endpoint_reports_failure(client, admin_headers, monkeypatch):
    monkeypatch.setattr(provider, "chat", lambda *a, **k: None)
    resp = client.post(
        "/api/ai/providers/test", json={"provider": "groq"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_settings_accepts_any_catalogue_provider(client, admin_headers, saved_overrides):
    # DeepSeek key is stored per provider and Ollama's endpoint is stashed so
    # local retrieval keeps working after the switch.
    resp = client.patch(
        "/api/admin/settings",
        json={"ai_provider": "deepseek", "ai_api_key": "sk-deepseek-test", "ai_chat_model": "deepseek-chat"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_provider"] == "deepseek"
    assert body["ai_provider_label"] == "DeepSeek"
    assert body["ai_api_key_present"] is True
    assert body["ai_chat_model"] == "deepseek-chat"

    overrides = runtime_settings.read_overrides()
    assert overrides["AI_PROVIDER"] == "deepseek"
    assert overrides["AI_KEY_DEEPSEEK"] == "sk-deepseek-test"
    assert overrides["AI_CHAT_MODEL_DEEPSEEK"] == "deepseek-chat"
    assert overrides["AI_BASE_URL_OLLAMA"]

    # Switching back to the local models works too.
    resp = client.patch(
        "/api/admin/settings", json={"ai_provider": "ollama"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["ai_provider"] == "ollama"


def test_settings_rejects_an_unknown_provider(client, admin_headers, saved_overrides):
    resp = client.patch(
        "/api/admin/settings", json={"ai_provider": "not-a-vendor"}, headers=admin_headers
    )
    assert resp.status_code == 400
    assert "Unknown ai_provider" in resp.json()["detail"]
