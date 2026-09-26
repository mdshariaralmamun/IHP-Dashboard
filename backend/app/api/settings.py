"""Settings endpoints (admin): the platform control panel.

Every tunable parameter of the platform is visible here and — where it makes
sense — editable at runtime. Values come from environment variables /
backend/.env and admins can override individual keys; overrides are stored
via `services/runtime_settings` (data/settings.json) and merged on top of
the env-driven Settings at request time.

Master-admin only: every endpoint requires the `users.manage` capability.
Trade and viewer roles get 403 here and never see the page in the UI.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..ai import provider as ai_provider
from ..ai import providers_catalog
from ..core.config import get_settings
from ..core.rbac import CAP_USERS_MANAGE, require_capability
from ..models import User
from ..services import runtime_settings

router = APIRouter(prefix="/admin/settings", tags=["admin_settings"])

# Whitelist of override-able settings. Anything else gets a 400.
OVERRIDABLE_KEYS = {
    # AI provider
    "AI_PROVIDER",
    "AI_BASE_URL",
    "AI_CHAT_MODEL",
    "AI_EMBED_MODEL",
    "AI_API_KEY",
    "OPENROUTER_API_KEY",
    # Embeddings can stay local while chat uses a cloud vendor
    "AI_EMBED_PROVIDER",
    "AI_EMBED_BASE_URL",
    # Stashed so switching the chat provider away from Ollama does not break
    # local embeddings
    "AI_BASE_URL_OLLAMA",
    "AI_CHAT_MODEL_OLLAMA",
    # Project variables (used by budget / BOQ generation)
    "VAT_RATE",
    "USD_SAR_RATE",
    "DEFAULT_CURRENCY",
    # Agent memory (archive ingestion root)
    "ARCHIVE_PATH",
    # Materials price master (synced into master_pricing)
    "PRICE_MASTER_PATH",
    # Tracker file resolution + PR-request PDF drop folder
    "TRACKERS_DIR",
    "PR_REQUEST_DIR",
    # Appearance
    "THEME",
}

#: Suggested archive roots offered by the UI when present on this machine.
_ARCHIVE_SUGGESTIONS = [
    r"E:\ENGINEERING_DATA\01_RAW_ARCHIVE",
    r"E:\ENGINEERING_DATA\archives",
    r"D:\Archive",
]


class SettingsOut(BaseModel):
    # AI provider
    ai_provider: str
    ai_provider_label: str
    ai_provider_kind: str
    ai_provider_docs: str
    ai_provider_local: bool
    ai_base_url: str
    ai_chat_model: str
    ai_embed_model: str
    ai_embed_provider: str
    ai_api_key_present: bool
    ai_key_env: str
    # Project variables
    vat_rate: float
    usd_sar_rate: float
    default_currency: str
    # Email (SMTP) — read-only view of env config
    smtp_configured: bool
    smtp_from: str | None
    smtp_host: str | None
    # Agent memory
    archive_path: str
    archive_suggestions: list[str]
    # Materials price master
    price_master_path: str
    # Tracker file resolution
    trackers_dir: str
    pr_request_dir: str
    # Appearance
    theme: str
    # Raw override map + env baseline for the diff view
    overrides: dict[str, Any]
    env: dict[str, str]


class SettingsUpdate(BaseModel):
    ai_provider: str | None = None
    ai_base_url: str | None = None
    ai_chat_model: str | None = None
    ai_embed_model: str | None = None
    ai_embed_provider: str | None = None
    ai_api_key: str | None = None
    openrouter_api_key: str | None = None
    vat_rate: float | None = None
    usd_sar_rate: float | None = None
    default_currency: str | None = None
    archive_path: str | None = None
    price_master_path: str | None = None
    trackers_dir: str | None = None
    pr_request_dir: str | None = None
    theme: str | None = None
    clear: list[str] | None = None  # keys to revert to env


#: Per-provider overrides written by the provider picker, e.g. AI_KEY_DEEPSEEK.
_PER_PROVIDER_KEY = re.compile(r"^AI_(KEY|BASE_URL|CHAT_MODEL)_[A-Z0-9-]+$")


def _is_overridable(key: str) -> bool:
    return key in OVERRIDABLE_KEYS or bool(_PER_PROVIDER_KEY.match(key))


def _archive_default() -> str:
    for candidate in _ARCHIVE_SUGGESTIONS:
        if Path(candidate).is_dir():
            return candidate
    return ""


def _settings_out() -> SettingsOut:
    s = get_settings()
    overrides = runtime_settings.read_overrides()
    selected = ai_provider.effective_provider(s)
    spec = providers_catalog.resolve(selected)
    return SettingsOut(
        ai_provider=selected,
        ai_provider_label=spec.label if spec else selected,
        ai_provider_kind=spec.kind if spec else "",
        ai_provider_docs=spec.docs if spec else "",
        ai_provider_local=bool(spec.local) if spec else False,
        ai_base_url=ai_provider.base_url_for(spec, s) if spec else s.AI_BASE_URL,
        ai_chat_model=ai_provider.default_model_for(spec, s) if spec else "",
        ai_embed_model=overrides.get("AI_EMBED_MODEL", s.AI_EMBED_MODEL),
        ai_embed_provider=overrides.get("AI_EMBED_PROVIDER", "ollama"),
        ai_api_key_present=bool(ai_provider.api_key_for(spec, s)) if spec else False,
        ai_key_env=spec.env_key if spec else "",
        vat_rate=float(overrides.get("VAT_RATE") or 0.15),
        usd_sar_rate=float(overrides.get("USD_SAR_RATE") or 3.75),
        default_currency=overrides.get("DEFAULT_CURRENCY") or "SAR",
        smtp_configured=bool(s.SMTP_HOST),
        smtp_from=s.SMTP_FROM,
        smtp_host=s.SMTP_HOST,
        archive_path=overrides.get("ARCHIVE_PATH") or _archive_default(),
        archive_suggestions=[p for p in _ARCHIVE_SUGGESTIONS if Path(p).is_dir()],
        price_master_path=overrides.get("PRICE_MASTER_PATH", s.PRICE_MASTER_PATH),
        trackers_dir=overrides.get("TRACKERS_DIR", s.TRACKERS_DIR),
        pr_request_dir=overrides.get("PR_REQUEST_DIR", s.PR_REQUEST_DIR),
        theme=overrides.get("THEME", "kaust"),
        overrides=overrides,
        env={
            "AI_BASE_URL": s.AI_BASE_URL,
            "AI_CHAT_MODEL": s.AI_CHAT_MODEL,
            "AI_EMBED_MODEL": s.AI_EMBED_MODEL,
        },
    )


@router.get("", response_model=SettingsOut)
def get_settings_endpoint(
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    return _settings_out()


@router.patch("", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    overrides = runtime_settings.read_overrides()

    if body.clear:
        for key in body.clear:
            if not _is_overridable(key):
                raise HTTPException(400, f"Cannot clear unknown key {key!r}")
            overrides.pop(key, None)

    settings = get_settings()
    updates: dict[str, Any] = {}

    # Which provider are these values for? The one being switched to, else the
    # one already selected.
    active_id = ai_provider.effective_provider(settings)
    if body.ai_provider is not None:
        spec = providers_catalog.resolve(body.ai_provider)
        if spec is None:
            available = ", ".join(s.id for s in providers_catalog.all_specs())
            raise HTTPException(400, f"Unknown ai_provider. Available: {available}")

        # Remember the Ollama endpoint/model before leaving it, so retrieval
        # (which embeds locally) keeps working after the switch.
        if spec.id != "ollama":
            current_base = overrides.get("AI_BASE_URL", settings.AI_BASE_URL)
            if ":11434" in str(current_base) and not overrides.get("AI_BASE_URL_OLLAMA"):
                updates["AI_BASE_URL_OLLAMA"] = current_base
            current_model = overrides.get("AI_CHAT_MODEL", settings.AI_CHAT_MODEL)
            if active_id == "ollama" and current_model and not overrides.get("AI_CHAT_MODEL_OLLAMA"):
                updates["AI_CHAT_MODEL_OLLAMA"] = current_model

        updates["AI_PROVIDER"] = spec.id

        # Back-compat: keep the legacy OpenRouter slot in step.
        if spec.id == "openrouter":
            old_key = overrides.get("AI_API_KEY", "")
            if old_key and not overrides.get("OPENROUTER_API_KEY"):
                updates["OPENROUTER_API_KEY"] = old_key
                overrides.pop("AI_API_KEY", None)
        active_id = spec.id

    spec = providers_catalog.resolve(active_id)
    provider_key = (spec.id if spec else active_id).upper()

    # Per-provider keys (`AI_*_<PROVIDER>`) are the source of truth, and the
    # legacy generic keys are mirrored so old .env files and scripts keep
    # working. `default_model_for`/\`api_key_for\` read the per-provider slot first.
    if body.ai_base_url is not None:
        updates[f"AI_BASE_URL_{provider_key}"] = body.ai_base_url.strip()
        updates["AI_BASE_URL"] = body.ai_base_url.strip()
    if body.ai_chat_model is not None:
        updates[f"AI_CHAT_MODEL_{provider_key}"] = body.ai_chat_model.strip()
        updates["AI_CHAT_MODEL"] = body.ai_chat_model.strip()
    if body.ai_embed_model is not None:
        updates["AI_EMBED_MODEL"] = body.ai_embed_model.strip()
    if body.ai_embed_provider is not None:
        embed_spec = providers_catalog.resolve(body.ai_embed_provider)
        if embed_spec is None:
            raise HTTPException(400, f"Unknown ai_embed_provider {body.ai_embed_provider!r}")
        updates["AI_EMBED_PROVIDER"] = embed_spec.id
    if body.ai_api_key is not None:
        updates[f"AI_KEY_{provider_key}"] = body.ai_api_key.strip()
        updates["AI_API_KEY"] = body.ai_api_key.strip()
        if provider_key == "OPENROUTER":
            updates["OPENROUTER_API_KEY"] = body.ai_api_key.strip()
    if body.openrouter_api_key is not None:
        updates["OPENROUTER_API_KEY"] = body.openrouter_api_key.strip()
        updates["AI_KEY_OPENROUTER"] = body.openrouter_api_key.strip()
    if body.vat_rate is not None:
        if not 0 <= body.vat_rate <= 1:
            raise HTTPException(400, "vat_rate must be between 0 and 1 (e.g. 0.15 for 15%)")
        updates["VAT_RATE"] = body.vat_rate
    if body.usd_sar_rate is not None:
        if body.usd_sar_rate <= 0:
            raise HTTPException(400, "usd_sar_rate must be positive (e.g. 3.75)")
        updates["USD_SAR_RATE"] = body.usd_sar_rate
    if body.default_currency is not None:
        updates["DEFAULT_CURRENCY"] = body.default_currency.strip().upper()[:8]
    if body.archive_path is not None:
        # Allow saving a path that doesn't exist yet (drive may be attached
        # later) but never a file.
        if body.archive_path.strip() and Path(body.archive_path.strip()).is_file():
            raise HTTPException(400, "archive_path must be a directory, not a file")
        updates["ARCHIVE_PATH"] = body.archive_path.strip()
    if body.price_master_path is not None:
        updates["PRICE_MASTER_PATH"] = body.price_master_path.strip()
    if body.trackers_dir is not None:
        # Allow saving a path that doesn't exist yet (drive may be attached
        # later) but never a file.
        if body.trackers_dir.strip() and Path(body.trackers_dir.strip()).is_file():
            raise HTTPException(400, "trackers_dir must be a directory, not a file")
        updates["TRACKERS_DIR"] = body.trackers_dir.strip()
    if body.pr_request_dir is not None:
        if body.pr_request_dir.strip() and Path(body.pr_request_dir.strip()).is_file():
            raise HTTPException(400, "pr_request_dir must be a directory, not a file")
        updates["PR_REQUEST_DIR"] = body.pr_request_dir.strip()
    if body.theme is not None:
        if body.theme not in {"kaust", "kaust-dark"}:
            raise HTTPException(400, "theme must be 'kaust' or 'kaust-dark'")
        overrides["THEME"] = body.theme

    overrides.update(updates)
    runtime_settings.write_overrides(overrides)
    return _settings_out()


@router.get("/tracker-files")
def tracker_files_status(
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Which tracker files the system points at RIGHT NOW — always the
    newest _DDMMYYYY-dated version — plus the PR-request PDF drop folder
    (the Planner drops copies there for bulk loading)."""
    from ..services import tracker_files

    s = get_settings()
    overrides = runtime_settings.read_overrides()
    return tracker_files.tracker_status(
        overrides.get("TRACKERS_DIR") or s.TRACKERS_DIR,
        overrides.get("PR_REQUEST_DIR") or s.PR_REQUEST_DIR,
    )


@router.post("/ai/test")
def test_ai_connection(
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Make a lightweight request to the configured AI provider to
    confirm it's reachable. Adapts the test to the active provider type.
    """
    s = get_settings()
    overrides = runtime_settings.read_overrides()
    provider = overrides.get("AI_PROVIDER", s.AI_PROVIDER).lower()
    base = overrides.get("AI_BASE_URL", s.AI_BASE_URL).rstrip("/")
    start = time.time()

    try:
        import urllib.error
        import urllib.request

        if provider == "openrouter":
            # OpenRouter: test with a minimal chat completion
            url = "https://openrouter.ai/api/v1/chat/completions"
            api_key = overrides.get("OPENROUTER_API_KEY") or s.OPENROUTER_API_KEY
            if not api_key:
                return {"ok": False, "url": url, "error": "No OpenRouter API key configured.",
                        "hint": "Enter your OpenRouter API key and save before testing."}
            model = overrides.get("AI_CHAT_MODEL", s.AI_CHAT_MODEL) or "nvidia/nemotron-3-ultra-550b-a55b:free"
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "Say hi in one word."}],
                "max_tokens": 5,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {api_key}")
            req.add_header("HTTP-Referer", "https://ihp-platform.kaust.edu.sa")
            req.add_header("X-Title", "IHP Design and Construction Platform")
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode())
                reply = ""
                try:
                    reply = body["choices"][0]["message"]["content"]
                except (KeyError, IndexError):
                    pass
                return {
                    "ok": True,
                    "latency_ms": int((time.time() - start) * 1000),
                    "url": url,
                    "model": model,
                    "reply": reply[:100],
                    "base_url": "https://openrouter.ai/api/v1",
                }

        elif provider in ("openai", "deepseek", "kimi", "glm"):
            # OpenAI-compatible: test with a minimal chat completion
            provider_urls = {
                "openai": "https://api.openai.com/v1/chat/completions",
                "deepseek": "https://api.deepseek.com/v1/chat/completions",
                "kimi": "https://api.moonshot.cn/v1/chat/completions",
                "glm": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            }
            url = provider_urls[provider]
            key_map = {
                "openai": overrides.get("AI_API_KEY") or s.OPENAI_API_KEY,
                "deepseek": overrides.get("AI_API_KEY") or s.DEEPSEEK_API_KEY,
                "kimi": overrides.get("AI_API_KEY") or s.KIMI_API_KEY,
                "glm": overrides.get("AI_API_KEY") or s.GLM_API_KEY,
            }
            api_key = key_map[provider]
            if not api_key:
                return {"ok": False, "url": url, "error": f"No API key configured for {provider}.",
                        "hint": "Enter your API key and save before testing."}
            model = overrides.get("AI_CHAT_MODEL", s.AI_CHAT_MODEL)
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "Say hi in one word."}],
                "max_tokens": 5,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=15) as r:
                body = json.loads(r.read().decode())
                return {
                    "ok": True,
                    "latency_ms": int((time.time() - start) * 1000),
                    "url": url,
                    "model": model,
                    "base_url": url.rsplit("/chat", 1)[0],
                }

        else:
            # Ollama (default): test /api/tags
            url = f"{base}/api/tags"
            req = urllib.request.Request(url)
            api_key = overrides.get("AI_API_KEY") or s.AI_API_KEY
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=5) as r:
                body = json.loads(r.read().decode())
                models = [m.get("name") for m in body.get("models", []) if m.get("name")]
                return {
                    "ok": True,
                    "latency_ms": int((time.time() - start) * 1000),
                    "url": url,
                    "models": models[:20],
                    "base_url": base,
                }

    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()[:300]
        except Exception:
            pass
        return {
            "ok": False,
            "latency_ms": int((time.time() - start) * 1000),
            "url": url if "url" in dir() else "",
            "error": f"HTTP {e.code}: {error_body or e.reason}",
            "hint": "Check the API key and model name. For free OpenRouter models, "
                    "ensure the model ID ends with ':free'.",
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "latency_ms": int((time.time() - start) * 1000),
            "url": url if "url" in dir() else "",
            "error": str(e.reason),
            "hint": "Check the URL. For local Ollama use http://localhost:11434. "
                    "For OpenRouter use https://openrouter.ai/api/v1.",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "url": url if "url" in dir() else "", "error": str(e)}
