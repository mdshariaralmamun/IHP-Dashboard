"""LLM provider abstraction (local Ollama + OpenAI-compatible fallback).

Per v2 spec:
  - Section 4: chat completions with local Ollama
  - Section 6: provider flexibility (local + OpenAI-compatible hosted APIs)

Supported AI_PROVIDER values:
  - "ollama"      : local Ollama instance at AI_BASE_URL
  - "openrouter"  : OpenRouter hosted API (OPENROUTER_API_KEY)
  - "anthropic"   : Anthropic API (ANTHROPIC_API_KEY)
  - "openai"      : OpenAI API (OPENAI_API_KEY)
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from ..core.config import get_settings
from ..services import runtime_settings
from .providers_catalog import CATALOG, ProviderSpec, resolve as resolve_provider


def _eff(key: str, env_default: str) -> str:
    """Resolve a setting: admin override if present, else the env default."""
    return runtime_settings.effective(key, env_default)


# ---------------------------------------------------------------------------
# Provider resolution (all market APIs, via backend/app/ai/providers_catalog.py)
# ---------------------------------------------------------------------------


def effective_provider(settings: Any) -> str:
    """The provider id in use, normalised through the catalogue aliases."""
    requested = _eff("AI_PROVIDER", settings.AI_PROVIDER).strip().lower()
    spec = resolve_provider(requested)
    return spec.id if spec else requested


def spec_for(settings: Any, provider: str | None = None) -> ProviderSpec | None:
    if provider:
        return resolve_provider(provider)
    return resolve_provider(effective_provider(settings))


def base_url_for(spec: ProviderSpec, settings: Any) -> str:
    """Base URL for a provider.

    Per-provider overrides win (`AI_BASE_URL_<PROVIDER>`); the generic
    `AI_BASE_URL` is only honoured for Ollama and for providers that ship no
    default URL, so switching to a cloud vendor cannot inherit the local URL.
    """
    override = runtime_settings.read_overrides().get(f"AI_BASE_URL_{spec.id.upper()}", "")
    if override:
        return str(override).rstrip("/")
    if spec.id == "ollama":
        return _eff("AI_BASE_URL", settings.AI_BASE_URL).rstrip("/")
    if not spec.base_url:
        return _eff("AI_BASE_URL", settings.AI_BASE_URL).rstrip("/")
    return spec.base_url.rstrip("/")


def api_key_for(spec: ProviderSpec, settings: Any) -> str:
    """API key: per-provider runtime override, then env, then the generic slot."""
    overrides = runtime_settings.read_overrides()
    per_provider = overrides.get(f"AI_KEY_{spec.id.upper()}", "")
    if per_provider:
        return str(per_provider).strip()
    if spec.env_key:
        env_value = getattr(settings, spec.env_key, "") or ""
        if env_value:
            return str(env_value).strip()
    return _eff("AI_API_KEY", settings.AI_API_KEY).strip()


def embed_base_for(spec: ProviderSpec, settings: Any) -> str:
    """Base URL for the embeddings endpoint.

    Retrieval must keep working when the chat provider is switched to a cloud
    vendor, so the Ollama base is resolved independently of `AI_BASE_URL`:
    explicit `AI_EMBED_BASE_URL`, then the stashed `AI_BASE_URL_OLLAMA` (the
    Settings UI records this when switching away from Ollama), then
    `AI_BASE_URL` when it really is an Ollama endpoint.
    """
    if spec.kind != "ollama":
        return base_url_for(spec, settings)
    overrides = runtime_settings.read_overrides()
    for key in ("AI_EMBED_BASE_URL", "AI_BASE_URL_OLLAMA"):
        value = overrides.get(key)
        if value:
            return str(value).rstrip("/")
    candidate = _eff("AI_BASE_URL", settings.AI_BASE_URL).rstrip("/")
    if effective_provider(settings) == "ollama" or ":11434" in candidate:
        return candidate
    return spec.base_url or "http://localhost:11434"


def default_model_for(spec: ProviderSpec, settings: Any) -> str:
    """Model to use for a provider.

    Per-provider overrides (`AI_CHAT_MODEL_<PROVIDER>`) win, so selecting a
    cloud vendor never inherits a local Ollama model name (and vice versa).
    """
    per_provider = runtime_settings.read_overrides().get(
        f"AI_CHAT_MODEL_{spec.id.upper()}", ""
    )
    if per_provider:
        return str(per_provider).strip()
    if spec.id == "ollama" or spec.local:
        generic = _eff("AI_CHAT_MODEL", settings.AI_CHAT_MODEL).strip()
        if generic:
            return generic
    return spec.default_models[0] if spec.default_models else ""


def _auth_headers(spec: ProviderSpec, api_key: str, settings: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    if spec.key_header == "api-key":
        headers["api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if spec.id == "openrouter":
        headers["HTTP-Referer"] = "https://ihp-platform.kaust.edu.sa"
        headers["X-Title"] = "IHP Design and Construction Platform"
    return headers


def _post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> dict[str, Any] | None:
    """POST JSON to a URL and return decoded JSON response, or None on failure."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(
            url,
            data=data,
            headers=req_headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"LLM provider request failed ({url}): {e}")
        return None


def _chat_timeout(settings: Any) -> int:
    try:
        return int(getattr(settings, "AI_CHAT_TIMEOUT", 600) or 600)
    except (TypeError, ValueError):
        return 600


def _get(url: str, headers: dict[str, str] | None = None,
         timeout: int = 10) -> dict[str, Any] | None:
    """GET JSON from a URL and return the decoded body, or None on failure."""
    try:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"LLM provider GET failed: {e}")
        return None


def available() -> tuple[bool, str | None]:
    """Return (is_available, reason).

    Checks whether the configured AI provider is reachable and usable.
    Uses runtime overrides so admin-saved settings take effect.
    """
    settings = get_settings()
    spec = spec_for(settings)
    if spec is None:
        return False, f"Unknown AI_PROVIDER: {effective_provider(settings)!r}"[:200]

    if spec.id == "ollama":
        base_url = base_url_for(spec, settings)
        if not base_url:
            return False, "AI_BASE_URL is not configured"
        # /api/tags is a GET endpoint. POSTing to it returns 405 and made the
        # app report a perfectly healthy Ollama as "offline".
        result = _get(f"{base_url}/api/tags")
        if result is None:
            return False, f"Cannot reach Ollama at {base_url} (is Ollama running?)"
        return True, None

    key = api_key_for(spec, settings)
    if spec.local and spec.id == "custom":
        if not base_url_for(spec, settings):
            return False, "Set the base URL for the custom endpoint in Settings"
        return (True, None) if key or True else (False, None)

    if spec.local:
        # Local OpenAI-compatible servers (LM Studio, vLLM, llama.cpp, ...).
        base = base_url_for(spec, settings)
        if _get(f"{base}/models", headers=_auth_headers(spec, key, settings), timeout=5) is None:
            return False, f"{spec.label} is not reachable at {base} - is the server running?"
        return True, None

    if not key and spec.kind != "azure":
        return False, (
            f"No API key configured for {spec.label}. Add it in Settings "
            f"(or set {spec.env_key or 'AI_API_KEY'} in .env)."
        )
    if spec.kind == "azure":
        base = base_url_for(spec, settings)
        if not base:
            return False, "Set the Azure OpenAI deployment base URL in Settings"
        if not key:
            return False, "No API key configured for Azure OpenAI"
    return True, None


def chat(messages: list[dict[str, str]], system: str | None = None,
         model: str | None = None, provider: str | None = None) -> str | None:
    """Send a chat completion request to a provider.

    `model` overrides the configured chat model and `provider` the configured
    vendor for this one request, which is what lets the assistant offer local
    Ollama models and cloud models side by side.
    """
    settings = get_settings()
    spec = spec_for(settings, provider)
    if spec is None:
        print(f"LLM provider unknown: {provider or effective_provider(settings)!r}")
        return None

    if spec.kind == "ollama":
        return _chat_ollama(messages, system, settings, model=model, spec=spec)
    if spec.kind == "anthropic":
        return _chat_anthropic(messages, system, settings, model=model, spec=spec)
    return _chat_openai_compat(messages, system, settings, spec, model=model)


#: Remote /v1/models responses are cached briefly: the UI polls this.
_model_cache: dict[str, tuple[float, list[str]]] = {}
_MODEL_CACHE_TTL = 120


def _remote_model_names(spec: ProviderSpec, settings: Any) -> list[str]:
    key = api_key_for(spec, settings)
    base = base_url_for(spec, settings)
    if not base:
        return []
    cached = _model_cache.get(spec.id)
    if cached and time.time() - cached[0] < _MODEL_CACHE_TTL:
        return cached[1]
    data = _get(
        f"{base}/models", headers=_auth_headers(spec, key, settings), timeout=8
    )
    names: list[str] = []
    for item in (data or {}).get("data", []) or []:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if name:
                names.append(str(name))
    if names:
        _model_cache[spec.id] = (time.time(), names)
    return names


def list_models(provider: str | None = None) -> list[dict[str, Any]]:
    """Models the provider can run: pulled Ollama models or the vendor's list.

    Cloud vendors are asked for their catalogue when a key is configured; if
    that is not possible the catalogue's suggested models are returned and
    flagged with `source: "suggested"` so the UI can say so.
    """
    settings = get_settings()
    spec = spec_for(settings, provider)
    if spec is None:
        return []
    active = default_model_for(spec, settings)

    if spec.kind == "ollama":
        base = base_url_for(spec, settings)
        data = _get(f"{base}/api/tags")
        if not data:
            return []
        out: list[dict[str, Any]] = []
        for model in data.get("models", []):
            name = model.get("name")
            if not name:
                continue
            out.append({
                "name": name,
                "active": name == active,
                "size": model.get("size"),
                "family": (model.get("details") or {}).get("family"),
                "params": (model.get("details") or {}).get("parameter_size"),
                "provider": spec.id,
                "source": "live",
            })
        out.sort(key=lambda m: (not m["active"], m["name"]))
        return out

    names = _remote_model_names(spec, settings)
    source = "live" if names else "suggested"
    if not names:
        names = list(spec.default_models)
    if active and active not in names:
        names.insert(0, active)
    return [
        {
            "name": name, "active": name == active, "size": None,
            "family": None, "params": None, "provider": spec.id, "source": source,
        }
        for name in names
    ]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _chat_ollama(
    messages: list[dict[str, str]],
    system: str | None,
    settings: Any,
    model: str | None = None,
    spec: ProviderSpec | None = None,
) -> str | None:
    spec = spec or resolve_provider("ollama")
    base = base_url_for(spec, settings)
    model = model or default_model_for(spec, settings)
    # Ollama defaults to a 2048-token window, which is smaller than the
    # assistant's live-context block - it then rejects the request with
    # HTTP 400 and the chat looks empty. Always ask for an explicit window.
    num_ctx = int(getattr(settings, "AI_NUM_CTX", 8192) or 8192)
    num_predict = int(getattr(settings, "AI_NUM_PREDICT", 512) or 512)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
        "options": {"num_ctx": num_ctx, "num_predict": num_predict},
    }
    if system:
        payload["system"] = system
    response = _post(f"{base}/api/chat", payload, timeout=_chat_timeout(settings))
    if response is None:
        return None
    message = response.get("message")
    if message and isinstance(message, dict):
        return message.get("content")
    return None


def _chat_openai_compat(
    messages: list[dict[str, str]],
    system: str | None,
    settings: Any,
    spec: ProviderSpec,
    model: str | None = None,
) -> str | None:
    """Any OpenAI-compatible /chat/completions endpoint (see providers_catalog).

    Covers OpenAI, Azure, Gemini (OpenAI mode), DeepSeek, Moonshot, Zhipu,
    Qwen, Groq, Mistral, Together, Fireworks, OpenRouter, Perplexity and the
    local servers (LM Studio, vLLM, llama.cpp, LocalAI, Jan).
    """
    base = base_url_for(spec, settings)
    if not base:
        print(f"LLM provider {spec.id}: no base URL configured")
        return None
    api_key = api_key_for(spec, settings)
    chat_model = model or default_model_for(spec, settings)
    url = f"{base}/chat/completions"
    if spec.kind == "azure":
        api_version = _eff(
            "AZURE_OPENAI_API_VERSION",
            getattr(settings, "AZURE_OPENAI_API_VERSION", "") or "2024-08-01-preview",
        )
        if "api-version=" not in url:
            url += ("&" if "?" in url else "?") + f"api-version={api_version}"

    all_messages: list[dict[str, str]] = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend({"role": m["role"], "content": m["content"]} for m in messages)

    payload: dict[str, Any] = {"model": chat_model, "messages": all_messages}
    response = _post(
        url, payload, _auth_headers(spec, api_key, settings),
        timeout=_chat_timeout(settings),
    )
    if response is None:
        return None
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _chat_anthropic(
    messages: list[dict[str, str]],
    system: str | None,
    settings: Any,
    model: str | None = None,
    spec: ProviderSpec | None = None,
) -> str | None:
    """Anthropic Messages API."""
    spec = spec or resolve_provider("anthropic")
    url = base_url_for(spec, settings) or "https://api.anthropic.com/v1/messages"
    model = model or default_model_for(spec, settings) or "claude-3-5-haiku-latest"
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
    }
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": api_key_for(spec, settings),
        "anthropic-version": "2023-06-01",
    }
    response = _post(url, payload, headers, timeout=_chat_timeout(settings))
    if response is None:
        return None
    try:
        return response["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None


def embed_many(texts: list[str], batch_size: int = 8) -> list[list[float] | None]:
    """Embed several texts, batched. Returns one entry per input (None on failure).

    Embeddings are independent of the chat provider: swapping the chat model to
    a cloud vendor must not break retrieval, so this always uses a local Ollama
    unless `AI_EMBED_PROVIDER` points somewhere else (any OpenAI-compatible
    /embeddings endpoint works too).
    """
    results: list[list[float] | None] = [None] * len(texts)
    if not texts:
        return results
    settings = get_settings()
    overrides = runtime_settings.read_overrides()
    embed_provider = str(
        overrides.get("AI_EMBED_PROVIDER")
        or getattr(settings, "AI_EMBED_PROVIDER", "")
        or "ollama"
    ).strip().lower()
    spec = resolve_provider(embed_provider) or resolve_provider("ollama")
    embed_model = _eff("AI_EMBED_MODEL", settings.AI_EMBED_MODEL)
    base = embed_base_for(spec, settings).rstrip("/")

    if spec.kind != "ollama":
        # OpenAI-compatible embeddings endpoint (OpenAI, Mistral, Gemini, ...).
        for start in range(0, len(texts), max(1, batch_size)):
            window = texts[start:start + batch_size]
            response = _post(
                f"{base}/embeddings",
                {"model": embed_model, "input": window},
                _auth_headers(spec, api_key_for(spec, settings), settings),
                timeout=120,
            )
            items = (response or {}).get("data")
            if not isinstance(items, list):
                continue
            for offset, item in enumerate(items):
                vector = (item or {}).get("embedding") if isinstance(item, dict) else None
                if isinstance(vector, list) and vector:
                    results[start + offset] = [round(float(v), 5) for v in vector]
        return results

    for start in range(0, len(texts), max(1, batch_size)):
        window = texts[start:start + batch_size]
        response = _post(
            f"{base}/api/embed", {"model": embed_model, "input": window}
        )
        vectors = (response or {}).get("embeddings")
        if isinstance(vectors, list) and len(vectors) == len(window):
            for offset, vector in enumerate(vectors):
                if isinstance(vector, list) and vector:
                    results[start + offset] = [round(float(v), 5) for v in vector]
            continue
        # Legacy server: one request per text.
        for offset, text in enumerate(window):
            legacy = _post(
                f"{base}/api/embeddings", {"model": embed_model, "prompt": text}
            )
            vector = (legacy or {}).get("embedding")
            if isinstance(vector, list) and vector:
                # Rounded to 5 decimals: ~3x smaller JSON embeddings (tens of
                # thousands of chunks) with no measurable effect on cosine.
                results[start + offset] = [round(float(v), 5) for v in vector]
    return results


def embed(text: str) -> list[float] | None:
    """Return an embedding vector for the given text, or None if unavailable."""
    if not (text or "").strip():
        return None
    return embed_many([text])[0]
