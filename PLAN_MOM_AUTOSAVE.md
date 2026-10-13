# Investigation + implementation plan — MOM autosave (app 1.2.1)

## 1. What MomPanel.tsx does on input today — **it calls nothing**

Every input handler writes to React state and stops there:

| UI field | Handler (frontend/src/components/project/MomPanel.tsx) | What it does |
|---|---|---|
| Meeting Title / Location / Number / Date / Time / Organizer | `onChange={updateMeeting(field)}` line 608 → `setMeeting(...)` lines 495-498 | local state only |
| Attendee name / title / email | `onChange={(e) => updateAttendee(i, 'name', ...)}` lines 665-683 → `setAttendees` line 519 | local state only (the email is also proposed on blur from the directory) |
| Existing agenda rows (trade / scope / action / ETC) | `updateAgenda(i, field, value)` lines 744-795 → `setAgenda` line 525 | local state only |
| New agenda item | `setNewItem` lines 845-867 | local state only, saved by the **Add** button |
| Invitation textarea | `setInvitation(e.target.value)` line 632 | local state only |

The **only** writes the panel performs are explicit button actions, all wrapped in `run()` (line 406):

* `POST /api/projects/{id}/mom/generate` — the **Generate** button (line 437), which renders a new document and **bumps the version**;
* `POST /mom/agenda` (line 265), `PUT /mom/agenda/{index}` (line 285, the edit dialog's Save), `DELETE /mom/agenda/{index}` (line 292);
* `POST /mom/status` (line 481).

So typing in the meeting details, the attendees or an existing agenda row is **never sent to the server**. Only pressing Generate persists them — and it does so by regenerating the document. That is the bug, confirmed in the code.

## 2. What mom.py exposes today — **no PATCH, no PUT on the details**

The live app's own OpenAPI (193 paths total) lists exactly these under /mom:

~~~
GET             /api/projects/{project_id}/mom/defaults
POST            /api/projects/{project_id}/mom/generate
GET             /api/projects/{project_id}/mom/download
GET             /api/projects/{project_id}/mom/email-directory
GET             /api/projects/{project_id}/mom/view
GET             /api/projects/{project_id}/mom/email-link
GET             /api/projects/{project_id}/mom/email.eml
POST            /api/projects/{project_id}/mom/suggest
POST            /api/projects/{project_id}/mom/agenda
DELETE,PUT      /api/projects/{project_id}/mom/agenda/{index}
POST            /api/projects/{project_id}/mom/status
POST            /api/projects/{project_id}/mom/parse-invitation
~~~

* **No `PATCH` anywhere under /mom**, and the collection path `/api/projects/{id}/mom` carries **no methods at all**.
* The only detail-carrying writers are `POST /generate` (bumps `version`, re-renders docx/pdf, rebuilds the email draft) and `PUT /agenda/{index}` (one agenda row).
* Meeting details and attendees have **no endpoint** that can store them without regenerating the whole minute.

## 3. What the Network tab shows when you type — **zero requests**

There is no `fetch` in any `onChange` in `MomPanel.tsx` (section 1), and there is **no endpoint to call** (section 2). Both halves are verified, so typing fires nothing at all — there is no request to report, and the request you would expect (PATCH /api/projects/{id}/mom) does not exist in the live route table.

The stored record on PR-12864 right now (read live):

~~~
MOM v2 | status draft | docx MOM_PR-12864_v2.docx
details keys: agenda, attendees, meeting_date, meeting_location, meeting_number,
              meeting_time, meeting_title, organizer
attendees: 3 | agenda rows: 8 | meeting_title: PR-12864 Installation of new gas line ...
~~~

### The model (backend/app/models.py, MomRecord)

Columns: `id, project_id (unique), version, status, docx_filename (NOT NULL), pdf_filename, email_subject,
email_body, note, details (JSON), updated_by_id, created_at, updated_at`.

There is **no `scope` or `action_items` column**: the scope and the action items you type are the agenda
rows' `scope` / `action` / `etc` fields, stored inside `details["agenda"]` alongside
`details["attendees"]` and the meeting keys. The panel **already uses the right key names**
(`meetingInputs` lines 529-535), so no renaming is needed — the B1 alias bug was in the assistant's
prompt, not here. The missing pieces are the endpoint and the call.


---

## 4. The fix

### 4.1 New endpoint — PATCH /api/projects/{project_id}/mom (backend/app/api/mom.py)

~~~python
@router.patch("", response_model=MomOut)
def patch_mom(
    project_id: int,
    payload: MomDetailsPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Autosave the MOM fields the panel changed. Never regenerates the document.

    Meeting details, attendees, the agenda, the invitation and the organizer are
    edited in place here: version, docx_filename, pdf_filename and the email
    draft are deliberately untouched, so autosave can never invalidate a document
    that was already issued. A field left out of the body is left alone; a field
    sent as "" is cleared.
    """
~~~

Behaviour, precisely:

| Rule | Detail |
|---|---|
| Merge, never replace | `payload.model_dump(exclude_unset=True)` is merged into a copy of `mom.details or {}` — an unsent key keeps its stored value. |
| Never regenerate | `version`, `docx_filename`, `pdf_filename`, `email_subject`, `email_body` and `status` are not written. |
| First edit on a project with no MOM | creates the record (version 1, status draft, empty docx_filename, merged details) so the very first keystroke is stored, then returns `MomOut` 200. |
| Nothing to update | a body with no fields set → **422** "Nothing to update." |
| Capabilities | `mom.manage` → any field. `mom.agenda` only → the body may carry `agenda` only, and each row is checked with the existing `_check_item_access(user, item)` (their own trade; the trade label is not theirs to change). Neither → **403** "Missing permission: mom.manage or mom.agenda". |
| Audit | `workflow.log_action(db, user, "mom:edit", project, {"fields": sorted(changed), "attendees": n, "agenda": m})` |
| Response | `MomOut` — the same shape `/defaults` and `/generate` return, so the client can read `updated_at`. |
| Dates and times | kept as the strings the team types (the template takes strings); no parsing, so "10:00" and "10:00-11:30" both store. |

One guard added next to it, for the new empty-document state only:

~~~python
    # in download_mom, before building the path
    if fmt != "minute-pdf" and not mom.docx_filename:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generate the MOM first: the document has not been rendered yet.",
        )
~~~

Today `docx_filename` is always set, so this state cannot occur in the current app; it becomes reachable
only because the new PATCH can create a draft record. Without the guard the download would fall through to
the misleading "MOM file missing on disk".

### 4.2 Schema — backend/app/schemas.py

~~~python
class MomDetailsPatch(BaseModel):
    """Autosave payload: only the fields the panel actually changed.

    Every field defaults to None so exclude_unset can tell "not sent" (leave as
    is) apart from an explicit "" (clear it).
    """

    meeting_title: str | None = None
    meeting_location: str | None = None
    meeting_number: str | None = None
    meeting_date: str | None = None
    meeting_time: str | None = None
    organizer: str | None = None
    invitation: str | None = None
    attendees: list[MomAttendee] | None = None
    agenda: list[MomAgendaItem] | None = None
~~~

`MomAttendee` and `MomAgendaItem` already exist and are reused as they are, so the agenda row shape
stays scope / action / etc / trade.

### 4.3 Client — frontend/src/lib/api.ts

~~~typescript
export interface MomDetailsPatch {
  meeting_title?: string;
  meeting_location?: string;
  meeting_number?: string;
  meeting_date?: string;
  meeting_time?: string;
  organizer?: string;
  invitation?: string;
  attendees?: MomAttendee[];
  agenda?: MomAgendaItem[];
}

/** Autosave one slice of the MOM. keepalive is for the pagehide flush. */
export function patchMom(
  projectId: number,
  patch: MomDetailsPatch,
  opts: { keepalive?: boolean } = {},
): Promise<MomRecord> {
  return request<MomRecord>(
    '/api/projects/' + projectId + '/mom',
    { method: 'PATCH', keepalive: opts.keepalive ?? false },
    patch,
  );
}
~~~

`keepalive` is a standard RequestInit field, so the existing `request<T>()` wrapper keeps the bearer
header, the 401 redirect and the FastAPI-detail error surfacing exactly as they are.

### 4.4 MomPanel.tsx — debounced autosave (layout and existing buttons unchanged)

**Debounce 400 ms**, one PATCH per burst, plus three flush points so nothing is ever lost:

| Trigger | Why |
|---|---|
| 400 ms after the last keystroke in a slice | the normal path: one PATCH per burst |
| `onBlur` of the field or row | leaving a field saves immediately |
| `visibilitychange` to hidden and `pagehide` | covers "type and immediately refresh / switch tab"; the pagehide flush uses keepalive |
| right before Generate, status, agenda add / edit / delete | the heavy action never runs on stale data (`await flush()` first) |

New state and refs inside the existing component:

~~~typescript
const [saveState, setSaveState] = useState('idle');   // idle | saving | saved | failed
const [saveError, setSaveError] = useState(null);
const [savedAt, setSavedAt] = useState(null);
const pendingRef = useRef({});        // merged patch, not yet sent
const timerRef = useRef(null);        // the debounce timer
const lastSavedRef = useRef('');      // JSON of the last accepted body
const savingRef = useRef(false);      // one request in flight at a time
~~~

~~~typescript
/** Queue one slice and (re)start the debounce. */
function scheduleSave(patch) {
  pendingRef.current = { ...pendingRef.current, ...patch };
  setSaveState('saving');
  setSaveError(null);
  if (timerRef.current) clearTimeout(timerRef.current);
  timerRef.current = setTimeout(() => void flush(), 400);
}

/** Send what is pending. Returns true when the server accepted it. */
async function flush(keepalive = false) {
  if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
  const body = pendingRef.current;
  if (Object.keys(body).length === 0) return true;
  const serialised = JSON.stringify(body);
  if (serialised === lastSavedRef.current) { setSaveState('saved'); return true; }
  if (savingRef.current && !keepalive) return false;
  savingRef.current = true;
  try {
    const saved = await patchMom(projectId, body, { keepalive });
    lastSavedRef.current = serialised;
    pendingRef.current = {};
    setSavedAt(saved.updated_at ?? null);
    setSaveState('saved');
  } catch (err) {
    setSaveState('failed');
    setSaveError(err instanceof Error ? err.message : 'Save failed.');
    return false;                     // pending is kept for the retry
  } finally {
    savingRef.current = false;
  }
  return true;
}
~~~

Wiring — the handlers keep their names and local-state behaviour and gain one line each:

* `updateMeeting(field)` → `setMeeting(...)` **and** `scheduleSave({ [field]: e.target.value })`
* `updateAttendee(i, field, value)` → compute `next`, `setAttendees(next)`, `scheduleSave({ attendees: next })`
* `updateAgenda(i, field, value)` → the same with the agenda array
* the invitation textarea → `scheduleSave({ invitation: e.target.value })`
* `proposeEmail` (the blur fill from the directory) → `scheduleSave({ attendees: nextWithEmail })` so the proposed address persists too
* the `useEffect` that primes the form from `mom.details` gains a guard: skip re-priming while pending is not empty, so a background refresh cannot overwrite unsaved typing

**Save indicator** in the existing `VisualCard` header row (nothing else in the layout moves):

| State | Shown |
|---|---|
| saving | amber pill "Saving…" |
| saved | emerald pill "Saved 14:32:05" |
| failed | red clickable pill "Save failed — retry" (click runs `flush()`), with the FastAPI detail shown in the panel's existing error line |
| idle | nothing |

Nothing from the response is written back over the inputs (no `setMeeting` from the PATCH reply), so the
cursor never jumps while typing; the reply is used only for the timestamp.

### 4.5 Version and changelog

`APP_VERSION = '1.2.1'` and `APP_VERSION_DATE = '14 October 2026'`; a CHANGELOG **1.2.1 — MOM autosave**
section: the new PATCH endpoint, the debounced autosave with flush, the save indicator, the download guard,
and the note that Generate keeps its behaviour (it is still the only thing that renders the document).


---

## 5. Tests to add (backend/tests/test_mom_autosave.py — 8 tests)

1. `test_patch_meeting_fields_persist` — PATCH title/location/date/time → 200; `GET /mom/defaults` returns them; the version is unchanged.
2. `test_patch_leaves_untouched_fields_alone` — send only the title; the stored agenda rows and attendees survive.
3. `test_patch_attendees_and_agenda` — both arrays replaced, the meeting keys untouched.
4. `test_patch_never_regenerates_the_document` — docx_filename unchanged, no new PDF, version identical.
5. `test_patch_logs_mom_edit` — an audit row with the key `mom:edit` and the changed field list.
6. `test_patch_empty_body_is_422` and `test_patch_requires_a_mom_capability` (403), with a `mom.agenda`-only user allowed for agenda and refused for meeting details.
7. `test_patch_creates_the_record_when_missing` — no MOM yet → 200, the record exists with an empty docx_filename, and `GET /mom/download` then answers **409** with the new sentence.
8. `test_patch_last_write_wins` — two PATCHes in a row; the second value is what /defaults returns (the "type then refresh" case).

The existing 382 tests must stay green.

---

## 6. Live verification — backend/scripts/verify_mom_autosave.py

Runs inside the backend container, drives the **public HTTPS URL** with a real admin JWT (the browser's own
path), proves the round-trip on PR-12864, and **restores the record exactly**.

~~~python
# 0. snapshot PR-12864's MOM (version, status, docx/pdf names, email bodies, details, updated_at)
# 1. one field: the request body and the response body are printed in full
#    PATCH /api/projects/291/mom   {"meeting_title": "PR-12864 autosave check A"}   -> 200
#    GET   /api/projects/291/mom/defaults -> meeting_title == check A, version unchanged
# 2. change it again: the new value is there and the old one is gone
#    PATCH ... {"meeting_title": "PR-12864 autosave check B"}                        -> 200
#    GET   ... -> check B
# 3. the whole surface the panel edits: location, time, attendees, an agenda row, invitation
#    PATCH ... {"meeting_location": "...", "meeting_time": "10:00-11:30",
#               "attendees": [ ...one email changed... ],
#               "agenda": [ ...row 1 scope changed... ], "invitation": "..."}         -> 200
#    GET   ... -> every value echoed; the other agenda rows intact
# 4. type-then-refresh: two PATCHes back to back, the last one wins
# 5. audit: GET /api/projects/291/audit contains mom:edit with the field list
# 6. negative: {} -> 422 "Nothing to update."
# 7. latency: every PATCH under 1 s (the Cloudflare budget)
# 8. restore: write the snapshot back, GET /defaults, assert it equals the snapshot, print
#    "restored: PR-12864 MOM unchanged"
~~~

Plus the two checks on the VPS for the built bundle and the page:

~~~bash
docker exec ihp-frontend-1 grep -rlo MOM.autosave /app/.next/static | head -3
curl -s -o /dev/null -w "live page: %{http_code}\n" https://ihp.shariar.dev/projects/291
~~~

## 7. Working order

| Step | Proof |
|---|---|
| 1 | pytest -q → 382 + 8 new |
| 2 | npx tsc --noEmit and npm run build clean |
| 3 | no new migration (the details JSON only) |
| 4 | commit + push, then on the VPS git pull --ff-only and docker compose up -d --build |
| 5 | verify_mom_autosave.py → round-trip, last-write-wins, audit, restore |
| 6 | hygiene: PR-12864's MOM version, details, attendees and agenda identical to the snapshot |

## 8. Decisions to confirm

1. **Trade users (`mom.agenda`)**: the plan lets them autosave agenda rows only, enforced by the existing per-row trade check. Say so if you would rather restrict autosave to `mom.manage` entirely.
2. **Interval**: 400 ms, inside the 300-500 ms you asked for. 250 ms is the snappier alternative at twice the requests.
3. **First edit on a project with no MOM** creates a draft record, so nothing can be lost — which is why the download guard is added. If you prefer "no record until Generate", the PATCH would answer 409 instead and the first typing would still need Generate.
