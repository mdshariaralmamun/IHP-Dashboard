"""Settings are env-driven (pydantic-settings).

All settings can be overridden via environment variables or a `.env` file
placed in the working directory (backend/). No env prefix is used.
"""

import json
from functools import lru_cache
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Demo markup rates used by later budget/BOQ stages. Parsed from JSON.
DEFAULT_MARKUP_RATES = (
    '{"overhead": 0.10, "contingency": 0.15, "profit": 0.05, "escalation": 0.03}'
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database. Production example:
    #   postgresql+psycopg://ihp:<password>@db:5432/ihp
    DATABASE_URL: str = "sqlite:///./dev.db"

    # Auth
    SECRET_KEY: str = "dev-secret-key-change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Seed admin (created on startup when the users table is empty)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # Filesystem storage (uploaded attachments + generated documents)
    DATA_DIR: str = "./data"
    TEMPLATES_DIR: str = "./templates"

    # Planner's materials price master (markdown table, updated frequently;
    # synced into master_pricing via services/price_master.py)
    PRICE_MASTER_PATH: str = (
        r"E:\ENGINEERING_DATA\trackers\IHP - Cost Estimates file -1.md"
    )
    # Dated tracker versions live here; the system always resolves the
    # newest _DDMMYYYY file (services/tracker_files.py)
    TRACKERS_DIR: str = r"E:\ENGINEERING_DATA\trackers"
    # The Planner drops PR-request PDF copies here for bulk loading
    PR_REQUEST_DIR: str = r"E:\ENGINEERING_DATA\trackers\PR Request Copy"

    # SMTP (optional). If SMTP_HOST is unset, emails are draft-only.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None

    # JSON string with markup rates, parsed for later stages (SOW/BOQ).
    BUDGET_MARKUP_RATES: str = DEFAULT_MARKUP_RATES

    # AI provider configuration.
    # The AI layer can route to different providers based on AI_PROVIDER.
    # Supported values: "ollama", "openrouter", "anthropic", "openai", "deepseek", "kimi", "glm", "claude"
    AI_PROVIDER: str = "ollama"

    # Ollama-compatible local instance (used when AI_PROVIDER="ollama").
    AI_BASE_URL: str = "http://localhost:11434"
    AI_CHAT_MODEL: str = "llama3.2:3b"
    AI_EMBED_MODEL: str = "nomic-embed-text"
    # Seconds to wait for one chat completion. CPU-only hosts need minutes for
    # a long prompt (and more while an embedding job shares the CPU).
    AI_CHAT_TIMEOUT: int = 600
    # Cap the generated answer so one request cannot outlive the proxy timeout
    # (~100 s at Cloudflare). 512 tokens is a few paragraphs.
    AI_NUM_PREDICT: int = 512
    # Context window sent to Ollama. Ollama's own default is only 2048 tokens,
    # which is smaller than the assistant's live-context block, so requests
    # came back as HTTP 400 "exceeds context" and the chat showed nothing.
    AI_NUM_CTX: int = 8192
    # Optional bearer key for the base URL above (needed only when the
    # endpoint is hosted; local Ollama ignores it). Admins can override
    # this at runtime via /api/admin/settings.
    AI_API_KEY: str = ""

    # OpenRouter (used when AI_PROVIDER="openrouter").
    OPENROUTER_API_KEY: str = ""

    # Anthropic (used when AI_PROVIDER="anthropic").
    ANTHROPIC_API_KEY: str = ""

    # OpenAI (used when AI_PROVIDER="openai").
    OPENAI_API_KEY: str = ""

    # DeepSeek (used when AI_PROVIDER="deepseek").
    DEEPSEEK_API_KEY: str = ""

    # Kimi K3 / Moonshot (used when AI_PROVIDER="kimi").
    KIMI_API_KEY: str = ""

    # GLM (used when AI_PROVIDER="glm").
    GLM_API_KEY: str = ""

    # Claude API (used when AI_PROVIDER="claude").
    CLAUDE_API_KEY: str = ""

    # Force local embedder regardless of API keys (Ollama).
    AI_FORCE_LOCAL_EMBEDDER: int = 0

    @model_validator(mode="before")
    @classmethod
    def _blank_env_is_unset(cls, data: Any) -> Any:
        """Treat an empty environment variable as "not set".

        Docker Compose passes optional variables through as empty strings
        (``SMTP_PORT: ${SMTP_PORT:-}``), and pydantic would then fail to parse
        "" as an int and crash the whole app at import time. Dropping blanks
        lets each field fall back to its declared default, so a deployment
        without SMTP (or any other optional setting) starts cleanly.
        """
        if isinstance(data, dict):
            return {
                k: v
                for k, v in data.items()
                if not (isinstance(v, str) and v.strip() == "")
            }
        return data

    @property
    def budget_markup_rates(self) -> dict:
        """Parsed markup rates; falls back to demo rates on bad JSON."""
        try:
            rates = json.loads(self.BUDGET_MARKUP_RATES)
            return rates if isinstance(rates, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST)


@lru_cache
def get_settings() -> Settings:
    return Settings()
