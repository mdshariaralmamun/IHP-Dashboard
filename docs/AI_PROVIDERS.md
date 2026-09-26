# AI providers

The live list is `GET /api/ai/providers` (the Settings page renders it) and
`backend/app/ai/providers_catalog.py` holds the definitions - 36 vendors.
Almost every API on the market speaks the OpenAI-compatible
`POST {base}/chat/completions` protocol, so a new vendor is one entry there.

Keys are resolved in this order: `AI_KEY_<PROVIDER>` runtime override (what
the Settings page writes) -> the provider's env variable -> the legacy vendor
slot (e.g. `OPENROUTER_API_KEY`) -> `AI_API_KEY`. Embeddings stay on local
Ollama unless `AI_EMBED_PROVIDER` / `AI_EMBED_BASE_URL` say otherwise, so
moving chat to a cloud vendor never breaks document retrieval.

## Local

Ollama (this server, also the embedder), LM Studio, vLLM, llama.cpp server,
LocalAI, Jan, and "Custom OpenAI-compatible endpoint" for anything else.

## Cloud (OpenAI-compatible unless noted)

OpenAI, Azure OpenAI (api-key header + api-version), Anthropic (native Messages
API), Google Gemini, xAI Grok, Mistral, Cohere, DeepSeek, Moonshot/Kimi, Zhipu
GLM, Alibaba Qwen (DashScope), MiniMax, 01.AI Yi, SiliconFlow, Upstage Solar,
OpenRouter, Groq, Together, Fireworks, Cerebras, DeepInfra, Novita, Nebius,
SambaNova, Hyperbolic, Perplexity Sonar, NVIDIA NIM, GitHub Models, Cloudflare
Workers AI.

Base URLs, env key names and suggested models per vendor: open
`/api/ai/providers` or the Settings page, which shows them next to the picker.

## Per-request override

    curl -s -X POST "$API/api/ai/ask" -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d '{"question":"Which projects are overdue?","provider":"deepseek","model":"deepseek-chat"}'

`POST /api/ai/providers/test` probes a provider (a key/base URL passed in the
body is used for that probe only and never stored).
`GET /api/ai/models?provider_id=...` lists another vendor's models.

## Legacy ids

`claude` -> `anthropic`, `kimi` -> `moonshot`, `glm` -> `zhipu`,
`gemini` -> `google-gemini`, `azure` -> `azure-openai`,
`openai-compatible` -> `custom`.
