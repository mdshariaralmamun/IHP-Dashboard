"""Catalogue of LLM providers the platform can talk to.

Almost every vendor on the market exposes an OpenAI-compatible
\`POST {base}/chat/completions\` endpoint, so instead of one hardcoded branch per
vendor the platform keeps this table and routes everything through the shared
OpenAI-compatible client. Adding a provider is one entry here.

Kinds:
  * "ollama"    - local Ollama (\`/api/chat\`, \`/api/tags\`, native embeddings)
  * "openai"    - any OpenAI-compatible \`/chat/completions\` (cloud or local)
  * "azure"     - Azure OpenAI (\`api-key\` header + \`api-version\` query)
  * "anthropic" - Anthropic Messages API

Keys are resolved in this order, so an admin can paste a key in Settings
without touching .env:
  1. runtime override \`AI_KEY_<PROVIDER>\` (Settings UI / settings.json)
  2. the provider's environment variable (settings.ENV_KEY)
  3. runtime override \`AI_API_KEY\` / env \`AI_API_KEY\` (the generic slot)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    kind: str
    base_url: str = ""
    env_key: str = ""
    default_models: tuple[str, ...] = ()
    docs: str = ""
    local: bool = False
    #: Some vendors need an extra header (Azure) or account id in the URL.
    key_header: str = "Authorization"
    notes: str = ""


_CATALOG: tuple[ProviderSpec, ...] = (
    # ---------------------------------------------------------------- local
    ProviderSpec(
        id="ollama", label="Ollama (this server)", kind="ollama",
        base_url="http://localhost:11434", local=True,
        default_models=("llama3.2:3b", "llama3.2:1b"),
        docs="https://ollama.com/library",
        notes="Local models; also provides the embeddings used by retrieval.",
    ),
    ProviderSpec(
        id="lmstudio", label="LM Studio", kind="openai",
        base_url="http://localhost:1234/v1", env_key="LMSTUDIO_API_KEY", local=True,
        docs="https://lmstudio.ai/docs/api/openai-api",
    ),
    ProviderSpec(
        id="vllm", label="vLLM", kind="openai",
        base_url="http://localhost:8000/v1", env_key="VLLM_API_KEY", local=True,
        docs="https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html",
    ),
    ProviderSpec(
        id="llamacpp", label="llama.cpp server", kind="openai",
        base_url="http://localhost:8080/v1", env_key="LLAMACPP_API_KEY", local=True,
        docs="https://github.com/ggml-org/llama.cpp/tree/master/tools/server",
    ),
    ProviderSpec(
        id="localai", label="LocalAI", kind="openai",
        base_url="http://localhost:8080/v1", env_key="LOCALAI_API_KEY", local=True,
        docs="https://localai.io/basics/open_ai_examples/",
    ),
    ProviderSpec(
        id="jan", label="Jan", kind="openai",
        base_url="http://localhost:1337/v1", env_key="JAN_API_KEY", local=True,
        docs="https://jan.ai/docs/api",
    ),
    ProviderSpec(
        id="custom", label="Custom OpenAI-compatible endpoint", kind="openai",
        env_key="CUSTOM_AI_API_KEY", local=True,
        docs="https://platform.openai.com/docs/api-reference/chat",
        notes="Set the base URL (ending in /v1) and model in Settings.",
    ),

    # -------------------------------------------------------------- frontier
    ProviderSpec(
        id="openai", label="OpenAI", kind="openai",
        base_url="https://api.openai.com/v1", env_key="OPENAI_API_KEY",
        default_models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"),
        docs="https://platform.openai.com/docs/api-reference/chat",
    ),
    ProviderSpec(
        id="azure-openai", label="Azure OpenAI", kind="azure",
        env_key="AZURE_OPENAI_API_KEY",
        default_models=("gpt-4o-mini",),
        docs="https://learn.microsoft.com/azure/ai-services/openai/",
        key_header="api-key",
        notes="Base URL: https://<resource>.openai.azure.com/openai/deployments/<deployment> (api-version=2024-08-01-preview).",
    ),
    ProviderSpec(
        id="anthropic", label="Anthropic Claude", kind="anthropic",
        base_url="https://api.anthropic.com/v1/messages", env_key="ANTHROPIC_API_KEY",
        default_models=("claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-sonnet-4-5"),
        docs="https://docs.anthropic.com/en/api/messages",
    ),
    ProviderSpec(
        id="google-gemini", label="Google Gemini", kind="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        env_key="GEMINI_API_KEY",
        default_models=("gemini-2.0-flash", "gemini-1.5-pro", "gemini-2.5-pro"),
        docs="https://ai.google.dev/gemini-api/docs/openai",
    ),
    ProviderSpec(
        id="xai", label="xAI Grok", kind="openai",
        base_url="https://api.x.ai/v1", env_key="XAI_API_KEY",
        default_models=("grok-2-latest", "grok-beta"),
        docs="https://docs.x.ai/docs/api-reference",
    ),
    ProviderSpec(
        id="mistral", label="Mistral AI", kind="openai",
        base_url="https://api.mistral.ai/v1", env_key="MISTRAL_API_KEY",
        default_models=("mistral-small-latest", "mistral-large-latest", "open-mistral-nemo"),
        docs="https://docs.mistral.ai/api/",
    ),
    ProviderSpec(
        id="cohere", label="Cohere", kind="openai",
        base_url="https://api.cohere.ai/compatibility/v1", env_key="COHERE_API_KEY",
        default_models=("command-r-plus-08-2024", "command-r-08-2024"),
        docs="https://docs.cohere.com/v2/docs/compatibility-api",
    ),

    # ------------------------------------------------------------------ Asia
    ProviderSpec(
        id="deepseek", label="DeepSeek", kind="openai",
        base_url="https://api.deepseek.com/v1", env_key="DEEPSEEK_API_KEY",
        default_models=("deepseek-chat", "deepseek-reasoner"),
        docs="https://api-docs.deepseek.com/",
    ),
    ProviderSpec(
        id="moonshot", label="Moonshot / Kimi", kind="openai",
        base_url="https://api.moonshot.cn/v1", env_key="KIMI_API_KEY",
        default_models=("moonshot-v1-8k", "moonshot-v1-32k", "kimi-k2-0711-preview"),
        docs="https://platform.moonshot.cn/docs/api/chat",
    ),
    ProviderSpec(
        id="zhipu", label="Zhipu GLM", kind="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4", env_key="GLM_API_KEY",
        default_models=("glm-4-flash", "glm-4-plus", "glm-4"),
        docs="https://docs.bigmodel.cn/",
    ),
    ProviderSpec(
        id="qwen", label="Alibaba Qwen (DashScope)", kind="openai",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        env_key="DASHSCOPE_API_KEY",
        default_models=("qwen-plus", "qwen-max", "qwen2.5-72b-instruct"),
        docs="https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope",
    ),
    ProviderSpec(
        id="minimax", label="MiniMax", kind="openai",
        base_url="https://api.minimax.chat/v1", env_key="MINIMAX_API_KEY",
        default_models=("MiniMax-Text-01", "abab6.5s-chat"),
        docs="https://www.minimax.io/platform/document",
    ),
    ProviderSpec(
        id="yi", label="01.AI Yi", kind="openai",
        base_url="https://api.lingyiwanwu.com/v1", env_key="YI_API_KEY",
        default_models=("yi-lightning", "yi-large"),
        docs="https://platform.lingyiwanwu.com/docs",
    ),
    ProviderSpec(
        id="siliconflow", label="SiliconFlow", kind="openai",
        base_url="https://api.siliconflow.cn/v1", env_key="SILICONFLOW_API_KEY",
        default_models=("Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3"),
        docs="https://docs.siliconflow.cn/",
    ),
    ProviderSpec(
        id="upstage", label="Upstage Solar", kind="openai",
        base_url="https://api.upstage.ai/v1/solar", env_key="UPSTAGE_API_KEY",
        default_models=("solar-pro", "solar-mini"),
        docs="https://developers.upstage.ai/docs/apis/chat",
    ),

    # ------------------------------------------------------------ aggregators
    ProviderSpec(
        id="openrouter", label="OpenRouter", kind="openai",
        base_url="https://openrouter.ai/api/v1", env_key="OPENROUTER_API_KEY",
        default_models=(
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "deepseek/deepseek-chat",
            "anthropic/claude-3.5-sonnet",
        ),
        docs="https://openrouter.ai/docs",
    ),
    ProviderSpec(
        id="groq", label="Groq", kind="openai",
        base_url="https://api.groq.com/openai/v1", env_key="GROQ_API_KEY",
        default_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"),
        docs="https://console.groq.com/docs/openai",
    ),
    ProviderSpec(
        id="together", label="Together AI", kind="openai",
        base_url="https://api.together.xyz/v1", env_key="TOGETHER_API_KEY",
        default_models=("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"),
        docs="https://docs.together.ai/docs/openai-api-compatibility",
    ),
    ProviderSpec(
        id="fireworks", label="Fireworks AI", kind="openai",
        base_url="https://api.fireworks.ai/inference/v1", env_key="FIREWORKS_API_KEY",
        default_models=("accounts/fireworks/models/llama-v3p3-70b-instruct",),
        docs="https://docs.fireworks.ai/api-reference/introduction",
    ),
    ProviderSpec(
        id="cerebras", label="Cerebras", kind="openai",
        base_url="https://api.cerebras.ai/v1", env_key="CEREBRAS_API_KEY",
        default_models=("llama3.3-70b", "llama3.1-8b"),
        docs="https://inference-docs.cerebras.ai/",
    ),
    ProviderSpec(
        id="deepinfra", label="DeepInfra", kind="openai",
        base_url="https://api.deepinfra.com/v1/openai", env_key="DEEPINFRA_API_KEY",
        default_models=("meta-llama/Meta-Llama-3.1-8B-Instruct",),
        docs="https://deepinfra.com/docs/openai_api",
    ),
    ProviderSpec(
        id="novita", label="Novita AI", kind="openai",
        base_url="https://api.novita.ai/v3/openai", env_key="NOVITA_API_KEY",
        default_models=("meta-llama/llama-3.1-8b-instruct",),
        docs="https://novita.ai/docs/api-reference/model-apis-llm",
    ),
    ProviderSpec(
        id="nebius", label="Nebius AI Studio", kind="openai",
        base_url="https://api.studio.nebius.ai/v1", env_key="NEBIUS_API_KEY",
        default_models=("meta-llama/Meta-Llama-3.1-8B-Instruct",),
        docs="https://docs.nebius.com/studio/inference/api",
    ),
    ProviderSpec(
        id="sambanova", label="SambaNova", kind="openai",
        base_url="https://api.sambanova.ai/v1", env_key="SAMBANOVA_API_KEY",
        default_models=("Meta-Llama-3.3-70B-Instruct", "Meta-Llama-3.1-8B-Instruct"),
        docs="https://docs.sambanova.ai/cloud/docs/get-started/overview",
    ),
    ProviderSpec(
        id="hyperbolic", label="Hyperbolic", kind="openai",
        base_url="https://api.hyperbolic.xyz/v1", env_key="HYPERBOLIC_API_KEY",
        default_models=("meta-llama/Llama-3.3-70B-Instruct",),
        docs="https://docs.hyperbolic.xyz/docs/getting-started",
    ),
    ProviderSpec(
        id="perplexity", label="Perplexity Sonar", kind="openai",
        base_url="https://api.perplexity.ai", env_key="PERPLEXITY_API_KEY",
        default_models=("sonar", "sonar-pro"),
        docs="https://docs.perplexity.ai/api-reference/chat-completions",
    ),
    ProviderSpec(
        id="nvidia", label="NVIDIA NIM", kind="openai",
        base_url="https://integrate.api.nvidia.com/v1", env_key="NVIDIA_API_KEY",
        default_models=("meta/llama-3.1-8b-instruct", "meta/llama-3.3-70b-instruct"),
        docs="https://docs.nvidia.com/nim/",
    ),
    ProviderSpec(
        id="github-models", label="GitHub Models", kind="openai",
        base_url="https://models.inference.ai.azure.com", env_key="GITHUB_MODELS_TOKEN",
        default_models=("gpt-4o-mini", "Phi-3.5-MoE-instruct"),
        docs="https://docs.github.com/en/github-models",
    ),
    ProviderSpec(
        id="cloudflare", label="Cloudflare Workers AI", kind="openai",
        env_key="CLOUDFLARE_AI_API_KEY",
        default_models=("@cf/meta/llama-3.1-8b-instruct",),
        docs="https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/",
        notes="Base URL: https://api.cloudflare.com/client/v4/accounts/<account_id>/ai/v1",
    ),
)

CATALOG: dict[str, ProviderSpec] = {spec.id: spec for spec in _CATALOG}

#: Older ids kept working so existing installs do not break.
ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "kimi": "moonshot",
    "glm": "zhipu",
    "gemini": "google-gemini",
    "google": "google-gemini",
    "groq-cloud": "groq",
    "azure": "azure-openai",
    "openai-compatible": "custom",
    "compatible": "custom",
}


def resolve(provider_id: str | None) -> ProviderSpec | None:
    """Look up a provider, following aliases."""
    if not provider_id:
        return None
    key = provider_id.strip().lower()
    key = ALIASES.get(key, key)
    return CATALOG.get(key)


def all_specs() -> list[ProviderSpec]:
    return list(_CATALOG)


def public_list() -> list[dict[str, object]]:
    """Catalogue as JSON for the Settings UI."""
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "kind": spec.kind,
            "base_url": spec.base_url,
            "default_models": list(spec.default_models),
            "docs": spec.docs,
            "local": spec.local,
            "env_key": spec.env_key,
            "notes": spec.notes,
        }
        for spec in _CATALOG
    ]
