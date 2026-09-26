# Local AI: precision, retrieval and training plan

Status as of this commit: **retrieval, ingestion and the training-data loop are
implemented**; the fine-tuning itself is an optional next step (recipe below).

## 1. Short answer

| Goal | What actually works | Where it runs |
| --- | --- | --- |
| Exact numbers, dates, lists, stages | Deterministic answers read straight from the database (\`mode: "live"\`) | VPS |
| "What does our archive say about X?" | Retrieval over the document corpus (keyword + embeddings), cited by file name | VPS |
| Better wording, summaries, drafts | A larger instruct model (3B-8B) - quality, not facts | VPS (CPU) |
| Domain style / house format | LoRA fine-tune of a small model on the exported dataset | **Training PC (RTX 5060 Ti)**, served from the VPS |
| "The model trains itself" | Automated re-index + feedback capture + periodic supervised fine-tune + evaluation. Never unsupervised self-training | both |

Fine-tuning cannot make a 1B model accurate about 262 live projects - it will
still invent numbers, and a wrong number baked into weights is worse than a
wrong number in a prompt. Facts belong to retrieval and to the database; style
and format belong to fine-tuning.

## 2. What is implemented

**Retrieval** - \`backend/app/ai/retrieval.py\`
* hybrid score: keyword overlap (no model needed) + embedding cosine when the
  chunk has a vector; SQL keyword prefilter keeps it fast; duplicate chunks are
  dropped.
* \`GET /api/ai/search?q=...\` returns hits and corpus size without calling a
  model - useful to sanity-check what the assistant can cite.

**Ingestion**
* \`POST /api/projects/archive/ingest\` (admin, background) walks a folder,
  extracts text (pdf, docx, xlsx, msg, txt, md, csv), chunks it, embeds it and
  stores it in the corpus. Defaults to \`ARCHIVE_PATH\`; the shipped text corpus
  is mounted at \`/archive_text\`.
* \`GET /api/projects/archive/ingest/status\` - progress, corpus size, last scan.
* \`POST /api/projects/archive/embeddings/backfill\` - embed chunks that were
  ingested while the provider was offline.
* \`scripts/extract_archive_text.py\` - runs on the Windows machine, walks the
  raw archive, and writes a compact \`.txt\` mirror (resumable, parallel, skips
  scanned drawings with no text layer) which is what gets copied to the server.
  On this archive: 3,161 candidate documents (5.4 GB) -> tens of MB of text.

**Answers** - retrieved excerpts are given to the model with file name and chunk
index, cited in the UI sources, and the prompt says live database facts win when
a document disagrees.

**Training data**
* 👍/👎 in the chat -> \`POST /api/ai/feedback\` -> \`/data/ai_feedback.jsonl\`.
* \`POST /api/ai/training/export\` -> \`/data/training/ihp_sft.jsonl\`, chat-format
  (system/user/assistant) examples: rated-good answers plus exact question and
  answer pairs generated from the live fact pack.

## 2b. What is actually loaded right now

| Item | Value |
| --- | --- |
| Archive source | `E:\ENGINEERING_DATA` (IHP_Projects + archives), 473 GB drive |
| Candidates selected | 3,161 engineering documents (SOW/BOQ/EAR/MOM/spec/quote/ICR) |
| Extracted text | 3,011 documents, 100.8 MB of text (137 scanned PDFs had no text layer) |
| Shipped to server | 13.6 MB gzip -> `/opt/ihp/archive_text` (read-only at `/archive_text`) |
| Corpus | 3,011 documents, 52,743 chunks, keyword retrieval live |
| Embeddings | embedding backfill is **paused** (552 of 52,743 chunks) - resume any time |
| Verified | "Which archived document covers a nitrogen line installation?" -> answers and cites `archive/PR 9446 ... 03_WCH/...WCH.pdf.txt` in ~17 s |

Long jobs share the CPU with the chat model, and **Cloudflare aborts a proxied
request at ~100 s** (HTTP 524), so the knobs below matter:

```bash
# resume / stop the embedding backfill (resumable, ~2 chunks/s)
curl -X POST "$API/api/projects/archive/embeddings/backfill?limit=60000" -H "Authorization: Bearer $TOKEN"
curl -X POST "$API/api/projects/archive/jobs/stop?kind=backfill"          -H "Authorization: Bearer $TOKEN"
# progress
curl "$API/api/projects/archive/ingest/status" -H "Authorization: Bearer $TOKEN"
```

Best practice: run the backfill overnight (it is CPU-saturating), and keep chat
answers short (`AI_NUM_PREDICT=512`, excerpts capped at 800 chars) so a single
request stays well inside the 100 s proxy window. The proper long-term fix for
long generations is streaming (SSE) or a submit-and-poll endpoint.

## 3. Hardware reality

| Machine | CPU | RAM | GPU | Role |
| --- | --- | --- | --- | --- |
| VPS 185.182.9.20 | AMD EPYC, 6 cores | 11 GB | none | serve Ollama (1B/3B), retrieval, ingestion |
| Training PC | Ryzen 9 9900X, 12 cores | 31 GB | RTX 5060 Ti | fine-tuning, dataset building, bulk extraction |

Measured on the VPS: \`llama3.2:1b\` answers a ~1,800-token prompt in 25-35 s;
embedding runs at ~11 chunks/s (batched). Full archive embedding of ~30k chunks
is therefore a ~45 minute background job. An 8B model would answer in ~2-4
minutes - usable, but not for interactive chat.

## 4. Model options

Already installed: \`llama3.2:1b\` (fastest), \`llama3.2:3b\`, \`nomic-embed-text\`.

Worth pulling on the VPS (CPU-friendly, better instruction following):
\`\`\`bash
ollama pull qwen2.5:3b        # best small generalist, strong at tables/JSON
ollama pull phi4-mini         # 3.8B, good reasoning for its size
ollama pull granite3.3:2b     # IBM, tuned for RAG answers with citations
ollama pull bge-m3            # multilingual embeddings (if non-English docs matter)
\`\`\`
The chat UI lists everything Ollama has pulled, so a new model appears in the
dropdown as soon as \`ollama pull\` finishes.

## 5. Recipe: fine-tune on the PC, serve on the VPS

This is the safe version of "the model improves itself": a periodic,
supervised tune on curated examples, evaluated before it is used.

1. **Export the dataset** (VPS):
   \`\`\`bash
   curl -s -X POST https://ihp.shariar.dev/api/ai/training/export -H "Authorization: Bearer $TOKEN"
   # -> /data/training/ihp_sft.jsonl
   docker compose cp backend:/data/training/ihp_sft.jsonl .
   \`\`\`
2. **Train on the PC** (RTX 5060 Ti, 16 GB - a 1B-3B LoRA takes minutes):
   \`\`\`bash
   pip install "transformers>=4.45" peft trl accelerate datasets
   python train_lora.py --data ihp_sft.jsonl \
       --model meta-llama/Llama-3.2-1B-Instruct --epochs 3 --out ihp-lora
   \`\`\`
   Use \`trl.SFTTrainer\` with the \`messages\` field already in the export. Keep
   the base model's chat template. For 7B-8B use 4-bit QLoRA
   (\`load_in_4bit=True\`) - still comfortable in 16 GB.
3. **Merge and convert to GGUF**, then import into Ollama:
   \`\`\`bash
   ollama create ihp-assistant -f Modelfile   # FROM ./ihp-lora-Q4_K_M.gguf
   ollama cp ihp-assistant ihp-assistant:latest
   \`\`\`
   (\`llama.cpp/convert_hf_to_gguf.py\` then \`llama-quantize\` for the GGUF step.)
4. **Ship it to the VPS** and it shows up in the model dropdown:
   \`\`\`bash
   ollama push         # or scp ~/.ollama/models/blobs/... and recreate the manifest
   ollama list         # ihp-assistant appears -> /api/ai/models lists it
   \`\`\`
5. **Evaluate before switching**: keep a golden set of ~50 questions with known
   answers (the deterministic layer can generate them). Only adopt the tuned
   model if it does not regress; otherwise keep it as a selectable option.

## 6. Scaling retrieval past ~100k chunks

Vectors are stored as JSON and compared in Python, which keeps SQLite dev and
Postgres prod identical and is fast enough up to roughly 10^5 chunks. Beyond
that:

* the database image already ships pgvector - add
  \`ALTER TABLE corpus_chunks ADD COLUMN embedding_vec vector(768)\` plus an HNSW
  index, and query with \`ORDER BY embedding_vec <=> :q\`;
* keep the keyword prefilter as a fallback so a missing embedding never breaks
  an answer.

## 7. Operational notes

* Re-index nightly (new documents, changed files) - idempotent, skips unchanged
  files by size+mtime:
  \`\`\`bash
  0 3 * * * cd /opt/ihp && docker compose exec -T backend python -c \
    "from app.services import ai_ingest_jobs as j; print(j.start_archive_scan('/archive_text', 1, max_files=20000))"
  \`\`\`
  (a CLI/cron wrapper is a good next step - today it is an admin API call).
* Never point an unsupervised loop at production answers: without a human
  signal it drifts, and drift in a delivery dashboard is a safety problem.
