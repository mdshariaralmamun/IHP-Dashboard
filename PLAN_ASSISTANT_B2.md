# Implementation plan — B2: the delivery assistant UI (+ MOM agenda fix)

**Target:** live app https://ihp.shariar.dev · B1 backend already shipped and verified
**Scope:** the panel, the typed client, the mount, the MOM agenda fallback, 1.2.0 changelog. **No new migration.**

---

## 0. Grounding facts (checked before planning)

| Check | Result |
|---|---|
| B1 endpoints | live: `GET ""`, `POST /message`, `POST /run`, `GET /messages`, `DELETE /messages`, `GET /actions` — all under `/api/projects/{project_id}/assistant` |
| AssistantTurn shape | id, role, content, created_at, action, suggested_action, needs_confirmation, artifacts[], gate, elapsed_ms, available |
| Actions in the registry | **13**: mom.draft, mom.confirm, summary.draft, summary.approve, ear.draft, ear.pi_signature, ear.asepc, sow.draft, boq.draft, drawings.list, sow.approve, package.binder, mto.draft |
| Capability per action | returned by `GET /actions` as `capability` (mom.manage, projects.edit, ear.manage, sow.manage, boq.manage) |
| Pipeline rows today | only PR-12864 has rows (stage 1 `in_progress`); the other **291 projects have none**, so `_rows()` creates them read-only and every one of them shows stage 1 `not_started`, allowed `[mom.draft, mom.confirm]` |
| Existing chat pattern | `ProjectChat.tsx` — `useState` turns, `aiChat()` via the typed client, `VisualCard` wrapper, no hard-coded colours |
| Capabilities in the UI | `useUser()` → `{ user, loading }` and `canDo(user, cap): boolean` (frontend/src/lib/useUser.ts) |
| VisualCard | `{ title, subtitle, actions, children }` (frontend/src/components/powerbi/PowerBI.tsx) |
| Project page mount area | NextStepCard block ends line ~260; PipelinePanel block lines 262-265; ProjectChat block 273-276; page has `load` already passed to NextStepCard as `onChanged` |
| **MOM detail keys the template reads** | `meeting_title`, `meeting_location`, `meeting_date`, `meeting_time`, `meeting_number`, `attendees[]`, `agenda[]` (item keys: scope/description, trade, action, etc, responsible) — **B1's instruction asked for date/location/time**, so those three were dropped unless the model guessed |
| MOM empty-agenda behaviour | `build_mom_context` already falls back to **one** row (project.description or title, action "IHP"); B1's artifact printed the *raw* `details["agenda"]` (0), which is why it *looked* empty |

So B2 has three real defects to fix in the MOM path: **key aliases**, **no per-scope-point agenda**, and **the report reading the raw details instead of the built context**.

---

## 1. File-by-file

### 1.1 `frontend/src/lib/api.ts` (modify — append a `// --- Delivery assistant ---` block)

Six methods, typed payloads matching the live B1 responses, all through `request<T>()` (bearer token, 401 handling, FastAPI `detail` surfaced as `ApiError.message`):

~~~typescript
export interface AssistantArtifact {
  kind: string;                     // docx | xlsx | zip | pdf | record | table
  label: string;
  filename?: string | null;
  url?: string | null;              // an existing download endpoint
  panel?: string | null;            // MomPanel | EarPanel | SowBoqPanel | ...
  meta?: Record<string, unknown>;
}

export interface AssistantGate {
  stage: number;
  label: string;
  status: string;
  allowed: string[];
  blocked: Record<string, string>;  // action id -> the pipeline's own reason
}

export interface AssistantEarTrack {
  status: string;
  next_step: string | null;
  trade_inputs: number;
  parallel: boolean;
}

export interface AssistantAiStatus {
  provider: string;
  model: string;
  available: boolean;
  reason?: string | null;
}

export interface AssistantTurn {
  id: number;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  created_at: string;
  action?: string | null;
  suggested_action?: string | null;
  needs_confirmation?: boolean;
  artifacts?: AssistantArtifact[];
  gate?: AssistantGate | null;
  elapsed_ms?: number | null;
  available?: boolean;
}

export interface AssistantActionInfo {
  id: string;
  label: string;
  track: 'spine' | 'ear';
  stage: number;
  panel: string;
  capability: string;
  precondition: string | null;
}

export interface AssistantState {
  project_id: number;
  pr_number: string;
  pipeline: unknown;                // the five-stage payload, already rendered by PipelinePanel
  gate: AssistantGate;
  ear: AssistantEarTrack;
  actions: AssistantActionInfo[];
  ai: AssistantAiStatus;
  transcript: AssistantTurn[];
}

/** GET /api/projects/{id}/assistant — gate, EAR track, actions, transcript. */
export function getAssistantState(projectId: number): Promise<AssistantState> {
  return request<AssistantState>(`/api/projects/${projectId}/assistant`);
}

/** POST /api/projects/{id}/assistant/message — paste notes, get the next step. */
export function proposeAssistant(
  projectId: number,
  message: string,
  opts: { model?: string; provider?: string } = {},
): Promise<AssistantTurn> {
  return request<AssistantTurn>(
    `/api/projects/${projectId}/assistant/message`,
    { method: 'POST' },
    { message, model: opts.model ?? null, provider: opts.provider ?? null },
  );
}

/** POST /api/projects/{id}/assistant/run — execute one action (409 = gate). */
export function runAssistantAction(
  projectId: number,
  action: string,
  note?: string,
  opts: { model?: string; provider?: string } = {},
): Promise<AssistantTurn> {
  return request<AssistantTurn>(
    `/api/projects/${projectId}/assistant/run`,
    { method: 'POST' },
    { action, note: note ?? null, model: opts.model ?? null, provider: opts.provider ?? null },
  );
}

/** GET /api/projects/{id}/assistant/messages — the transcript, oldest first. */
export function listAssistantMessages(projectId: number): Promise<AssistantTurn[]> {
  return request<AssistantTurn[]>(`/api/projects/${projectId}/assistant/messages`);
}

/** DELETE /api/projects/{id}/assistant/messages — clear the transcript. */
export function resetAssistant(projectId: number): Promise<void> {
  return request<void>(`/api/projects/${projectId}/assistant/messages`, { method: 'DELETE' });
}

/** GET /api/projects/{id}/assistant/actions — the registry (id, label, capability). */
export function listAssistantActions(projectId: number): Promise<AssistantActionInfo[]> {
  return request<AssistantActionInfo[]>(`/api/projects/${projectId}/assistant/actions`);
}
~~~

(That is exactly the six endpoints requested, with `/actions` taking the project id because it shares the router prefix.)

### 1.2 `frontend/src/components/project/AssistantChat.tsx` (new)

~~~typescript
'use client';

interface Props {
  projectId: number;
  prNumber: string;
  /** Refresh the project page after a run so the other panels show the new document. */
  onChanged?: () => void;
}
export default function AssistantChat({ projectId, prNumber, onChanged }: Props) — ~360 lines
~~~

**State**

| State | Type | Purpose |
|---|---|---|
| `state` | AssistantState \| null | gate, EAR track, action registry, AI status |
| `turns` | AssistantTurn[] | transcript rendered in the window (seeded from state.transcript) |
| `input` | string | the textarea (notes / instructions) |
| `note` | string | optional note passed with the next run |
| `busy` | 'propose' \| string \| null | per-button spinner (`'propose'` or the action id) |
| `error` | string \| null | API message (incl. a 409 sentence) |
| `notice` | string \| null | "MOM v2 drafted…" confirmation |
| `lastResult` | AssistantTurn \| null | the inline result card (doc, version, panels, audit key) |
| `showAll` | boolean | show every action vs only the allowed + next ones |
| `suggested` | string \| null | the action returned by /message |

**Behaviour**

1. `useEffect(load, [projectId])` → `getAssistantState`; `setTurns(state.transcript)`.
2. Header: `VisualCard title={'Delivery assistant — ' + prNumber}`, subtitle = the gate line
   (`Stage 2 · Project Summary / EAR & Cost Estimate · not_started`) plus an AI badge
   (`DeepSeek · deepseek-chat · ready` / the `ai.reason` when unavailable) and a `Reset` button.
3. **Gate block** at the top: the five spine stages as chips (status colour map identical to
   §Q<PipelinePanel§Q>'s `STATUS_STYLE`), then a separate **EAR chip** ("EAR · asepc_pending · beside the
   spine") to make the parallel track visible.
4. **Chat window**: user turns right-aligned card, assistant turns plain, tool turns with a green left
   border; each artifact renders as a row (`[kind] label · filename · panel`) linking to `artifact.url`.
   Autoscroll on append (`boxRef.scrollTo`, like ProjectChat).
5. **Composer**: `<textarea rows={6}>` placeholder "Paste the meeting notes, the instructions or the
   scope inputs", `[Propose]` button (calls `proposeAssistant`), disabled while empty/busy.
6. **Action list** (`state.actions`): group by track (spine / EAR); each row shows the label, the
   stage, and
   * an enabled `[Run]` when `action.id` is in `gate.allowed` **and** `canDo(user, capability)`;
   * a disabled button with the reason sentence when `gate.blocked[action.id]` exists (title attribute
     + visible muted text) — the user sees exactly what the pipeline would say;
   * a locked note when the capability is missing ("needs mom.manage").
   The `suggested_action` is highlighted as "next step" and hoisted to the top.
7. `run(actionId)`: `runAssistantAction` → append the tool turn to `turns`, set `lastResult`,
   then `load()` + `onChanged?.()` so MomPanel / EarPanel / SowBoqPanel / PipelinePanel refresh.
   A thrown `ApiError` (409/403/503) becomes the visible error line — never a silent failure.
8. `Reset` → `resetAssistant` → clear `turns` (documents stay).
9. Colours: Apple tokens only — `text-apple-text`, `text-apple-muted`, `border-apple-border`,
   `bg-apple-hover`; status chips reuse the light/emerald/blue/amber/red classes PipelinePanel uses.

### 1.3 `frontend/src/app/projects/[id]/page.tsx` (modify — mount above PipelinePanel)

~~~tsx
import AssistantChat from '@/components/project/AssistantChat';
...
            {/* The delivery assistant: paste the notes, the documents come out
                in gate order. Above the pipeline so it is the first thing the
                team sees on any project. */}
            <div className="mb-6">
              <AssistantChat
                projectId={project.id}
                prNumber={project.pr_number}
                onChanged={load}
              />
            </div>

            {/* The five-stage delivery spine: one row per milestone gate. */}
            <div className="mb-6">
              <PipelinePanel projectId={project.id} />
            </div>
~~~

Inserted between the NextStepCard block (ends ~line 260) and the PipelinePanel block (starts ~line 262).
No hard-coded id: `project.id` / `project.pr_number` come from the route, exactly like the other panels,
so the panel appears on all 292 projects.

### 1.4 `backend/app/services/assistant_orchestrator.py` (modify — MOM agenda, no new endpoint, no migration)

Three changes, all inside the MOM path.

**(a) Key aliases + guaranteed rows.** New helper used by `_mom_draft`:

~~~python
_MOM_ALIASES = (
    ("date", "meeting_date"),
    ("location", "meeting_location"),
    ("time", "meeting_time"),
    ("title", "meeting_title"),
)


def _clean_agenda(value: Any) -> list[dict]:
    rows = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope") or item.get("description") or "").strip()
        if not scope:
            continue
        rows.append({
            "scope": scope,
            "trade": str(item.get("trade") or "").strip(),
            "action": str(item.get("action") or "").strip(),
            "responsible": str(item.get("responsible") or "").strip(),
            "etc": str(item.get("etc") or "").strip(),
        })
    return rows


def _mom_details(data: dict, source_text: str | None) -> tuple[dict, str]:
    """Normalise the model's MOM JSON: template keys and at least one agenda row.

    Returns (details, how the agenda was produced) so the report can say which
    path was taken: "model", "notes" or "project".
    """
    details = {k: v for k, v in (data or {}).items() if v not in (None, [], {})}
    for alias, key in _MOM_ALIASES:
        if not details.get(key) and details.get(alias):
            details[key] = details[alias]
    agenda = _clean_agenda(details.get("agenda"))
    source = "model"
    if not agenda:
        agenda = _agenda_from_notes(source_text)
        source = "notes"
    if not agenda:
        agenda = [{
            "scope": (project_description_or_title_fallback),
            "trade": "",
            "action": "IHP to confirm the scope and the trades",
            "responsible": "IHP",
            "etc": "",
        }]
        source = "project"
    details["agenda"] = agenda
    return details, source
~~~

**(b) The deterministic fallback** — one row per scope point in the pasted prose:

~~~python
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
_ACTION_HINT = re.compile(
    r"\b(action|actions|responsible|to be (?:issued|confirmed|submitted)|"
    r"\b(?:ihp|pi|hse|operations|fmom|ctps)\s+to\b|to issue|to confirm|to submit|"
    r"to finalise|to finalize|to provide)\b",
    re.I,
)
_ACTOR = re.compile(r"\b(IHP|PI|HSE|Building Operations|FMOM|CTPS|Proponent)\b", re.I)
_SCOPE_HINT = re.compile(
    r"\b(scope|agreed|works?|installation|install|replace|replacement|upgrade|"
    r"supply|provide|new |tie[- ]in|remove|relocat|repair|testing|commission)\b",
    re.I,
)
_TRADE_HINT = (
    ("Civil / Architectural", ("civil", "architect", "trench", "concrete", "penetrat")),
    ("Electrical", ("electric", "panel", "cable", "earthing", "bonding", "power supply")),
    ("Low Current", ("low current", "telecom", "bms", "detection", "scada", "cctv", "tgm")),
    ("Plumbing", ("plumb", "gas", "pipe", "valve", "water", "drain")),
    ("HVAC", ("hvac", "duct", "ahu", "fcu", "ventilation", "chiller")),
    ("Fire Sprinkler", ("sprinkler", "fire", "hot work", "fire-stop", "fire stop")),
)


def _agenda_from_notes(source_text: str | None) -> list[dict]:
    """One agenda row per scope point when the model returned none.

    Bullet / numbered lines win; otherwise sentences are used. A point that
    speaks about an action keeps it, the actor becomes the responsible party,
    and the trade is inferred from the vocabulary so the MOM still sorts
    trade-wise.
    """
    text = (source_text or "").strip()
    if not text:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    points = [ _BULLET.sub("", line).strip() for line in lines if _BULLET.match(line) ]
    if not points:
        points = [p.strip() for p in re.split(r"(?<=[.!?])\s+", " ".join(lines)) if p.strip()]
    rows, seen = [], set()
    for point in points:
        if len(point) < 15 or point.lower().startswith(("meeting", "date:", "attendees")):
            continue
        if not (_SCOPE_HINT.search(point) or _ACTION_HINT.search(point)):
            continue
        key = point.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        actor = _ACTOR.search(point)
        trade = next((name for name, words in _TRADE_HINT if any(w in point.lower() for w in words)), "")
        rows.append({
            "scope": point,
            "trade": trade,
            "action": point if _ACTION_HINT.search(point) else "",
            "responsible": actor.group(1) if actor else "",
            "etc": "",
        })
    return rows[:12]
~~~

**(c) Pass the source text in and report truthfully.** `run_action` resolves the text once and hands it
to the writer (all writers accept the new optional kwarg; the 13-action registry, preconditions and
audit keys are untouched):

~~~python
source_text = note or (db.scalars(
    select(AssistantMessage)
    .where(AssistantMessage.project_id == project.id, AssistantMessage.role == "user")
    .order_by(AssistantMessage.id.desc())
).first() or AssistantMessage()).content
...
result = action.writer(db, project, user, data, model=model, provider_id=provider_id,
                       source_text=source_text)
~~~

and `_mom_draft` now reports what the document actually contains:

~~~python
details, agenda_source = _mom_details(data, source_text)
...
context = mom_api.build_mom_context(project, details, version)
...
agenda_rows = len(context["agenda"])          # the built, trade-sorted agenda
summary = (f"MOM v{version} drafted from your notes: {agenda_rows} agenda item(s) "
           f"({agenda_source}), {len(context['attendees'])} attendee(s). "
           "It is in the MOM panel, ready for you to confirm.")
artifact("table", "MOM agenda", ..., {"agenda": context["agenda"][:15], ...})
~~~

Also tightened in the same edit — the `mom.draft` instruction now names the template keys and demands
one row per scope point:

~~~
Turn the team's notes into the KAUST MOM fields. Use these exact keys:
{"meeting_title": ..., "meeting_location": ..., "meeting_date": "YYYY-MM-DD",
 "meeting_time": "10:00-11:30", "meeting_number": "01",
 "attendees": [{"name": ..., "title": ..., "email": ""}],
 "agenda": [{"scope": ..., "trade": ..., "action": ..., "responsible": ..., "etc": ...}]}
Prose notes are normal: split them into ONE agenda row per scope point
(one per trade where a trade is mentioned). Never return an empty agenda.
~~~

### 1.5 `frontend/src/lib/version.ts` + `CHANGELOG.md` (modify)

`APP_VERSION = '1.2.0'`, `APP_VERSION_DATE = '14 October 2026'`; a 1.2.0 section: the delivery
assistant panel, the two-step propose/run flow, the gate display, the EAR parallel track, the MOM
agenda/key fix, and the three B1 fixes recorded (sow.approve, hand-set Procore status unlocking the
MTO, BOQ fallback + the `deliverables/` folder fix) — the last three are already deployed, so they belong
in 1.2.0's notes.

### 1.6 No migration

`assistant_messages` (20261013_1000) already covers everything. The migration-id duplicate check still
runs before deploy, unchanged: 26 revisions, no duplicates (verified today).

---

## 2. Tests to add (`backend/tests/test_assistant.py` — 4 tests, total 381)

1. `test_mom_agenda_from_prose_notes` — the model returns `{"agenda": []}` with prose notes; the run
   reports ≥1 agenda row, the `mom_records.details["agenda"]` is non-empty, and every row has a
   `scope`. (Monkeypatch `_ai_json` to drop the agenda.)
2. `test_mom_agenda_splits_prose_into_scope_points` — unit test on `_agenda_from_notes`: 5 points of
   a realistic paragraph → ≥3 rows, the gas/pipe point tagged **Plumbing**, the "Action: IHP to issue the
   SOW" point carrying `responsible == "IHP"`.
3. `test_mom_detail_aliases_are_normalised` — model answers `date/location/time/title`; the stored
   details expose `meeting_date/meeting_location/meeting_time/meeting_title`.
4. `test_assistant_actions_endpoint_lists_the_registry` — `GET /actions` → 13 rows with ids,
   panels and capabilities (this is what the UI greys out from).

Existing 377 must stay green (`python -m pytest -q`).

---

## 3. Live verification script — `backend/scripts/verify_assistant_ui.py`

Proves the UI's own path: **public HTTPS + a real admin JWT**, i.e. exactly what the browser does
(Cloudflare → Next proxy → FastAPI), on **two different real PRs**, and cleans up after itself.

~~~python
"""Verify the B2 delivery-assistant UI end to end, then leave the app as it was.

Run inside the backend container:
    python /tmp/verify_assistant_ui.py PR-12864

What it proves
  1. the panel's own API is reachable through the PUBLIC URL with a real admin JWT
  2. the project page serves (200) and the built bundle contains the panel
  3. paste notes -> Propose -> a suggested action comes back
  4. Run on a blocked action -> 409 with the pipeline's sentence
  5. the real write chain on a THROWAWAY project (nothing else is touched)
  6. the same script on a SECOND real PR proves it is generic, not 12864-specific
  7. cleanup: throwaway project, rows, attachments and the PR-12864 transcript
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db import SessionLocal
from app.models import (
    AssistantMessage, Attachment, AuditLog, BoqMtoItem, EarRecord, EarTradeInput,
    MomRecord, PipelineStage, Project, SowRecord,
)

BASE = "https://ihp.shariar.dev"
NOTES = """ ... the same realistic gas-line prose notes ... """


def api(method: str, path: str, token: str, body: dict | None = None):
    """One call through the public URL - the same path the browser takes."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            ctype = resp.headers.get("content-type", "").split(";")[0]
            return resp.status, ctype, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, exc.headers.get("content-type", "").split(";")[0], raw


def show(label, status, ctype, raw, extra=""):
    print(f"{label}: HTTP {status} | {ctype} | {len(raw)} bytes{extra}")
    if status >= 400:
        print("    body:", raw[:200].decode(errors="replace"))
    return raw


def first_project(db, excluded: int) -> Project:
    """The second PR, chosen by data (never hard-coded): newest real PR with a PI."""
    return (db.query(Project)
            .filter(~Project.pr_number.like("PR-AS-%"), Project.id != excluded,
                    Project.pi_email.isnot(None), Project.pi_name.isnot(None))
            .order_by(Project.id.desc()).first())


def main() -> None:
    pr = sys.argv[1] if len(sys.argv) > 1 else "PR-12864"
    token = create_access_token("admin")
    db = SessionLocal()
    results = []

    real = db.query(Project).filter(Project.pr_number.ilike("%" + pr.replace("PR-", "") + "%")).first()
    second = first_project(db, real.id)
    print("real PR:", real.pr_number, "(id", real.id, ") | second PR:", second.pr_number,
          "(id", second.id, ")")

    # 1 + 2. the panel path and the page, on BOTH projects
    for project in (real, second):
        status, ctype, raw = api("GET", f"/api/projects/{project.id}/assistant", token)
        show(f"GET /assistant ({project.pr_number})", status, ctype, raw)
        state = json.loads(raw)
        assert state["pr_number"] == project.pr_number, "the panel is not bound to this project"
        print("    gate:", state["gate"]["stage"], state["gate"]["status"],
              "| allowed:", state["gate"]["allowed"], "| blocked:", len(state["gate"]["blocked"]))
        print("    ai:", state["ai"], "| actions:", len(state["actions"]))
        status, ctype, raw = api("GET", f"/api/projects/{project.id}/assistant/actions", token)
        show(f"GET /actions ({project.pr_number})", status, ctype, raw)
        assert len(json.loads(raw)) == 13
        codes = []
        for action in ("sow.draft", "mto.draft"):
            status, ctype, raw = api("POST", f"/api/projects/{project.id}/assistant/run",
                                     token, {"action": action})
            show(f"POST /run {action} ({project.pr_number}, must be 409)", status, ctype, raw)
            codes.append(status)
        assert codes == [409, 409], "a gate let something through on a real project"
        t0 = time.time()
        status, ctype, raw = api("POST", f"/api/projects/{project.id}/assistant/message",
                                 token, {"message": NOTES})
        show(f"POST /message ({project.pr_number})", status, ctype, raw,
             f" | {round(time.time() - t0, 1)}s to propose")
        turn = json.loads(raw)
        print("    suggested:", turn["suggested_action"], "| needs_confirmation:",
              turn["needs_confirmation"])
        status, ctype, raw = api("GET", f"/api/projects/{project.id}/assistant/messages", token)
        show(f"GET /messages ({project.pr_number})", status, ctype, raw,
             f" | {len(json.loads(raw))} turns")
        # leave the real PRs exactly as they were
        db.query(AssistantMessage).filter(AssistantMessage.project_id == project.id).delete()
        db.commit()

    # 3. the served page and the built bundle
    status, ctype, raw = api("GET", f"/projects/{real.id}", token)
    show("GET /projects/<id> (page)", status, ctype, raw)

    # 4. the real write chain on a throwaway project, through the public URL
    pr_new = "PR-AS-UI-" + uuid.uuid4().hex[:6].upper()
    created = db_project_from_api(...)      # POST /api/projects through the public URL
    ...
    chain = ("mom.draft", "mom.confirm", "summary.draft", "summary.approve",
             "ear.draft", "ear.pi_signature", "ear.asepc", "sow.draft", "boq.draft",
             "drawings.list", "sow.approve", "package.binder")
    for action in chain:
        t0 = time.time()
        status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/run", token,
                                 {"action": action})
        turn = json.loads(raw) if status < 400 else {}
        show(f"POST /run {action}", status, ctype, raw, f" | {round(time.time() - t0, 1)}s")
        for art in turn.get("artifacts", []):
            print("     artifact:", art["kind"], "|", art["label"], "|", art.get("filename"),
                  "|", art.get("panel"), "|", art.get("meta"))
    # MOM agenda proof: the run above used PROSE notes
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    agenda = (mom.details or {}).get("agenda") or []
    print("    MOM agenda rows from prose notes:", len(agenda),
          "| trades:", sorted({a.get("trade") for a in agenda if a.get("trade")}))
    assert len(agenda) >= 3, "prose notes still produce no agenda rows"
    # MTO stays locked until the hand-set Procore status
    status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/run", token, {"action": "mto.draft"})
    show("POST /run mto.draft (must be 409)", status, ctype, raw)
    status, ctype, raw = api("PATCH", f"/api/projects/{pid}/procore", token,
                             {"procore_status": "Approved"})
    show("PATCH /procore Approved", status, ctype, raw)
    status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/run", token, {"action": "mto.draft"})
    show("POST /run mto.draft", status, ctype, raw)

    # 5. the labour rule and the panels
    turns = json.loads(api("GET", f"/api/projects/{pid}/assistant/messages", token)[2])
    text = " ".join(t["content"] for t in turns)
    print("    labour line present:", "Labor: IHP In-House Resources" in text and "$0.00" in text)
    for label, path in (("MomPanel", f"/api/projects/{pid}/mom/defaults"),
                        ("EarPanel", f"/api/projects/{pid}/ear"),
                        ("/sow", f"/api/projects/{pid}/sow"),
                        ("/boq", f"/api/projects/{pid}/boq"),
                        ("ProcorePanel", f"/api/projects/{pid}/procore"),
                        ("PipelinePanel", f"/api/projects/{pid}/pipeline"),
                        ("AuditTrail", f"/api/projects/{pid}/audit")):
        status, ctype, raw = api("GET", path, token)
        show("    panel " + label, status, ctype, raw)

    # 6. cleanup (audit_logs first: it is a real FK)
    ... delete EarTradeInput/EarRecord/SowRecord/BoqMtoItem/MomRecord/PipelineStage/
        AssistantMessage/Attachment/AuditLog/Project for the throwaway PR ...
    shutil.rmtree(Path(get_settings().DATA_DIR) / "projects" / pr_new, ignore_errors=True)

    failed = [label for label, code, _ in results if code >= 400 and "must be 409" not in label]
    print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))


if __name__ == "__main__":
    main()
~~~

Plus two shell checks on the VPS:

~~~bash
# the panel is in the bundle the browser is served
docker exec ihp-frontend-1 grep -rlo "Delivery assistant" /app/.next/static | head -3
# the page compiles and serves
curl -s -o /dev/null -w "live page: %{http_code}\n" https://ihp.shariar.dev/projects/291
~~~

**Why two PRs proves genericity:** both real PRs are driven with no id baked into the script beyond the
one passed on the command line; the second is chosen from the database (newest real PR with a PI,
excluding PR-12864). The assertions check `state["pr_number"] == project.pr_number` on each, plus the
409s, so a hard-coded project would fail the second run.

---

## 4. Working order (local proof → deploy → verify)

| Step | Command | Expected |
|---|---|---|
| 1 | `cd backend ; python -m pytest -q` | **381 passed** |
| 2 | `cd frontend ; npx tsc --noEmit` | clean |
| 3 | `npm run build` | clean, `/projects/[id]` route rebuilt |
| 4 | migration ids | 26 revisions, `dups: []` (unchanged) |
| 5 | `git add -A && git commit && git push origin main` | pushed |
| 6 | VPS `cd /opt/ihp && git pull --ff-only && docker compose up -d --build` | ~4 min |
| 7 | `docker logs ihp-backend-1 --tail 20` | "Application startup complete" |
| 8 | `scp` + `docker cp` + `docker exec python /tmp/verify_assistant_ui.py PR-12864` | `SUMMARY: ALL OK` |
| 9 | bundle grep + live page curl | panel string found, page 200 |
| 10 | hygiene query | 292 projects, no `PR-AS-%` leftovers, PR-12864 transcript 0 |

---

## 5. What will not change

The 13-action registry, every precondition, every audit key, the rejected 409 sentences, the labour
line, the hand-set Procore status, requester-approves/PI-funds, the MTO gate, the existing panels and
templates, and the Apple colour tokens. B2 adds a panel and fixes the MOM's own content; it does not
touch B1's verified behaviour.

**Shall I build it?** On your word I will go file-by-file in the order §1.1 → §1.4, run the suite, then
deploy and bring back the two-PR verification output.
