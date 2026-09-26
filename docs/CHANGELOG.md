# CHANGELOG — KAUST IHP ProjectFlow AI

All notable changes to the platform and the master prompt. Format follows
the master prompt Section 13 contract: every version, every change, every reason.

## [Platform] — 2026-09-17 — Module B: latest-tracker resolution + PR-request option

**Reason:** Planner direction — the system must ALWAYS point at the newest
`_DDMMYYYY`-dated tracker file; PR-request PDFs will be dropped into
`trackers\PR Request Copy\` for bulk loading.

- `[ADDED]` `services/tracker_files.py` — `latest_dated()` resolver
  (`_DDMMYYYY`, `_YYYYMMDD`, `_YYYY-MM-DD` suffixes; case-insensitive
  prefix; single-undated fallback) + `tracker_status()`.
- `[ADDED]` `TRACKERS_DIR` + `PR_REQUEST_DIR` settings (runtime-overridable
  in Settings) and `GET /api/admin/settings/tracker-files` — reports which
  planner/O&M file the system points at NOW + lists PR-request PDFs.
- `[MODIFIED]` `backfill_planner_bucket.py` — default tracker resolved to
  the newest dated file (was hardcoded `_07092026`).
- Verified live: planner → `IHP- Construction Projects_15092026.xlsx`,
  O&M → `..._15092026.xlsx`, `PR Request Copy` folder detected (0 PDFs).
  **Suite: 175 → 180 green.** Next: C (three-source reconciliation), then
  D (archive).

## [Platform] — 2026-09-16 — Module A: bucket dashboard + drill-down

**Reason:** Planner requirement — clickable bucket count buttons (EAR,
DESIGN, PTW/WICF, CONSTRUCTION, WCH, WCC…) on the dashboard, each opening
a detail dashboard with search, filters, status arrows, green progress
bars, notes and checklist chips. First of four modules (B: upload fixes,
C: three-source reconciliation, D: archive).

- `[ADDED]` `/dashboard` is now a real Bucket Dashboard (was a redirect):
  count tiles per planner bucket with share bars, built on
  `?bucket=` API data.
- `[ADDED]` `/dashboard/bucket/[bucket]` drill-down: search, stage/trade
  filters, per-project status arrow (✔/▲/•) + green completion bar +
  planner notes chips (trades, division, priority, PI), linking into the
  project page.
- Investigation findings for Module B (fix next): tracker folder holds
  BOTH `_07092026` and `_15092026` versions of the IHP planner and O&M
  sheets while default import paths point at the stale `_07092026`; and
  `/api/admin/import/planner` defaults to dry-run unless `dry_run=false`
  is sent — together explaining "uploads don't land in the system".

## [Platform] — 2026-09-16 — Register filter: Source → planner Bucket

**Reason:** Planner direction — the "Source" filter is not needed; replace
it with the IHP planner's own Bucket grouping (EAR, DESIGN, PTW/WICF,
CONSTRUCTION, WCH, WCC, ...).

- `[ADDED]` `projects.planner_bucket` column (raw MS-Project Bucket,
  indexed) + migration `c4d8e1f2a6b0`. Canonical bucket list stays in
  `BUCKET_TO_STAGE` (scripts/import_planner.py).
- `[MODIFIED]` `import_planner.py` — persists the raw bucket on create and
  update (alongside the existing bucket→stage mapping).
- `[MODIFIED]` `GET /api/projects?bucket=` — exact, case-insensitive
  bucket filter; `planner_bucket` exposed in `ProjectListItem`.
- `[MODIFIED]` Register page (`/projects`): Source filter replaced with a
  Bucket filter (canonical buckets + any seen in data); card detail field
  Source → Bucket. `api.ts`/`types.ts` updated.
- `[ADDED]` `scripts/backfill_planner_bucket.py` — bucket-ONLY backfill
  from the tracker (no stage changes; safe any time). **First run: 250/250
  projects bucketed** — WCH 101, WCC 92, CONSTRUCTION 20, EAR 18,
  DESIGN 10, PTW/WICF 8, QUALITY INSPECTION 1.
- `[ADDED]` 4 tests (filter match, case-insensitivity, exclusion,
  unbucketed behavior) + bucket persistence pinned in the planner-import
  test. **Suite: 171 → 175 green.** (API `source` param retained for
  compatibility; UI no longer uses it.)

## [Platform] — 2026-09-16 — AI-coordinated materials proposals (EAR budget + MTO drafts)

**Reason:** Planner requirement — the app should automatically suggest
materials from the project request + assessment, trade-wise from the
materials master list, with AI coordination drafting the initial budget
and MTO proposal for review.

- `[ADDED]` `AiMaterialsProposal` model + migration `b7e2a9c1d3f4`
  (items JSON, stage_target EAR|MTO, status draft|accepted|rejected,
  mode ai|keyword, SAR totals, model used, decision stamps).
- `[ADDED]` `services/ai_materials.py` — project brief from PR + EAR
  trade proposals + SOW scope; deterministic trade-wise keyword scoring
  of master-pricing candidates (per-trade top-8, cap 48); LLM coordinator
  picks items + estimates quantities (JSON-only prompt, defensive parse,
  invalid codes rejected); graceful degradation to keyword mode when the
  provider is offline or returns unusable JSON (same pattern as the EAR
  cross-check). Every item is a §3 ASSUMPTION until accepted.
- `[ADDED]` Endpoints in `mto.py`: POST `/mto/project/{id}/materials-proposal`
  (mto.manage), GET `.../materials-proposals`,
  POST `.../{pid}/accept` + `.../{pid}/reject`
  (ai.proposal.accept). Accept creates design `BoqMtoItem` rows priced
  from the master list — the AI never writes to a BOQ itself. All audited.
- `[ADDED]` `tests/test_ai_materials.py` — 11 tests (provider pinned:
  offline→keyword, stubbed chat→ai; trade filter; invented-code rejection;
  accept→BOQ creation; 409 double-decide; RBAC 403s; tokenizer).
  **Suite: 160 → 171 green.**
- `[FIX]` dev.db alembic drift: startup `create_all` had built tables
  beyond the stamped revision; verified all tables present and stamped
  dev.db to head `b7e2a9c1d3f4`.
- First live run (PR-12630, EAR target, electrical+civil): **mode=ai**
  (configured provider), 8 items priced from the Planner's master file,
  SAR 4,466.52 + VAT = 5,136.50, draft awaiting decision.

## [Platform] — 2026-09-16 — Materials price-master sync (living document)

**Reason:** Planner designated
`E:\ENGINEERING_DATA\trackers\IHP - Cost Estimates file -1.md` as the
materials price master they will update frequently for project budgets.

- `[ADDED]` `backend/app/services/price_master.py` — markdown-table parser
  (REF | DESCRIPTION | Unit | QTY | ITEM PRICE | TOTAL; QTY/TOTAL ignored),
  keyword trade classifier (flagged as inferred — filter-only), and a
  source-scoped upsert: keyed by `item_code = REF` (the same key
  `generate-budget` matches on); rows removed from the file are
  deactivated, never deleted; MACC/manual pricing rows are never touched.
- `[ADDED]` `POST /api/mto/pricing/sync` (users.manage) — re-syncs on
  demand from `PRICE_MASTER_PATH`; audited via `pricing:sync`.
- `[ADDED]` `PRICE_MASTER_PATH` setting (env default = the E: file) +
  runtime override in Settings (OVERRIDABLE_KEYS, SettingsOut/Update).
- `[ADDED]` `backend/scripts/import_price_master.py` — CLI wrapper
  (`python -m scripts.import_price_master [path]`).
- `[ADDED]` `backend/tests/test_price_master.py` — 8 tests: parser, trade
  inference, insert/idempotent resync, price update + deactivation, MACC
  isolation, endpoint (200/400/403), shared-DB cleanup. **Suite: 152 → 160 green.**
- First live sync: **761 items imported** (307 electrical, trade inferred).

## [Platform] — 2026-09-15 — SOW + BOQ + MTO auto-generator module

**Reason:** Planner issued `docs/SOW_BOQ_MTO_PROMPT.md` v1.0 (SOW/BOQ/MTO
auto-generator spec) and the activation sequence `GENERATE SOW/BOQ/MTO` +
`COMBINE PACKAGE PR-12630`.

- `[ADDED]` `backend/app/services/sow_boq_mto_docgen.py` — deterministic
  generators: SOW Word doc (§3.1 structure, §3.3 verbatim text blocks, all
  six trade subsections with "(Not Seen)", traceability annex, §9.2 drawing
  register with IFC note), BOQ workbook (Cover / Bill of Quantity with
  A–F groups + Supply/Install/S.+I. columns + SAR/USD/VAT totals from
  runtime settings / Take-off Trade sheets), MTO Design workbook with
  computation basis, §10 ZIP package with embedded QA verdict, §11
  ten-point QA checklist. docx→PDF via LibreOffice (best-effort; resolver
  checks PATH then standard install dirs).
- `[ADDED]` Endpoints in `sow_boq.py`: `POST /projects/{id}/generate/{sow|
  boq|mto|package}` (capability sow.manage / boq.manage; ICR gets 409 on
  sow+package; audited) and `GET /projects/{id}/qa-checklist`.
- `[ADDED]` `backend/scripts/seed_pr_12630.py` — idempotent §8 example
  seeding through the live API (reuses the real PR-12630 row, id=245).
- `[ADDED]` `backend/tests/test_sow_boq_mto_docgen.py` — 9 tests pinning
  structure, verbatim blocks, sheet layouts, TBC handling, totals math
  (VAT 15% / USD 3.75), QA outcomes, ZIP tree. **Suite: 143 → 152 green.**
- `[ADDED]` `docs/SOW_BOQ_MTO_PROMPT.md` — the Planner's spec, registered
  verbatim (v1.0).
- No schema migration: v1 scope/metadata live in `SowRecord.trade_sections`
  JSON; pricing lines in `BoqMtoItem`. Production schema (supply/install
  rate split, drawing register table, scope-item table) proposed, awaiting
  Planner approval per master prompt §10.3.
- First real run: PR-12630 package generated on the live server — 9/10 QA
  PASS, check 6 (drawing register) FAIL as expected → package stamped
  "DRAFT — QA FAILED, finalize blocked" per §11.

## [1.1] — 2026-09-15 — Master prompt reconciled to the codebase

**Reason:** v1.0 (written as a greenfield plan) locked the tech stack to
Next.js API Routes + Prisma + NextAuth, but the repository contains a
working FastAPI + SQLAlchemy 2.0 + Next.js 15 platform. Planner approved
reconciling the document to the existing build rather than rebuilding.

### MASTER_PROMPT.md
- `[MODIFIED]` §6 Tech stack — now describes the live stack: FastAPI +
  SQLAlchemy 2.0 + Alembic + Pydantic v2, JWT auth (pwdlib), Next.js 15 +
  React 19 frontend, multi-provider AI routing (ollama/openrouter/
  anthropic/openai/deepseek/kimi/glm/claude) with graceful degradation,
  docxtpl/openpyxl/soffice doc generation, runtime settings overrides.
- `[MODIFIED]` §7 Folder structure — actual `backend/` + `frontend/` tree.
- `[MODIFIED]` §8 Data model — actual 22 SQLAlchemy models, the 5 roles +
  22 capabilities, and the load-bearing extension recipe (state machine →
  rbac → types.ts mirror → api.ts → tests; Alembic chained from head).
- `[ADDED]` §4A — phase↔stage mapping table (5 business phases ↔ 17-stage
  state machine incl. ICR fast-track and `ICR_DONE`), with honest ◐ markers
  for steps that have no stage constant (1.2, 1.3, 1.5).
- `[MODIFIED]` §3 — traceability engine marked IMPLEMENTED (`DataPoint`
  model, `/api/projects/{id}/data-points` CRUD + CONFIRM, Planner-only
  `data.confirm`, edit-voids-confirmation semantics).
- `[MODIFIED]` §5 — document registry gained a generator + status column
  (built: EAR Word, BOQ/MTO Excel; to build: the rest).
- `[MODIFIED]` §11 — build sequence rewritten as R1–R7 on the live
  platform (data-points UI → utility matrix → AI extraction → generators →
  gap analysis → risks/actions → PR 12623 onboarding).
- `[MODIFIED]` §12 — replaced the v1.0 `create-next-app` first command
  with actual run/verify commands (pytest, uvicorn, seed, next dev).
- `[ADDED]` §10 open items requiring Planner decisions (Procore reviewer
  role mapping; >USD 10k free-bidding gate; stage constants for 1.2/1.3/1.5).
- `[REMOVED]` — nothing. No phases, steps, rules, or document types removed.

### Tests (WIP test debt fixed — no product bugs found)
- `tests/test_capability_matrix.py` — pinned `data.manage` /
  `data.confirm` in `ALL_CAPABILITIES` and the `planning` role default
  (caps were added to `core/rbac.py` with the data-points feature but the
  pinning tests weren't updated).
- `tests/test_auth.py` — `ALL_CAPS_SORTED` gained the two data caps;
  fixed stale "admin: all 8" comment.
- `tests/test_imports_settings_mto.py` — `isolated_settings_file` now
  patches `runtime_settings._overrides_path` (the settings refactor moved
  path resolution out of `app.api.settings`; the old `SETTINGS_PATH`
  module constant no longer exists).
- **Baseline: 3 failed + 5 errors + 135 passed → 143 passed** (verified
  this session, `python -m pytest tests/`, ~13s).

## [1.0] — Initial master prompt

Greenfield plan: 5-phase lifecycle, source-tag traceability rules, 17
auto-generated documents, module build sequence 1–11. Tech stack as
planned (Next.js API Routes + Prisma + NextAuth + Supabase/Vercel).
