# IHP Project Delivery — full app brief (for briefing an AI, a new developer, or a DeepSeek chat)

**Purpose of this file.** Everything an outside AI needs in order to understand the
app as it really is, and to write a *good* request for a change. Paste this whole
file into a DeepSeek chat (or any AI), add your request using the template at the
bottom, and use the answer as the prompt you send to the coding agent.

---

## 1. What the app is

An internal web app for the **In-House Projects (IHP) team of KAUST Facilities
Management**. It replaces the team's manual paperwork trail for one project —
called a **PR** (project request) — from the moment the request arrives to the
moment the work is closed out.

It is not a generic project manager. It mirrors **their actual documents and
gates**: the O&M register, the MOM (minutes of meeting), the EAR (Engineering
Assessment Request), the Procore submittal round-trip, the SOW/BOQ, the MTO
(material take-off), procurement, construction and close-out — plus an AI layer
that reads every uploaded document and writes the drafts.

The team states the goal of the app as: *"an intelligent app which makes my work
automation"*, *"learn daily the layers I implement"*, *"develop with me daily"*.

**Users today (5 accounts):** admin, moawya_masry_2000, abdul.rahim,
prabhu.murugesan, gouse.pathan — with roles admin / trade / planning (plus RBAC
capabilities and per-user role assignments).

---

## 2. Live system facts

| Item | Value |
|---|---|
| Public URL | **https://ihp.shariar.dev** |
| Host | VPS `185.182.9.20` (Contabo, Ubuntu 24.04), app at `/opt/ihp` |
| Deploy | GitHub repo `mdshariaralmamun/IHP-Dashboard`; push to `main` → GitHub Actions SSHes in and runs `cd /opt/ihp && git pull && docker compose up -d --build` |
| Edge | Cloudflare Zero Trust tunnel (no host ports published), nginx-proxy-manager in front; **Cloudflare caps a request at ~100 s** (HTTP 524) and gzips JSON |
| Containers | `ihp-db-1` (pgvector/pgvector:pg16), `ihp-backend-1` (FastAPI + uvicorn), `ihp-frontend-1` (Next.js standalone), `ihp-ollama` (local LLM + embeddings, CPU only), `ihp-db-backup-1` (nightly dumps, 14 days) |
| Migrations | run automatically by the backend container: `alembic upgrade head && uvicorn ...` |
| Build time | full `up -d --build` ≈ 4 minutes (more when apt packages change) |
| SSH (for verification) | `ssh -i <deploy key> root@185.182.9.20` |

---

## 3. Stack

**Backend** — Python 3.11, FastAPI (async endpoints where needed), SQLAlchemy 2.0
(typed `Mapped`/`mapped_column`), Alembic, Pydantic v2 + pydantic-settings, JWT
auth (PyJWT) with bcrypt via pwdlib, Postgres 16 + **pgvector**, psycopg 3.
Document libraries in the image: **python-docx / docxtpl** (Word), **openpyxl**
(Excel), **pypdf** and **PyMuPDF** (`import pymupdf`; the `fitz` alias is
deprecated), **extract-msg** (.msg), plus **LibreOffice** (`soffice`, with
Writer **and Calc**) and **headless Chromium** for HTML→PDF. Dependency list is in
`backend/pyproject.toml`.

**Frontend** — Next.js 15 standalone, React 19, TypeScript, Tailwind (dark mode
via `html.dark`), `recharts` in one public dashboard, `docx-preview` for the Word
web view. The frontend proxies `/api/*` to the backend
(`proxyTimeout: 600_000` because the AI and document generation are slow on a
CPU-only VPS: `frontend/next.config.ts`).

**Database tables (31)**: `users, projects, attachments, plan_markers, mom_records,
corpus_documents, corpus_chunks, audit_logs, data_points, ear_records,
ear_trade_inputs, sow_records, boq_mto_items, construction_mto_items,
construction_records, closeout_records, punch_list_items, icr_handoffs,
master_pricing, ai_materials_proposals, project_budget_summaries,
project_stage_budgets, crew_assignments, access_requests, project_todos,
pipeline_stages, source_documents, source_briefs, brief_questions,
procore_comments, mto_draft_items`.

**Everything is audited**: `audit_logs` records actor, action key
(`stage:SOW_APPROVED`, `package:pdf`, `procore:revise`, …) and a JSON payload;
the project page shows that trail.

---

## 4. Repository layout

```
/opt/ihp  (this repo)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app; every router registered here
│   │   ├── models.py            # all 31 SQLAlchemy models
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── db.py                # engine + SessionLocal + Base
│   │   ├── core/                # config.py (settings), security.py (JWT/hash), rbac.py (capabilities)
│   │   ├── api/                 # 31 endpoint modules (see the table in §5)
│   │   └── services/            # 31 domain services (see the table in §5)
│   ├── alembic/versions/        # one migration per schema change
│   ├── templates/               # the team's own Word/Excel templates (tagged)
│   ├── reference_data/          # FLOC lab list, building masters, area bands
│   ├── scripts/                 # importers + verification scripts
│   └── tests/                   # pytest suite (363 tests, all green)
├── frontend/
│   └── src/
│       ├── app/                 # 28 routes (App Router)
│       ├── components/          # 35 components (project panels, boards, powerbi widgets)
│       └── lib/                 # api.ts (typed client), types.ts, stages.ts, useUser.ts, version.ts
├── docker-compose.yml           # db + backend + frontend + db-backup (+ optional cloudflared)
├── CHANGELOG.md                 # every change, by app version
└── APP_BRIEF.md                 # this file
```

---

## 5. Backend map (211 endpoints)

| Module (`app/api/`) | Prefix | Endpoints | What it owns |
|---|---|---|---|
| `projects.py` | `/projects` | 34 | PR CRUD, list/filter, attachments, audit, tracker derivation, EAR promotion |
| `mto.py` | `/mto` | 14 | Design MTO budget, project/stage budgets |
| `sources.py` | `/projects` | 14 | Data room: upload, text extraction, AI brief, price-master import |
| `mom.py` | `/projects/{id}/mom` | 13 | MOM generate/send/confirm, agenda, `POST /parse-invitation` |
| `ai.py` | `/ai` | 12 | Chat with citations, corpus, ingestion jobs, training |
| `sow_boq.py` | `/projects/{id}` | 12 | SOW revisions, BOQ/MTO items, Excel export, **`POST /package/pdf`** (combined Procore binder) |
| `procore.py` | `/projects/{id}/procore` | 10 | Reviewer comments, Comment Log Sheet, manual Procore status, submittal dropzone, `POST /revise` |
| `roles.py` / `user_roles.py` | `/api/roles`, `/api/user-roles` | 16 | RBAC administration |
| `ear.py` | `/projects/{id}/ear` | 7 | EAR record, trade inputs, approvals |
| `closeout.py`, `construction_crew.py`, `imports.py` | — | 7 each | Close-out, crew allocation, Excel/O&M importers |
| `construction.py`, `construction_mto.py` | `/projects/{id}/construction` | 3 + 5 | Construction stage, construction MTO |
| `data_points.py`, `markers.py`, `planning.py`, `reference.py`, `access_requests.py` | — | 5 each | Source-tagged data points, plan pins, next-step/to-do, reference data, access requests |
| `admin.py`, `settings.py` | `/admin` | 4 + 4 | Users, runtime settings (including AI provider) |
| `pipeline.py` | `/projects` | 2 | **The five-stage delivery spine** (get/set stage + gates) |
| `public.py`, `icr.py`, `areas.py`, `boards.py`, `disposition.py`, `intake.py` | — | 1–2 each | Public tracking link, ICR branch, areas, boards, disposition, intake |

**Services (`app/services/`)** — the domain logic, kept out of the routers:
`workflow.py` (the canonical stage list + `log_action`), `docgen.py` +
`template_docgen.py` + `sow_boq_mto_docgen.py` + `mom_html.py` +
`ear_docgen.py` + `summary_docgen.py` (document generation), `storage.py`
(versioned file store under `DATA_DIR`), `source_extract.py` (PDF/Word/Excel/
.msg/audio → text), `ai_ingest_jobs.py`, `ai_training.py`, `price_master.py`,
`reference.py` (room → building/area/lab), `tracker_sources.py` +
`tracker_import.py` + `planner_status.py` (the O&M register import),
`consistency.py`, `court.py` (whose court is the ball in), `rbac_service.py` +
`rbac_seed.py`, `emailer.py`, `schedule.py`, `archive_index.py` +
`archive_ingest.py`, `ai_materials.py`, `summary_premium.py`,
`pr_form_parser.py`, `app_documents.py`, `runtime_settings.py`.

---

## 6. The team process the app mirrors

### 6.1 The five-stage delivery spine (`pipeline_stages` + `api/pipeline.py`)
1. **Request registered** — PR exists, contact/PI known.
2. **MOM** — meeting held: agenda, attendees, scope, actions → MOM generated and
   **confirmed** by the team.
3. **SOW / BOQ submitted** — scope of work + bill of quantities issued.
4. **Procore submittal** — the package goes to the reviewers, comments come back,
   answers are logged, a revision is issued.
5. **MTO / procurement** — material take-off and buying, once Procore approves.

**Gates are enforced by the API and explained in the UI**, never silent:
stage 2 needs the MOM confirmed; stage 3 needs stage 2 *approved/pending*;
stage 4 needs stage 3 *issued*; stage 5 waits for a **Procore approval**
(`approved` or `approved_as_noted`). A blocked stage shows the reason.

### 6.2 The Procore round-trip (Stage 4 detail)
Rev 0 goes out with a cover page. Reviewers are (quick-select, free text always
allowed): **HSE Team, FLP / Fire Protection, FMOM / Building Management, Building
Operations, CTPS, Proponent / PI**. Each comment is logged with department,
discipline, comment, IHP response, action taken, open/closed and the revision it
was raised on. IHP exports **`PR-XXXXX Comments Logs.xlsx` / `.pdf``, sets the
**Procore status by hand** (Under Review | Revise and Resubmit | Approved as
Noted | Approved) plus the submittal date, uploads the **stamped Procore
Submittal PDF**, and presses **[Generate Revision N Package]** (Rev 0 → Rev 1),
which stamps the new date and reports which items the new package must answer.

### 6.3 The combined binder (`POST /projects/{id}/package/pdf`)
Cover page (PyMuPDF, A4 portrait) → **SOW** → **BOQ** → **Procore Comment Log**
→ every non-generated PDF attachment (drawings). Each source keeps its own page
size and orientation (an A3 plot stays A3, a landscape CAD sheet stays
landscape). A part that cannot be converted is written to the audit trail as
`package:skip` instead of vanishing. The result is attached to the PR as a
`DELIVERABLE` and the revision is printed on the cover.

### 6.4 The EAR funnel (engineering assessment)
`cancelled, on_hold, site_visit, summary_trade` ("Project Summary Received by
Trade"), `waiting_wbs`, `pi_signature` ("EAR Under PI Signature"),
`asepc_pending` ("EAR Waiting for ASEPC Approval"), `ear_approved`,
`ear_revised`, `ear_issued`, `wbs_request, awaiting_summary, asepc_approved,
in_progress`. Rule agreed with the team: **the Requester approves, the PI
funds.**

### 6.5 ICR branch
Pull ICR projects from the O&M **Active Equipment PRs** tab: only rows classified
**"Construction Project"** (the typo "Contruction Project" is tolerated) become
ICR. Equipment installation never enters the app; the ASEPC Proposal Request is
"upcoming" (decided after the site visit). **IHP Remarks = the live status.**

### 6.6 Locations
A room code decodes as building-level-room. The **area** comes from the first
digit of the room number: **6 → Area 1, 7 → Area 3, 8 → Area 4, 9 → Area 6**;
bands 1xx–5xx are deliberately unmapped until the team supplies them. The lab
list names the **lab, centre and PI** (182 FLOCs). Reference JSONs live in
`backend/reference_data/` and are found wherever the app runs.

### 6.7 MOM
Generate from the team's KAUST Word template → Word/PDF + email draft + status
tracking. Scope/agenda fields are multi-line, resizable, keep line breaks. A
**paste-an-invitation parser** reads pasted Outlook text and extracts PR number,
meeting title, date, start/end time, room code (decoded, with the lab) and
attendees with roles.

---

## 7. The intelligence layer

- **Data room** per project: any format (PDF, Word, Excel, .msg/.eml, csv, images,
  audio) → text extraction cached per file → an **AI brief** (scope by trade,
  utility matrix, line items, open questions) → **answerable questions** stored on
  the project so answers survive re-analysis.
- **AI chat per project** with citations, scope switch (this project / standards /
  everything).
- **Corpus**: 554 documents / 21 243 chunks embedded (pgvector), built from the
  reference library (Specifications 408 docs, MEP BOQ 106, MEP Narrative 26).
- **Price master**: 2 282 items (Planner's cost estimates + the store's quotation
  list, with suppliers), searchable by trade; a materials picker and **MTO drafts**
  (save / update / clear) on top of it; manual override always allowed.
- **AI provider is pluggable** (`backend/app/core/config.py`,
  `services/provider.py`): `AI_PROVIDER` = `ollama` (default, local
  `ihp-ollama`, model `llama3.2:3b`, embeddings `nomic-embed-text`) or
  `openrouter / anthropic / openai / deepseek / kimi / glm / claude` with the
  matching key (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, …). Admins can also change
  it at runtime from **Admin → Settings** (`/api/admin/settings`).

---

## 8. RBAC

Capabilities (`backend/app/core/rbac.py`): `projects.create/edit/delete`,
`attachments.upload/delete`, `mom.manage`, `mom.agenda`, `users.manage`,
`disposition.manage`, `ear.input`, `ear.manage`, `sow.manage`,
`boq.manage`, `mto.manage`, `procurement.manage`, `work_permit.manage`,
`construction.manage`, `closeout.manage`, `icr.handoff`,
`ai.proposal.accept`, `data.manage`, `data.confirm`.
Endpoints take `Depends(require_capability(CAP_...))`; the UI hides what the user
cannot do (`useUser()` + `canDo()`). Roles: `admin`, `trade`, `planning`.

---

## 9. Frontend map

**Routes (28)** — `/` landing · `/login` · `/projects` · `/projects/new` ·
**`/projects/[id]`** (the working page: next step, delivery pipeline, Procore
review, data room, AI chat, materials picker, plan pins, MOM, EAR, disposition,
SOW/BOQ, construction, close-out, attachments, audit) ·
`/projects/[id]/summary` · `/todo` · `/contacts` · `/areas` · `/upload` ·
`/settings` · `/profile` · `/dashboard` + `/dashboard/{active-prs, consistency,
construction, design, ear, procore, bucket/[bucket]}` · `/admin/{users,
users-roles, roles, roles/[id], access-requests}` · `/request-access` ·
`/invite/[token]` · `/track/[token]` (public tracking link).

**Project panels (`components/project/`)**: `NextStepCard` (the one next step, the
to-do list, the cancellation record), `PipelinePanel` (five-stage spine),
`ProcorePanel` (comment log, log sheet, status, dropzone, Rev N),
`SourceRoomCard` (data room + brief), `ProjectChat`, `MaterialPicker`,
`PlanMarkersCard`, `MomPanel`, `EarPanel`, `DispositionPanel`, `SowBoqPanel`,
`ConstructionPanel`, `CloseoutPanel`, `PunchListPanel`, `AttachmentsSection`,
`AuditTrail`, `MetadataCard`, `StageChangePanel`, `AiReviewCard`,
`PromoteToEarModal`. Shared: `Header`, `AuthGuard`, `ThemeProvider` (dark mode),
`StageBadge`, `MomStatusBadge`, `TrackerStepper`, `TrackingShare`, `PhaseBoard`,
`DashboardView`, `PublicDashboardView`, `AiChat`, `powerbi/PowerBI` (`VisualCard`),
`overrides/OverrideDialog` + `OverrideField`.

**Conventions**: one typed client (`lib/api.ts`) — every call goes through
`request<T>()`; `getToken()` bearer auth; a 401 clears the token and redirects.
Dark-theme text must use the Apple tokens (`text-apple-text`, `text-apple-muted`,
`border-apple-border`, `bg-apple-hover`) — hard-coded colours became invisible in
dark mode before.

---

## 10. How changes are made and proven (the working agreement)

1. **One feature at a time**, finished and deployed, not several half-built.
2. Local proof first: `python -m pytest -q` (363 tests) in `backend/`;
   `npx tsc --noEmit` and `npm run build` in `frontend/`.
3. **Migration discipline**: every schema change is a new Alembic revision, and
   the new revision id is checked for uniqueness across
   `backend/alembic/versions/*.py` **before** deploying (a duplicate id once
   crash-looped the backend and took the site down).
4. Commit + push to `main` (the repo is the source of truth), then on the VPS
   `cd /opt/ihp && git pull --ff-only && docker compose up -d --build`.
5. **Verify live, on a real PR**, with a real admin JWT — e.g.
   `backend/scripts/verify_step_b.py` exercises the whole Procore round-trip and
   then restores the project's state. Report the actual HTTP status, content type,
   byte size and page count; never claim something works unverified.
6. Every user-visible change is written up in `CHANGELOG.md` and the app version
   is bumped in `frontend/src/lib/version.ts` (shown in **Admin → Version**).
   Current version: **1.1.0 — 12 October 2026**.

---

## 11. State of the system (last measured 12 Oct 2026)

~290 projects in the register (288 with a contact email), 15 ICR projects,
139 stored questions, 36 attachments, AI corpus 554 documents / 21 243 chunks,
price master 2 282 items, 5 users, ~33 GB free disk, 363 backend tests green.

**Shipped and verified**: intake/PR register and O&M import · MOM (generate, send,
confirm, invitation parser) · EAR funnels and boards · data room + AI brief +
questions + chat · per-document generation (Project Summary, SOW, BOQ, Cost
Estimate, MTO) from the team's own templates · web view + PDF for each · MTO
drafts from the price master · plan pins · construction, punch list, close-out ·
RBAC + access requests + public tracking link · **five-stage pipeline spine** ·
**combined Procore binder** · **Procore reviewer comment log, Comment Log Sheet,
manual status, stamped-submittal dropzone and Rev N** · dark theme fixes ·
performance work (memoised tracker, cached O&M parse, gzipped JSON).

**Agreed but not yet built (in order)**
- **Step D** — labour must print as "Labor: IHP In-House Resources — $0.00
  (Covered by IHP)"; only materials/equipment/consumables count in the total.
- **Step E** — MTO opens only after Procore approval, with procurement fields
  (brand, part spec, unit of issue, remarks) and Excel/CSV export.
- **Learning layers** — Skills (`.md` playbooks) + Lessons learned + a weekly
  digest, so the app accumulates how this team works.
- **Phase dashboards** — separate dashboards per document generation: MOM,
  Project Summary, SOW, MTO.

**Open questions (asked, not yet answered)**: the one project with no contact
email; SMTP details for really sending mail; which audio-transcription engine
(hosted or local); trade-grouped MOM sections. Known smaller gaps: the global
`/todo` page needs a refresh after changes; the "whose court" logic is still too
blunt; MOM invitation upload box in the UI; fuzzy attendee matching; rich text
(bold/H1/H2/lists) with HTML→Word; photo markup; automatic attachment indexing.

---

## 12. Ready-to-use prompt template

Copy this into a DeepSeek chat together with the section above that matters, fill
the brackets, and send me the result.

```
You are helping me brief a coding agent that works on my live app
"IHP Project Delivery" (https://ihp.shariar.dev). The brief above describes the
app's real structure. Write ONE precise, self-contained request that the agent
can execute and prove.

Feature I want: [describe it in my own words, e.g. "the MTO must not open before
Procore approves, and it needs brand / part spec / unit of issue / remarks
columns plus an Excel and CSV export"]

Rules the request must respect:
- one feature at a time, finished, deployed and verified — never several at once
- say which files/tables/endpoints it touches, and whether it needs a database
  migration
- say what "done" means in verifiable terms (HTTP status, file name, page count,
  rows in the export, which real PR to test on)
- keep the app's existing conventions (typed api.ts client, Apple colour tokens,
  audit log entries, CHANGELOG.md + version bump)
- state what must not change (e.g. labour stays $0.00, Procore status is set by
  hand, the requester approves and the PI funds)

Then output only the final prompt, ready to paste.
```

**Also useful to tell any AI:** the app already contains the whole team process —
the five-stage spine, the Procore comment log and revisions, the SOW/BOQ, the EAR
funnel, the ICR rules, the price master and the AI brief — so ask for changes in
that vocabulary ("a new column on the comment log", "a gate on stage 5"), not in
generic software terms.

**Connecting DeepSeek to the app itself.** The app's AI layer is provider-agnostic:
set `AI_PROVIDER=deepseek` and `DEEPSEEK_API_KEY=<key>` in `/opt/ihp/.env`
(or change it at runtime in **Admin → Settings**) and the in-app chat, briefs and
drafts are answered by DeepSeek instead of the local Ollama model. Embeddings can
stay local (`AI_FORCE_LOCAL_EMBEDDER=1`) so the pgvector corpus keeps working
without an API cost.
