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
import urllib.request
from typing import Any

from ..core.config import get_settings
from ..services import runtime_settings


def _eff(key: str, env_default: str) -> str:
    """Resolve a setting: admin override if present, else the env default."""
    return runtime_settings.effective(key, env_default)


def _post(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any] | None:
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"LLM provider request failed: {e}")
        return None


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
    provider = _eff("AI_PROVIDER", settings.AI_PROVIDER).lower()

    if provider == "ollama":
        base_url = _eff("AI_BASE_URL", settings.AI_BASE_URL)
        if not base_url:
            return False, "AI_BASE_URL is not configured"
        # /api/tags is a GET endpoint. POSTing to it returns 405 and made the
        # app report a perfectly healthy Ollama as "offline".
        result = _get(f"{base_url.rstrip('/')}/api/tags")
        if result is None:
            return False, "Cannot reach Ollama at AI_BASE_URL (is Ollama running?)"
        return True, None

    if provider == "openrouter":
        key = _eff("OPENROUTER_API_KEY", settings.OPENROUTER_API_KEY)
        if not key:
            return False, "OPENROUTER_API_KEY is not configured"
        return True, None

    if provider == "anthropic":
        key = _eff("AI_API_KEY", settings.ANTHROPIC_API_KEY)
        if not key:
            return False, "ANTHROPIC_API_KEY is not configured"
        return True, None

    if provider == "openai":
        key = _eff("AI_API_KEY", settings.OPENAI_API_KEY)
        if not key:
            return False, "OPENAI_API_KEY is not configured"
        return True, None

    if provider == "deepseek":
        key = _eff("AI_API_KEY", settings.DEEPSEEK_API_KEY)
        if not key:
            return False, "DEEPSEEK_API_KEY is not configured"
        return True, None

    if provider == "kimi":
        key = _eff("AI_API_KEY", settings.KIMI_API_KEY)
        if not key:
            return False, "KIMI_API_KEY is not configured"
        return True, None

    if provider == "glm":
        key = _eff("AI_API_KEY", settings.GLM_API_KEY)
        if not key:
            return False, "GLM_API_KEY is not configured"
        return True, None

    return False, f"Unknown AI_PROVIDER: {provider!r}"


def chat(messages: list[dict[str, str]], system: str | None = None,
         model: str | None = None) -> str | None:
    """Send a chat completion request to the configured provider.

    `model` overrides the configured chat model for this one request, which is
    how the assistant lets a user pick a different local model on the fly.
    Returns the assistant's reply text, or None on error.
    """
    settings = get_settings()
    provider = _eff("AI_PROVIDER", settings.AI_PROVIDER).lower()

    if provider == "ollama":
        return _chat_ollama(messages, system, settings, model=model)

    if provider in ("openrouter", "openai", "deepseek", "kimi", "glm"):
        return _chat_openai_compat(messages, system, settings, provider, model=model)

    if provider == "anthropic":
        return _chat_anthropic(messages, system, settings, model=model)

    return None


def list_models() -> list[dict[str, Any]]:
    """Models the provider can currently run (local Ollama: pulled models)."""
    settings = get_settings()
    provider = _eff("AI_PROVIDER", settings.AI_PROVIDER).lower()
    active = _eff("AI_CHAT_MODEL", settings.AI_CHAT_MODEL)
    if provider != "ollama":
        return [{"name": active, "active": True, "size": None}]
    base = _eff("AI_BASE_URL", settings.AI_BASE_URL).rstrip("/")
    data = _get(f"{base}/api/tags")
    if not data:
        return []
    out: list[dict[str, Any]] = []
    for m in data.get("models", []):
        name = m.get("name")
        if not name:
            continue
        out.append({
            "name": name,
            "active": name == active,
            "size": m.get("size"),
            "family": (m.get("details") or {}).get("family"),
            "params": (m.get("details") or {}).get("parameter_size"),
        })
    out.sort(key=lambda m: (not m["active"], m["name"]))
    return out


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _chat_ollama(
    messages: list[dict[str, str]],
    system: str | None,
    settings: Any,
    model: str | None = None,
) -> str | None:
    base = _eff("AI_BASE_URL", settings.AI_BASE_URL).rstrip("/")
    model = model or _eff("AI_CHAT_MODEL", settings.AI_CHAT_MODEL)
    # Ollama defaults to a 2048-token window, which is smaller than the
    # assistant's live-context block - it then rejects the request with
    # HTTP 400 and the chat looks empty. Always ask for an explicit window.
    num_ctx = int(getattr(settings, "AI_NUM_CTX", 8192) or 8192)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
        "options": {"num_ctx": num_ctx},
    }
    if system:
        payload["system"] = system
    response = _post(f"{base}/api/chat", payload)
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
    provider: str,
    model: str | None = None,
) -> str | None:
    """OpenAI-compatible chat completions (OpenRouter, OpenAI, DeepSeek, Kimi, GLM).

    Reads runtime overrides so admin-saved API keys and models take effect.
    """
    chat_model = model or _eff("AI_CHAT_MODEL", settings.AI_CHAT_MODEL)

    provider_config = {
        "openrouter": (
            "https://openrouter.ai/api/v1/chat/completions",
            _eff("OPENROUTER_API_KEY", settings.OPENROUTER_API_KEY),
            chat_model or "nvidia/nemotron-3-ultra-550b-a55b:free",
        ),
        "openai": (
            "https://api.openai.com/v1/chat/completions",
            _eff("AI_API_KEY", settings.OPENAI_API_KEY),
            chat_model or "gpt-4o-mini",
        ),
        "deepseek": (
            "https://api.deepseek.com/v1/chat/completions",
            _eff("AI_API_KEY", settings.DEEPSEEK_API_KEY),
            chat_model or "deepseek-chat",
        ),
        "kimi": (
            "https://api.moonshot.cn/v1/chat/completions",
            _eff("AI_API_KEY", settings.KIMI_API_KEY),
            chat_model or "moonshot-v1-8k",
        ),
        "glm": (
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            _eff("AI_API_KEY", settings.GLM_API_KEY),
            chat_model or "glm-4",
        ),
    }
    url, api_key, model = provider_config[provider]

    all_messages: list[dict[str, str]] = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend({"role": m["role"], "content": m["content"]} for m in messages)

    payload = {"model": model, "messages": all_messages}
    headers = {"Authorization": f"Bearer {api_key}"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://ihp-platform.kaust.edu.sa"
        headers["X-Title"] = "IHP Design and Construction Platform"

    response = _post(url, payload, headers)
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
) -> str | None:
    """Anthropic Messages API."""
    url = "https://api.anthropic.com/v1/messages"
    model = model or _eff("AI_CHAT_MODEL", settings.AI_CHAT_MODEL) or "claude-3-5-haiku-20241022"
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
    }
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": _eff("AI_API_KEY", settings.ANTHROPIC_API_KEY),
        "anthropic-version": "2023-06-01",
    }
    response = _post(url, payload, headers)
    if response is None:
        return None
    try:
        return response["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None


def embed_many(texts: list[str], batch_size: int = 8) -> list[list[float] | None]:
    """Embed several texts, batched. Returns one entry per input (None on failure).

    Uses Ollama's current /api/embed endpoint (which takes a list and is much
    faster than one call per chunk) and falls back to the legacy single-input
    /api/embeddings endpoint on older servers.
    """
    results: list[list[float] | None] = [None] * len(texts)
    if not texts:
        return results
    settings = get_settings()
    provider = _eff("AI_PROVIDER", settings.AI_PROVIDER)
    if provider.lower() != "ollama":
        return results
    base = _eff("AI_BASE_URL", settings.AI_BASE_URL).rstrip("/")
    embed_model = _eff("AI_EMBED_MODEL", settings.AI_EMBED_MODEL)

    for start in range(0, len(texts), max(1, batch_size)):
        window = texts[start:start + batch_size]
        response = _post(
            f"{base}/api/embed", {"model": embed_model, "input": window}
        )
        vectors = (response or {}).get("embeddings")
        if isinstance(vectors, list) and len(vectors) == len(window):
            for offset, vector in enumerate(vectors):
                if isinstance(vector, list) and vector:
                    results[start + offset] = vector
            continue
        # Legacy server: one request per text.
        for offset, text in enumerate(window):
            legacy = _post(
                f"{base}/api/embeddings", {"model": embed_model, "prompt": text}
            )
            vector = (legacy or {}).get("embedding")
            if isinstance(vector, list) and vector:
                results[start + offset] = vector
    return results


def embed(text: str) -> list[float] | None:
    """Return an embedding vector for the given text, or None if unavailable."""
    if not (text or "").strip():
        return None
    return embed_many([text])[0]
