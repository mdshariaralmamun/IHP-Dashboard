# Local AI: app data only

Policy: **the assistant answers from IHP platform data only.** That means the
live database (projects, MOM, EAR, SOW, BOQ/MTO, construction, closeout) plus
the documents teams upload to those projects. The external engineering archive
is *not* indexed - it was loaded for a trial and then removed (3,011 documents /
52,743 chunks deleted, mount dropped).

## 1. Short answer

| Goal | What actually works | Where it runs |
| --- | --- | --- |
| Exact numbers, dates, lists, stages | Deterministic answers read straight from the database (\`mode: "live"\`) | VPS |
| "What does the uploaded SOW say?" | Retrieval over the app's own documents, cited by file name | VPS |
| Better wording, summaries, drafts | A larger instruct model (3B) - quality, not facts | VPS (CPU) |
| House style / format | LoRA fine-tune on the exported dataset | **Training PC (RTX 5060 Ti)**, served from the VPS |
| "The model trains itself" | Re-index on upload + 👍/👎 capture + periodic supervised fine-tune + evaluation. Never unsupervised self-training | both |

Fine-tuning cannot make a small model accurate about 262 live projects - it will
still invent numbers. Facts come from the database and from retrieval; style and
format come from fine-tuning.

## 2. What is implemented

**Retrieval** - \`backend/app/ai/retrieval.py\`
* hybrid: keyword overlap (no model) + embedding cosine when the chunk has a
  vector, SQL prefilter, de-duplication; scoped to a project when the question
  is about one.
* \`GET /api/ai/search?q=...\` returns hits and corpus size without a model.

**App documents** - \`backend/app/services/app_documents.py\`
* every attachment uploaded to a project is text-extracted (pdf, docx, xlsx,
  xlsm, msg, txt, md, csv), chunked and stored as corpus chunks scoped to that
  project (\`source="attachment"\`), so answers can cite the real file;
* deleting an attachment deletes its corpus copy;
* \`POST /api/projects/attachments/reindex\` re-indexes anything that was
  uploaded before this existed (admin, background job);
* \`POST /api/projects/archive/ingest\` remains for one-off folder ingestion if
  ever needed - point it at a folder on the server.

**Job control** - \`backend/app/services/ai_ingest_jobs.py\`
* background jobs with progress in \`/data/ai_ingest_status.json\`;
* \`POST /api/projects/archive/jobs/stop?kind=backfill|attachments|archive\`
  stops a job cooperatively (all are resumable);
* \`GET /api/projects/archive/ingest/status\` shows progress + corpus size.

**Training data** - \`backend/app/services/ai_training.py\`
* 👍/👎 in the chat -> \`POST /api/ai/feedback\` -> \`/data/ai_feedback.jsonl\`;
* \`POST /api/ai/training/export\` -> \`/data/training/ihp_sft.jsonl\`
  (chat format): rated-good answers plus exact Q/A pairs generated from the
  live fact pack.

## 3. Verified end to end

| Check | Result |
| --- | --- |
| Upload a SOW to PR-12725 | appears in the corpus as \`attachment/ihp_scope_test.txt\`, scoped to project 262 |
| \`GET /api/ai/search?q=what pressure is the nitrogen line tested at&project_id=262\` | returns that document, score 0.545, snippet exact |
| \`POST /api/ai/ask\` with the same question | answers and cites \`attachment/ihp_scope_test.txt\` |
| Delete the attachment | corpus copy removed (corpus back to 0 documents) |
| Counts/question on app data | \`mode: "live"\`, instant (0.2-0.3 s), matches the construction dashboard exactly |

## 4. Hardware and models

| Machine | CPU | RAM | GPU | Role |
| --- | --- | --- | --- | --- |
| VPS 185.182.9.20 | AMD EPYC, 6 cores | 11 GB | none | serve Ollama (1B/3B), retrieval, indexing |
| Training PC | Ryzen 9 9900X, 12 cores | 31 GB | RTX 5060 Ti | fine-tuning, bulk extraction |

Installed: \`llama3.2:1b\` (fastest), \`llama3.2:3b\`, \`nomic-embed-text\`.
Worth pulling for better answers (the dropdown picks them up automatically):
\`ollama pull qwen2.5:3b\`, \`ollama pull phi4-mini\`, \`ollama pull granite3.3:2b\`
(RAG-answer tone). Embedding runs at ~10 chunks/s on this CPU; a project's
documents index in seconds.

## 5. Latency limits (important)

Cloudflare aborts a proxied request at **~100 s (HTTP 524)**, and the model runs
on CPU, so the assistant is bounded:

* \`AI_NUM_CTX=8192\` (Ollama's own default of 2048 rejects the context block),
* \`AI_CHAT_TIMEOUT=600\`, \`AI_NUM_PREDICT=512\`,
* retrieval excerpts capped at 800 chars x 4 hits,
* do not run an embedding/index job while people are chatting: it saturates the
  CPU and pushes answers past the proxy cap. Stop it with
  \`/api/projects/archive/jobs/stop\` and resume later.

The proper long-term fix for long generations is streaming (SSE) or
submit-and-poll; both are still open work.

## 6. Recipe: fine-tune on the PC, serve on the VPS

1. Export the dataset: \`POST /api/ai/training/export\`, then
   \`docker compose cp backend:/data/training/ihp_sft.jsonl .\`
2. Train on the PC (a 1B-3B LoRA takes minutes on a 5060 Ti):
   \`\`\`bash
   pip install "transformers>=4.45" peft trl accelerate datasets
   python train_lora.py --data ihp_sft.jsonl \\
       --model meta-llama/Llama-3.2-1B-Instruct --epochs 3 --out ihp-lora
   \`\`\`
   Use \`trl.SFTTrainer\` with the \`messages\` field already in the export.
3. Merge, convert to GGUF, import into Ollama:
   \`ollama create ihp-assistant -f Modelfile\` (FROM the GGUF).
4. Copy it to the VPS - it appears in the model dropdown automatically
   (\`GET /api/ai/models\` lists everything Ollama has).
5. Evaluate against a golden set before switching; keep the tuned model as an
   option, never as the only path. The deterministic layer stays the source of
   truth for numbers.

## 7. Scaling retrieval

Vectors are stored as JSON and compared in Python, which is fast enough up to
roughly 10^5 chunks and keeps SQLite dev and Postgres prod identical. Beyond
that, the database image already ships pgvector: add
\`embedding_vec vector(768)\` + an HNSW index and query with
\`ORDER BY embedding_vec <=> :q\`, keeping the keyword path as a fallback.
