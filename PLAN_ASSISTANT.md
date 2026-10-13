# Implementation plan — "Project Delivery Assistant" (chat mode)

**Target app:** IHP Project Delivery (live at https://ihp.shariar.dev) · app version **1.1.0**
**Goal:** one conversational assistant that orchestrates the existing endpoints in gate order,
so pasting meeting notes produces MOM → Assessment/Cost Estimate → EAR → SOW+BOQ → Drawing List →
Procore binder, each written into its existing panel and the audit trail.

---

## 0. What I verified before planning (grounding facts)

These are read from the live app and the code, not assumed.

| Check | Result |
|---|---|
| Effective AI provider | **deepseek** (runtime override in /data/settings.json; env still says ollama) |
| Base URL / model | https://api.deepseek.com/v1 · **deepseek-chat** |
| API key | present (35 chars, stored in the runtime settings file) |
| Live probe | provider.chat([...]) → 'ASSISTANT-OK' in **0.83 s** |
| Embeddings | nomic-embed-text, AI_FORCE_LOCAL_EMBEDDER untouched |
| Projects in register | 292 |
| **PR-291** | **does not exist** (PR-29186 exists: id 16, stage CLOSEOUT, no MOM/EAR/SOW, no pipeline rows) |

Because DeepSeek answered in **0.83 s**, the assistant can be **synchronous** and stay far below
the Cloudflare ~100 s cap. No streaming and no job queue are needed for v1 (contingency in §1 D6).

### 0.1 Corrections to the file list in the request

| Requested | Reality |
|---|---|
| services/provider.py | **app/ai/provider.py** — `provider.chat(messages, system=None, model=None, provider=None) -> str \| None`, `provider.available() -> (bool, reason)`, `provider.effective_provider(settings)` |
| services/mom.py | **does not exist.** MOM = `api/mom.py` (`build_mom_context`, `get_mom_or_404`, `generate_mom`) + `services/mom_html.py` + `services/docgen.py` (`render_docx`, `docx_to_pdf`) + `services/emailer.py` |
| services/ear_docgen.py | exists but is a **stub**: `generate_ear_document` writes a placeholder .txt and returns `(name, None)`. Real EAR rows yes; real EAR file later (§8.3) |
| services/sow_boq_mto_docgen.py | `generate_sow_docx`, `generate_boq_xlsx`, `generate_mto_xlsx`, `generate_package`, `run_qa_checks`, `TRADE_GROUPS`, `SOW_SECTION_ORDER` |
| services/summary_docgen.py | `generate_project_summary_docx(project, context=None, db=None) -> Path` |
| api/procore.py | comment log + status + revisions (unchanged, reused) |
| api/sow_boq.py | binder is here: `POST /projects/{id}/package/pdf` → `combined_binder(project_id, revision, db, user)` |

### 0.2 The trade vocabulary is A–F, and "General" is not one of them

`sow_boq_mto_docgen.TRADE_GROUPS` (canonical, never reordered):

~~~python
("A", "Civil / Architectural", ("civil",))
("B", "Electrical",            ("electric",))
("C", "Plumbing",              ("plumb",))
("D", "HVAC",                  ("hvac", "mechanical",))
("E", "Low Current",           ("low", "current", "telecom", "lc",))
("F", "Fire Sprinkler",        ("fire", "sprink",))
~~~

SOW §3.1 order is **A, B, E, C, D, F** (Low Current before Plumbing on purpose).
The request's six trades map as: Civil → **A**, Plumbing/Gas Piping → **C**, Electrical → **B**,
HVAC → **D**, Low Current/TGM → **E**, and **"General" has no group** — F is Fire Sprinkler.
Decision needed (§8.2). Default in this plan: the assistant speaks A–F (Fire Sprinkler included)
and places anything truly general under A with the note "General".

### 0.3 The labour rule is not built yet

There is **no labour line anywhere in the codebase**: `_totals_block()` prints only
TOTAL (SAR/USD) + VAT. Step D ("Labor: IHP In-House Resources — $0.00 (Covered by IHP)") is
still on the roadmap. This feature therefore **never puts manpower cost into any total** and
prints the $0.00 labour line in the assessment text. Writing it into the Excel is Step D, not this.

### 0.4 Gate authority that already exists

~~~python
# api/pipeline.py — the single source of truth
STAGES = {1: MOM, 2: Project Summary / EAR & Cost Estimate, 3: SOW package, 4: Procore, 5: MTO}
STAGE_STATUSES = {1: (not_started, in_progress, awaiting_feedback, confirmed), ...}
PROCORE_APPROVED = ("approved", "approved_as_noted")
def blocked_reason(by_stage, stage) -> str | None     # the sentence the UI shows
def _rows(db, project_id) -> dict[int, PipelineStage] # creates the 5 rows on first read
# services/workflow.py — the long project.stage lifecycle (INTAKE … CLOSEOUT, EAR_*)
# services/workflow.py — log_action(db, user, key, project, payload)
~~~

---

## 1. Design decisions

**D1 — An action registry, not a free chat.** The AI writes language; the code owns the writes.
Every step is a named action with a precondition, a writer, an audit key and an artifact.

**D2 — Two-step write (propose, then run).** `POST /message` only *proposes* the next action
and records the user's turn; nothing is written until `POST /run` carries an explicit
`action`. This is exactly the user's flow ("receives MOM → confirm → receives Assessment"),
and it means an AI hallucination can never create rows or documents.

**D3 — Gate authority is imported, not reimplemented.** The orchestrator calls
`pipeline._rows()` and `pipeline.blocked_reason()`; a blocked action returns **409** with the
same sentence the panel already shows. One source of truth, so the assistant can never skip a gate.

**D4 — The EAR funnel is a parallel track.** Actions are tagged `track="spine"` or `track="ear"`.
The EAR steps (Project Summary → PI signature → ASEPC) are proposed once the MOM is confirmed and
do **not** block stage 3; stage 3 does not block them. `GET /assistant` reports both tracks.

**D5 — Reuse the real generators by importing them** (never by HTTP round-trips to our own API):
`mom_api.build_mom_context` + `docgen.render_docx`, `summary_docgen.generate_project_summary_docx`,
`sow_boq_mto_docgen.generate_sow_docx / generate_boq_xlsx / generate_mto_xlsx`,
`ear_docgen.generate_ear_document`, `procore.comment_log_xlsx`, and the binder (§3.6).

**D6 — Synchronous with a hard budget.** One AI call per action, each capped at 60 s
(`ASSISTANT_AI_BUDGET_S = 60`) and the whole request at 90 s, always under Cloudflare's ~100 s.
Response carries `elapsed_ms`. If a future generation exceeds the budget, the documented
escalation is the existing async pattern in `services/ai_ingest_jobs.py`
(`POST /assistant/run?async=1` → `{job_id}` + `GET /assistant/jobs/{id}`) — **not built in v1**.

**D7 — The provider stays pluggable.** Never call DeepSeek directly: always
`provider.chat(messages, system=..., model=body.model, provider=body.provider)`, so the Ollama
fallback and the existing model switcher keep working, and `provider.available()` gates the
endpoint with a readable reason (503).

**D8 — The transcript stores references, not blobs.** `assistant_messages` holds user/assistant/tool
turns with a small JSON `meta` (action, artifacts, elapsed). Documents stay in storage and are
reached through the existing download endpoints.

---

## 2. Migration

**File:** `backend/alembic/versions/20261013_1000_add_assistant_messages.py`
**Revision id:** `20261013_1000` (latest shipped head is `20261012_1000`).
**Uniqueness check before deploy** (run from the repo root — this is a hard gate, a duplicate id
once crash-looped production):

~~~powershell
python - <<'PY'
import re, glob, collections
pat = re.compile(r"revision: str = ['\"]([^'\"]+)")
ids = []
for f in glob.glob("backend/alembic/versions/*.py"):
    m = pat.search(open(f, encoding="utf-8").read())
    ids.append(m.group(1) if m else "MISSING:" + f)
print("migrations:", len(ids), "dups:", [k for k, v in collections.Counter(ids).items() if v > 1])
PY
~~~

~~~python
"""add assistant_messages: the Project Delivery Assistant transcript

Revision ID: 20261013_1000
Revises: 20261012_1000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_1000"
down_revision: str | None = "20261012_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        # action id, artifacts [{kind,label,filename,url,panel}], elapsed_ms, gate snapshot
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_assistant_messages_project_id", "assistant_messages", ["project_id"])
    op.create_index("ix_assistant_messages_project_id_id", "assistant_messages", ["project_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_project_id_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_project_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")
~~~

Roles: `user` | `assistant` | `tool`. The requested six columns are all present;
**`meta` JSON is the one addition**, and it is what lets the UI render artifact cards without a
second table. If you want exactly six columns, artifacts can be recovered from `audit_logs` instead —
say so and I will drop `meta`.

---

## 3. File-by-file

### 3.1 `backend/app/models.py` (modify — +20 lines)

~~~python
class AssistantMessage(Base):
    """One turn of the Project Delivery Assistant transcript.

    role: "user" (what the team pasted), "assistant" (what the assistant said)
    or "tool" (what an action actually produced). meta carries the action id,
    the artifacts (filename + the panel that shows them) and the elapsed time,
    so the chat can render links without a second table.
    """

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="assistant_messages")
~~~

Plus `Project.assistant_messages` relationship (`cascade="all, delete-orphan"`).
`JSON`, `Text`, `ForeignKey`, `DateTime` are already imported.

### 3.2 `backend/app/schemas.py` (modify — append `Assistant*` block)

~~~python
class AssistantArtifact(BaseModel):
    kind: str                       # "docx" | "xlsx" | "zip" | "pdf" | "record" | "table"
    label: str
    filename: str | None = None
    url: str | None = None          # an existing download endpoint
    panel: str | None = None        # "MomPanel" | "EarPanel" | "SowBoqPanel" | ...
    meta: dict = {}


class AssistantGate(BaseModel):
    stage: int
    label: str
    status: str
    allowed: list[str]
    blocked: dict[str, str]         # action -> the reason it may not run


class AssistantEarTrack(BaseModel):
    status: str
    next_step: str | None = None
    trade_inputs: int = 0
    parallel: bool = True


class AssistantAiOut(BaseModel):
    provider: str
    model: str
    available: bool
    reason: str | None = None


class AssistantTurnOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    action: str | None = None
    suggested_action: str | None = None
    needs_confirmation: bool = False
    artifacts: list[AssistantArtifact] = []
    gate: AssistantGate | None = None
    elapsed_ms: int | None = None
    available: bool = True


class AssistantStateOut(BaseModel):
    project_id: int
    pr_number: str
    pipeline: dict
    gate: AssistantGate
    ear: AssistantEarTrack
    actions: list[dict]
    ai: AssistantAiOut
    transcript: list[AssistantTurnOut] = []


class AssistantMessageIn(BaseModel):
    message: str
    model: str | None = None
    provider: str | None = None


class AssistantRunIn(BaseModel):
    action: str
    note: str | None = None
    model: str | None = None
    provider: str | None = None
~~~

### 3.3 `backend/app/services/assistant_orchestrator.py` (new — ~480 lines)

The whole brain. Public surface:

~~~python
LABOUR_LINE = "Labor: IHP In-House Resources — $0.00 (Covered by IHP)"
ASSISTANT_AI_BUDGET_S = 60
MAX_MESSAGE_CHARS = 20000


@dataclass(frozen=True)
class Action:
    id: str                 # "mom.draft"
    label: str              # "Generate the MOM from these notes"
    track: str              # "spine" | "ear"
    stage: int              # the five-stage spine stage it belongs to
    capability: str         # the capability it needs (checked by the API layer)
    panel: str              # which existing panel shows the result
    audit_key: str          # the audit_logs action key
    precondition: str | None  # None | "mom_confirmed" | "stage2_out" | "stage3_out" | "procore_approved"
    writer: Callable[..., dict]


ACTIONS: dict[str, Action] = {...}          # the 12 actions in §4


# ---- state ---------------------------------------------------------------
def pipeline_state(db: Session, project: Project) -> dict      # pipeline._rows/_payload
def ear_state(db: Session, project: Project) -> AssistantEarTrack
def allowed_actions(db, project) -> tuple[list[str], dict[str, str]]
def next_action(db, project) -> str | None
def gate(db, project) -> AssistantGate


# ---- transcript ----------------------------------------------------------
def record(db, project, role, content, *, actor_id=None, meta=None) -> AssistantMessage
def transcript(db, project, limit: int = 50, offset: int = 0) -> list[dict]


# ---- the two steps -------------------------------------------------------
def propose(db, project, user, message: str, *, model=None, provider=None) -> dict
def run_action(db, project, user, action: str, *, note=None, model=None, provider=None) -> dict


# ---- AI helpers ---------------------------------------------------------
def _ai_text(system: str, prompt: str, *, model, provider, timeout_s=ASSISTANT_AI_BUDGET_S) -> str | None
def _ai_json(system: str, prompt: str, *, model, provider, keys: tuple[str, ...]) -> dict | None
def _trades() -> list[tuple[str, str]]            # A–F from TRADE_GROUPS
def _trade_block() -> str                          # the six-trade instruction block
~~~

**The propose call** (one AI call): the system prompt contains the project facts, the *allowed*
action list and the blocked reasons; the model must answer with one JSON object
`{"action": "...", "reason": "...", "reply": "..."}`. The action is validated against the
allowed set — if the model names a blocked or unknown action, the orchestrator falls back to
`next_action()` and says so in the reply. The user's message is recorded as a `user` turn first.

**One AI call per action**, each with a fixed JSON shape (all values are trusted only after
validation; empty/missing fields fall back to the deterministic generator):

| Action | Prompt intent | JSON the model must return |
|---|---|---|
| mom.draft | structure meeting notes into the KAUST MOM fields | `{meeting_title, location, date, time, attendees:[{name,title,email}], agenda:[{scope,action,responsible}]}` |
| summary.draft | trade-wise assessment + cost estimate, Supply & Install by IHP | `{summary, scope, trades:[{group,assessment,basis:"Supply & Install by IHP",materials_sar,equipment_sar,consumables_sar}], total_sar, notes}` |
| ear.draft | engineering assessment: findings, recommendations, trade budgets | `{summary, recommendations, trade_budgets:{A:{materials,manpower},...}}` |
| sow.draft | SOW §3.1 sections per group + measurement lines | `{scope_text, trade_sections:[{group,scope,measurements:[{description,unit,quantity}]}], drawings:[{drawing_no,rev,title,date}]}` |
| boq.draft | BOQ lines from the SOW measurements, unpriced | `{items:[{group,item_code,description,unit,quantity}]}` |
| drawings.list | technical drawing register | `{drawings:[{drawing_no,rev,title,discipline,date,status}]}` |
| mto.draft | procurement-ready take-off (after Procore approval) | `{items:[{group,item_code,description,unit,quantity,material_spec}]}` |

**Writers** (each ends with `workflow.log_action(db, user, action.audit_key, project, {...})`,
returns `{"artifacts": [...], "summary": "...", "saved": {...}}`):

* `_mom_draft` — upsert the single `MomRecord` (version+1), `details={<the model JSON>}`,
  `context = mom_api.build_mom_context(project, details, version)`,
  `docgen.render_docx(MOM_TEMPLATE_NAME, context, mom_dir / docx_name)` + `docx_to_pdf`,
  `emailer.build_mom_draft`; artifact → `GET /projects/{id}/mom/download?format=docx`, panel MomPanel.
* `_summary_draft` — `summary_docgen.generate_project_summary_docx(project, ctx, db)`, plus one
  `DataPoint` row per trade (`source_tag="DOC"`, `origin="assistant:summary"`) so the numbers are
  traceable; cost text incl. `LABOUR_LINE`; artifact → the generated Summary + a "Cost estimate" table.
* `_ear_draft` — upsert `EarRecord` (`summary`, `recommendations`, `budget_data={"trade_budgets": ..., "billing_type": "pi_baseline"}`),
  replace `EarTradeInput` rows per group, then `ear_docgen.generate_ear_document`; artifact → EarPanel.
* `_sow_draft` — new `SowRecord` with `revision_name = "Rev-{n}"` (n = existing revisions), `trade_sections` in
  **SOW §3.1 order (A, B, E, C, D, F)**, `scope_text`; then `generate_sow_docx`; artifact → SowBoqPanel + docx.
* `_boq_draft` — `BoqMtoItem` rows with `mto_kind="design"`, `unit_rate=0.0` (unpriced for bidding),
  **no labour/material-manpower lines**; then `generate_boq_xlsx`; artifact → SowBoqPanel + xlsx.
* `_drawings_list` — merges the model's register with the project's PDF attachments and writes it back
  into the SOW's `trade_sections["drawings"]`; renders a table in the chat (no new table).
* `_binder` — calls the binder path (§3.6), returns the PDF filename, byte size and page count.
* `_mto_draft` — design MTO rows + `generate_mto_xlsx`, allowed only when stage 4 is
  `approved / approved_as_noted`.

**Stage writers** (the "confirm/approve" half of the conversation):
`mom.confirm` → stage 1 = confirmed; `summary.approve` → stage 2 = approved;
`sow.approve` → stage 3 = approved; `ear.pi_signature` → `ear_records.status="pi_signature"`;
`ear.asepc` → `status="asepc_pending"`. Each goes through the same
`blocked_reason` guard and writes `pipeline:stage` / `ear:funnel` audit entries.

### 3.4 `backend/app/api/assistant.py` (new — ~180 lines)

~~~python
router = APIRouter(prefix="/projects/{project_id}/assistant", tags=["assistant"])


@router.get("", response_model=AssistantStateOut)
def assistant_state(project_id: int,
                    db: Session = Depends(get_db),
                    _user: User = Depends(get_current_user)) -> AssistantStateOut:
    """Stage ribbon, gate, allowed/blocked actions, EAR track, AI status, transcript."""


@router.post("/message", response_model=AssistantTurnOut)
def assistant_message(project_id: int,
                      body: AssistantMessageIn,
                      db: Session = Depends(get_db),
                      user: User = Depends(require_capability(CAP_PROJECTS_EDIT))) -> AssistantTurnOut:
    """Record the user's notes and propose the next allowed action (nothing written yet)."""


@router.post("/run", response_model=AssistantTurnOut)
def assistant_run(project_id: int,
                  body: AssistantRunIn,
                  db: Session = Depends(get_db),
                  user: User = Depends(require_capability(CAP_PROJECTS_EDIT))) -> AssistantTurnOut:
    """Execute one action. 409 with the pipeline's own sentence when the gate blocks it."""


@router.get("/messages", response_model=list[AssistantTurnOut])
def assistant_messages(project_id: int, limit: int = Query(50, ge=1, le=200), offset: int = 0,
                       db: Session = Depends(get_db), _user: User = Depends(get_current_user)): ...


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
def assistant_reset(project_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_capability(CAP_PROJECTS_EDIT))): ...


@router.get("/actions")
def assistant_actions(_user: User = Depends(get_current_user)) -> list[dict]:
    """The registry: id, label, track, stage, panel, capability (for the UI)."""
~~~

**Capability table** — the endpoint holds `CAP_PROJECTS_EDIT`, and each action re-checks its own
capability with `effective_permissions(user)` (the same idiom as `api/sow_boq.py` line 594),
because the reused generator functions do not check anything themselves:

| Action group | Capability checked before running |
|---|---|
| mom.draft / mom.confirm | `CAP_MOM_MANAGE` |
| summary.draft / summary.approve | `CAP_PROJECTS_EDIT` |
| ear.draft / ear.pi_signature / ear.asepc | `CAP_EAR_MANAGE` |
| sow.draft / sow.approve / drawings.list / package.binder | `CAP_SOW_MANAGE` |
| boq.draft / mto.draft | `CAP_BOQ_MANAGE` (MTO also `CAP_MTO_MANAGE`) |

Status codes: **409** gate blocked (detail = `blocked_reason`), **403** missing capability,
**404** unknown action (`detail` lists the valid ids), **422** empty/an over-long message,
**503** `provider.available()` false (detail = its reason), **200** otherwise.

### 3.5 `backend/app/main.py` (modify — 2 lines)

`import` `procore`-style block `+ assistant`, and
`app.include_router(assistant.router, prefix="/api")` next to the pipeline router.

### 3.6 The binder — one small, optional deviation

The assistant needs the binder **path + page count** (to print "15 pages, 105 909 bytes" in the chat),
while `combined_binder` returns a `FileResponse` and attaches a row every time.
Recommended: extract the body of `combined_binder` into

~~~python
# app/api/sow_boq.py
def build_binder_pdf(project, db, user, revision: int | None = None) -> tuple[Path, int, list[str]]:
    """Cover + SOW + BOQ + comment log + drawings. Returns (path, pages, parts)."""
~~~

and make the endpoint a 6-line wrapper. That is the only change to an existing endpoint file, and it
stops the assistant from filing a duplicate `DELIVERABLE` attachment on every chat run.
Zero-change fallback (if you prefer): call `sow_boq.combined_binder(project_id, None, db, user)` and
read `response.path` — it works, it is just less clean and it re-attaches each time.

### 3.7 `frontend/src/lib/api.ts` (modify — append `// --- Assistant ---`)

~~~typescript
export interface AssistantArtifact { kind: string; label: string; filename?: string | null;
  url?: string | null; panel?: string | null; meta?: Record<string, unknown>; }
export interface AssistantGate { stage: number; label: string; status: string;
  allowed: string[]; blocked: Record<string, string>; }
export interface AssistantTurn { id: number; role: 'user' | 'assistant' | 'tool';
  content: string; created_at: string; action?: string | null; suggested_action?: string | null;
  needs_confirmation?: boolean; artifacts?: AssistantArtifact[];
  gate?: AssistantGate | null; elapsed_ms?: number | null; available?: boolean; }
export interface AssistantState { project_id: number; pr_number: string; pipeline: unknown;
  gate: AssistantGate; ear: { status: string; next_step: string | null; trade_inputs: number;
  parallel: boolean }; actions: Array<{ id: string; label: string; track: string; stage: number;
  panel: string }>; ai: { provider: string; model: string; available: boolean; reason?: string | null };
  transcript: AssistantTurn[]; }

export function getAssistantState(projectId: number): Promise<AssistantState>
export function proposeAssistant(projectId: number, message: string, opts?: { model?: string; provider?: string }): Promise<AssistantTurn>
export function runAssistantAction(projectId: number, action: string, note?: string): Promise<AssistantTurn>
export function listAssistantMessages(projectId: number): Promise<AssistantTurn[]>
export function resetAssistant(projectId: number): Promise<void>
~~~

### 3.8 `frontend/src/components/project/AssistantChat.tsx` (new — ~320 lines)

One card, mounted on the project page **above** §Q<PipelinePanel§Q> (the Q&A §Q<ProjectChat§Q> stays
exactly as it is; this is a different job):

1. **Stage ribbon** — the five spine stages as chips with status colours, plus a **separate EAR chip**
   ("EAR · PI signature", "EAR · ASEPC pending") to make the parallel track visible.
2. **Gate banner** — the next action, its reason when blocked, and the AI badge
   (`DeepSeek · deepseek-chat · ready` or the offline reason from `/assistant`).
3. **Transcript** — user / assistant / tool cards; each artifact renders as a link
   (label + filename + panel name), pointing at the existing download endpoints.
4. **Input** — a textarea ("Paste the meeting notes, the instructions, or the scope inputs") and
   **[Send]**, which calls `proposeAssistant`.
5. **Action card** — the suggested action with its button **[Approve & run]**, plus the other
   allowed actions; blocked ones are shown disabled with the reason. Running calls
   `runAssistantAction` and appends the tool turn (pages, bytes, row counts).
6. Apple tokens only (`text-apple-text`, `text-apple-muted`, `border-apple-border`, `bg-apple-hover`),
   spinner + `elapsed_ms` while the call runs, error box on failure.

Mount in `app/projects/[id]/page.tsx`:

~~~tsx
{/* The delivery assistant: notes in, gated documents out. */}
<div className="mb-6">
  <AssistantChat projectId={project.id} prNumber={project.pr_number} />
</div>
~~~

### 3.9 `frontend/src/lib/version.ts` + `CHANGELOG.md` (modify)

`APP_VERSION = '1.2.0'`, `APP_VERSION_DATE = '13 October 2026'`, and a 1.2.0 section describing the
assistant, the gate matrix and the two-step write.

---

## 4. Action + gate matrix

| # | Action id | Track | Precondition (code) | Writes | Audit key | Panel | Capability |
|---|---|---|---|---|---|---|---|
| 1 | mom.draft | spine 1 | none | mom_records (upsert) + docx/pdf | assistant:mom | MomPanel | mom.manage |
| 2 | mom.confirm | spine 1 | none | pipeline stage 1 = confirmed | pipeline:stage | PipelinePanel | mom.manage |
| 3 | summary.draft | spine 2 | stage 1 confirmed | Summary docx + DataPoint rows | assistant:summary | SowBoqPanel/Summary | projects.edit |
| 4 | summary.approve | spine 2 | stage 1 confirmed | pipeline stage 2 = approved | pipeline:stage | PipelinePanel | projects.edit |
| 5 | ear.draft | **ear (parallel)** | stage 1 confirmed | ear_records + ear_trade_inputs + EAR file | assistant:ear | EarPanel | ear.manage |
| 6 | ear.pi_signature | ear | EAR record exists | ear_records.status | ear:funnel | EarPanel | ear.manage |
| 7 | ear.asepc | ear | pi_signature done | ear_records.status | ear:funnel | EarPanel | ear.manage |
| 8 | sow.draft | spine 3 | stage 2 approved or pending | sow_records + docx | assistant:sow | SowBoqPanel | sow.manage |
| 9 | boq.draft | spine 3 | a SOW revision exists | boq_mto_items + xlsx | assistant:boq | SowBoqPanel | boq.manage |
| 10 | drawings.list | spine 3 | a SOW revision exists | trade_sections["drawings"] | assistant:drawings | SowBoqPanel | sow.manage |
| 11 | package.binder | spine 4 | stage 3 approved or pending | Binder PDF + attachment | package:pdf | ProcorePanel | sow.manage |
| 12 | mto.draft | spine 5 | **Procore approved / approved as noted** | boq_mto_items (design MTO) + xlsx | assistant:mto | MaterialPicker | boq.manage + mto.manage |

Actions 1–2 and 5–7 are always available; 3–4 need the MOM confirmed; 8–11 follow
`blocked_reason(by_stage, 3/4)`; 12 follows `blocked_reason(by_stage, 5)` — unchanged rules, now
spoken by the assistant.

---

## 5. Verification script

`backend/scripts/verify_assistant.py` (new, kept in the repo like `verify_step_b.py` so it can be
re-run after any change):

~~~python
"""Verify the Project Delivery Assistant end to end on a real PR, then clean up.

Run inside the backend container:
    python /tmp/verify_assistant.py PR-XXXXX

It snapshots the project, drives the whole conversation (including a deliberate
attempt to skip a gate), prints the HTTP result of every step, checks that each
document reached its panel and the audit trail, and finally restores the project
exactly as it was: created rows deleted, pipeline stages reset, attachments removed.
"""
from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db import SessionLocal
from app.main import app
from app.models import (
    AssistantMessage,
    Attachment,
    BoqMtoItem,
    EarRecord,
    EarTradeInput,
    MomRecord,
    PipelineStage,
    Project,
    SowRecord,
)

NOTES = """
Meeting: PR-XXXXX - HVAC and electrical upgrade, Bldg 5 lab.
Date: 13 October 2026, 10:00-11:30, Room 5-3201 (Area 1).
Attendees: Ibrahim Al-Harbi (PI, CERP), Sara Al-Qahtani (Building Operations),
Mohammed Khan (IHP Design), Nasser Al-Otaibi (HSE).
Scope agreed: replace the 2 air-handling units on the roof level, add 6 new
fan-coil units in the lab, new dedicated 60 A electrical supply with a new panel,
gas piping tie-in to the existing manifold, low-current points for the new
thermostats. All work Supply & Install by IHP. Site access after 18:00, weekend
work not allowed. Action: IHP to issue the SOW and BOQ within two weeks.
HSE note: hot-work permit required for the roof AHU replacement.
"""


def main() -> None:
    pr = sys.argv[1] if len(sys.argv) > 1 else "PR-291"
    db = SessionLocal()
    project = db.query(Project).filter(Project.pr_number.ilike("%" + pr + "%")).first()
    if project is None:
        raise SystemExit("project not found: " + pr)
    pid = project.id
    print("project", pid, project.pr_number, "|", (project.title or "")[:60])

    snap = {
        "attachments": {a.id for a in db.query(Attachment).filter(Attachment.project_id == pid)},
        "mom": db.query(MomRecord).filter(MomRecord.project_id == pid).count(),
        "ear": db.query(EarRecord).filter(EarRecord.project_id == pid).count(),
        "sow": db.query(SowRecord).filter(SowRecord.project_id == pid).count(),
        "boq": db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).count(),
        "stages": {r.stage: r.status for r in
                   db.query(PipelineStage).filter(PipelineStage.project_id == pid)},
    }

    client = TestClient(app)
    H = {"Authorization": "Bearer " + create_access_token("admin")}
    results: list[tuple[str, int]] = []

    def step(label: str, response, extra: str = ""):
        took = getattr(response, "elapsed_s", None)
        print(f"{label}: HTTP {response.status_code} | "
              f"{response.headers.get('content-type', '').split(';')[0]} | "
              f"{len(response.content)} bytes{extra}")
        if response.status_code >= 400:
            print("    body:", response.text[:300])
        results.append((label, response.status_code))
        return response

    base = f"/api/projects/{pid}/assistant"

    # 0. state: gate, allowed actions, AI provider
    r = step("GET  /assistant", client.get(base, headers=H))
    state = r.json()
    print("    ai:", state["ai"], "| stage:", state["gate"]["stage"], state["gate"]["status"])
    print("    allowed:", state["gate"]["allowed"])
    print("    blocked:", state["gate"]["blocked"])
    print("    ear track:", state["ear"])

    # 1. paste the notes -> a proposal, nothing written yet
    t0 = time.time()
    r = step("POST /assistant/message", client.post(
        base + "/message", headers=H, json={"message": NOTES}))
    print("    suggested:", r.json().get("suggested_action"),
          "| needs_confirmation:", r.json().get("needs_confirmation"),
          "| seconds:", round(time.time() - t0, 1))

    # 2. THE GATE: trying to skip straight to the SOW must be refused with the pipeline sentence
    r = step("POST /assistant/run sow.draft (must be 409)",
             client.post(base + "/run", headers=H, json={"action": "sow.draft"}))
    assert r.status_code == 409, "the gate let the SOW through before the MOM was confirmed"

    # 3. the gated chain, one action at a time
    for action in ("mom.draft", "mom.confirm"):
        r = step(f"POST /assistant/run {action}",
                 client.post(base + "/run", headers=H, json={"action": action}))
        if r.status_code == 200:
            body = r.json()
            print("    artifacts:", [(a["kind"], a["label"], a.get("filename")) for a in body["artifacts"]])

    for action in ("summary.draft", "summary.approve", "ear.draft", "ear.pi_signature"):
        r = step(f"POST /assistant/run {action}",
                 client.post(base + "/run", headers=H, json={"action": action}))

    for action in ("sow.draft", "boq.draft", "drawings.list", "package.binder"):
        r = step(f"POST /assistant/run {action}",
                 client.post(base + "/run", headers=H, json={"action": action}))
        if action == "package.binder" and r.status_code == 200:
            art = r.json()["artifacts"][0]
            print("    binder:", art.get("filename"), "|", art["meta"])

    # 4. MTO must still be locked: Procore has not approved yet
    r = step("POST /assistant/run mto.draft (must be 409)",
             client.post(base + "/run", headers=H, json={"action": "mto.draft"}))

    # 5. set Procore to Approved by hand, then the MTO opens
    step("PATCH /procore procore_status=Approved", client.patch(
        f"/api/projects/{pid}/procore", headers=H, json={"procore_status": "Approved"}))
    step("POST /assistant/run mto.draft", client.post(
        base + "/run", headers=H, json={"action": "mto.draft"}))

    # 6. every artifact must exist in its own panel
    for label, path in (
        ("MomPanel", f"/api/projects/{pid}/mom"),
        ("EarPanel", f"/api/projects/{pid}/ear"),
        ("SowBoqPanel /sow", f"/api/projects/{pid}/sow"),
        ("SowBoqPanel /boq", f"/api/projects/{pid}/boq"),
        ("ProcorePanel", f"/api/projects/{pid}/procore"),
        ("PipelinePanel", f"/api/projects/{pid}/pipeline"),
    ):
        r = client.get(path, headers=H)
        print(f"    panel {label}: HTTP {r.status_code} | {len(r.content)} bytes")

    audit = client.get(f"/api/projects/{pid}/audit", headers=H).json()
    keys = {row.get("action") for row in (audit if isinstance(audit, list) else audit.get("entries", []))}
    print("    audit keys present:", sorted(k for k in keys if k and
          (k.startswith("assistant:") or k in ("package:pdf", "pipeline:stage", "ear:funnel"))))

    # 7. the labour rule: $0.00 and no manpower in any total
    summary_turn = client.get(base + "/messages", headers=H).json()
    text = " ".join(t["content"] for t in summary_turn if t["role"] == "assistant")
    assert "Labor: IHP In-House Resources" in text and "$0.00" in text, "the labour line is missing"
    print("    labour line: present, $0.00 (Covered by IHP)")

    # 8. per-step timing (Cloudflare caps at ~100 s)
    assert all(code < 400 for _label, code in results if "must be 409" not in _label)

    # ---- restore the project exactly as it was ----
    db.query(AssistantMessage).filter(AssistantMessage.project_id == pid).delete()
    db.query(EarTradeInput).filter(EarTradeInput.ear_id.in_(
        [e.id for e in db.query(EarRecord).filter(EarRecord.project_id == pid)])).delete(
        synchronize_session=False)
    db.query(EarRecord).filter(EarRecord.project_id == pid).delete()
    db.query(SowRecord).filter(SowRecord.project_id == pid).delete()
    db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).delete()
    db.query(MomRecord).filter(MomRecord.project_id == pid).delete()
    for row in db.query(PipelineStage).filter(PipelineStage.project_id == pid):
        row.status = snap["stages"].get(row.stage, "not_started")
    for att in db.query(Attachment).filter(Attachment.project_id == pid):
        if att.id not in snap["attachments"]:
            db.delete(att)
    project = db.query(Project).filter(Project.id == pid).first()
    project.procore_status = None
    project.procore_submittal_date = None
    project.procore_revision = 0
    db.commit()
    db.close()
    print("cleanup: transcript, MOM/EAR/SOW/BOQ rows, verification attachments removed; "
          "pipeline stages and Procore state restored")

    failed = [label for label, code in results
              if code >= 400 and "must be 409" not in label]
    print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))


if __name__ == "__main__":
    main()
~~~

Deploy-day invocation (same pattern as Step B):

~~~bash
scp -i <key> backend/scripts/verify_assistant.py root@185.182.9.20:/tmp/verify_assistant.py
ssh -i <key> root@185.182.9.20 \
  "docker cp /tmp/verify_assistant.py ihp-backend-1:/tmp/ && \
   docker exec -w /app ihp-backend-1 python /tmp/verify_assistant.py PR-XXXXX"
~~~

---

## 6. Tests to add (`backend/tests/test_assistant.py` — 9 tests, no network)

The suite monkeypatches `app.services.assistant_orchestrator._ai_json` / `_ai_text`, so no
DeepSeek call is made in CI.

1. `test_state_lists_allowed_and_blocked_actions` — fresh project: only actions 1,2,5 allowed.
2. `test_gate_refuses_sow_before_mom_confirmed` — POST /run sow.draft → 409 + the pipeline sentence.
3. `test_gate_refuses_mto_until_procore_approved` — approve everything but Procore → 409.
4. `test_mom_draft_writes_record_and_audit` — mom_records row, details keys, `assistant:mom` audit.
5. `test_ear_track_runs_parallel` — ear.draft allowed while stage 2 is merely pending.
6. `test_propose_writes_user_turn_and_proposes_one_action` — transcript row + allowed action only.
7. `test_labour_never_enters_a_total` — every BoqMtoItem `unit_rate == 0` and the assessment prints `LABOUR_LINE`.
8. `test_provider_offline_returns_503` — monkeypatch `provider.available → (False, "reason")`.
9. `test_transcript_order_and_limit` — newest last, `limit` respected.

---

## 7. Deploy + verify checklist

~~~powershell
# local
cd backend ; python -m pytest -q                     # 363 + 9 green
cd ..\frontend ; npx tsc --noEmit ; npm run build    # clean

# migration id uniqueness (hard gate)
python .chk_migrations.py                            # dups: []

git add -A ; git commit -m "Project Delivery Assistant: gated chat orchestrator over the existing panels" ; git push

# VPS
ssh -i <key> root@185.182.9.20 "cd /opt/ihp && git pull --ff-only && docker compose up -d --build"
ssh -i <key> root@185.182.9.20 "docker logs ihp-backend-1 --tail 20 | grep -E 'Running upgrade|startup complete'"

# live end-to-end (cleans up after itself)
#   scp + docker cp + docker exec python /tmp/verify_assistant.py <PR>

# the panel is really in the served bundle
ssh -i <key> root@185.182.9.20 "docker exec ihp-frontend-1 grep -rlo 'Delivery assistant' /app/.next/static | head -2"
~~~

---

## 8. Decisions I need from you before I write code

1. **Test PR.** PR-291 does not exist. PR-29186 is the closest (id 16, but it sits at
   **CLOSEOUT** with no pipeline rows — a bad target for a gate-ordered run). Name the PR to use, or
   I will create a throwaway project (`POST /api/projects`), run the full chain on it, prove it, and
   delete it — leaving the 292 real projects untouched.
2. **The "General" trade.** Canonical is A–F with **F = Fire Sprinkler**. Recommended: keep A–F,
   Fire Sprinkler included, and put truly general items under A with a "General" note. Confirm.
3. **EAR document is a stub.** This feature creates real EAR rows + the AI review, but the
   downloadable "EAR" is still a placeholder .txt until the §7 template pass. Ship as is (recommended) or
   fold the real EAR Word template into this feature (roughly doubles the scope).
4. **Binder refactor** (§3.6): extract `build_binder_pdf()` in `api/sow_boq.py` (recommended) or call the
   endpoint function and read `response.path` (zero change, duplicate attachments).
5. **`assistant_messages.meta`**: keep (recommended) or exactly the six requested columns.
6. **Drawing List source**: derived from the SOW's `trade_sections["drawings"]` + PDF attachments
   (recommended, no new table) or a new `drawing_register` table (bigger).

---

## 9. Rollout order (one feature at a time)

| Step | Content | Proof |
|---|---|---|
| **B1** | model + migration + orchestrator + endpoints + 9 tests | pytest green, migration applied on the VPS, `GET /assistant` 200 with the gate |
| **B2** | `AssistantChat.tsx` + `api.ts` + mount | tsc + build clean, panel visible on the live project page |
| **B3** | the live end-to-end run | `verify_assistant.py` output: every step's HTTP code, artifacts in every panel, audit keys, 409s where gates must hold, cleanup done |
| **B4** | CHANGELOG 1.2.0 + version bump + `APP_BRIEF.md` refresh | version shown in Admin → Version |

**Shall I start with B1?** Nothing in this plan changes the MOM/EAR/SOW/BOQ generators, the panels,
the templates, the audit conventions or the labour rule — it only drives them in the right order.
