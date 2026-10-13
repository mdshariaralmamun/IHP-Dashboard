# Investigation + implementation plan — live MOM preview, download and email (app 1.2.1)

**State note:** the MOM-autosave plan from the previous turn was never built (it was a plan only), so
nothing has changed on the live app: typing in the MOM panel still saves nothing, and there is still no
PATCH. This feature therefore *includes* the autosave work, because the live preview and the exports
have nothing to render from until the panel can save.

---

## 1. What MomPanel.tsx does today on input — **it calls nothing**

Every input handler writes to React state and stops there:

| UI field | Handler (frontend/src/components/project/MomPanel.tsx) | What it does |
|---|---|---|
| Meeting Title / Location / Number / Date / Time / Organizer | `onChange={updateMeeting(field)}` line 608 → `setMeeting(...)` lines 495-498 | local state only |
| Attendee name / title / email | `updateAttendee(i, field, value)` lines 665-683 → `setAttendees` line 519 | local state only (the email is also proposed on blur from the directory) |
| Existing agenda rows (trade / scope / action / ETC) | `updateAgenda(i, field, value)` lines 744-795 → `setAgenda` line 525 | local state only |
| New agenda item | `setNewItem` lines 845-867 | local state only; the **Add** button posts it |
| Invitation textarea | `setInvitation(e.target.value)` line 632 | local state only |

The panel's own writes are all explicit buttons, wrapped in `run()` (line 406): `POST /mom/generate`
(the Generate button, line 437 — it renders a new document and bumps the version), `POST /mom/agenda`
(265), `PUT /mom/agenda/{index}` (285, the edit dialog's Save), `DELETE /mom/agenda/{index}` (292) and
`POST /mom/status` (481).

**What exists today for preview / download / email:**

* **Preview**: a **modal that renders the DOCX with docx-preview** (`renderAsync(previewBlob, container)`,
  lines 250-257, fed by `getMomDocxBlob`), plus a "web view" that **opens `/mom/view` in a new tab**
  (`openMomWebView`). There is **no live HTML preview inside the panel**.
* **Download**: `downloadMom(projectId, fmt)` exists for `docx | pdf | minute-pdf`, but there is **no
  Download control that writes a named file, and the export is not attached as a DELIVERABLE**.
* **Email**: an "Open in Outlook" button calls `handleOpenInOutlook` (line 155) → `GET /mom/email-link` →
  `window.location.href = link.mailto` — a **mailto: with no attachment**. A second control
  (`handleSendEmail`, line 170) downloads an **.eml with the minute attached** via `downloadMomEmail`.

## 2. What mom.py exposes today — no PATCH, no preview JSON, no export

The live app's own OpenAPI (193 paths) lists 12 under /mom:

~~~
GET             /api/projects/{project_id}/mom/defaults
POST            /api/projects/{project_id}/mom/generate
GET             /api/projects/{project_id}/mom/download        (fmt=docx|pdf|minute-pdf)
GET             /api/projects/{project_id}/mom/email-directory
GET             /api/projects/{project_id}/mom/view            (full HTML document)
GET             /api/projects/{project_id}/mom/email-link      (mailto, no attachment)
GET             /api/projects/{project_id}/mom/email.eml       (.eml with the minute attached)
POST            /api/projects/{project_id}/mom/suggest
POST            /api/projects/{project_id}/mom/agenda
DELETE,PUT      /api/projects/{project_id}/mom/agenda/{index}
POST            /api/projects/{project_id}/mom/status
POST            /api/projects/{project_id}/mom/parse-invitation
~~~

* **No `PATCH`** and the collection path carries no methods at all.
* **There is a HTML GET**: `/mom/view` already returns the self-contained minute document — so the
  preview does not need a new renderer, only a JSON-shaped sibling the panel can poll.
* There is **no export endpoint that names the file and files it as a DELIVERABLE**.

### The model (backend/app/models.py, MomRecord)

Columns: `id, project_id (unique), version, status, docx_filename (NOT NULL), pdf_filename, email_subject,
email_body, note, details (JSON), updated_by_id, created_at, updated_at`.

There is **no `scope` and no `action_items` column**: the scope lines and the action items you type are the
agenda rows' `scope` / `action` / `etc` inside `details["agenda"]`. The panel already uses the correct
template keys (lines 529-535: `meeting_title, meeting_location, meeting_number, meeting_date, meeting_time,
organizer`). PR-12864 today: **MOM v2, 3 attendees, 8 agenda rows**.

## 3. What mom_html.py takes — no AI involved

~~~python
def build_html_context(*, project, details: dict, derived: dict, version: int,
                       context: dict | None = None, base_url: str | None = None,
                       for_email: bool = False) -> dict      # line 177
def render_html(context: dict) -> str                        # line 390, Jinja: templates/mom_template.html
~~~

**Inputs**: the project row, `details` (the MOM JSON), `derived` (from `_derive_tracker_fields(project)`),
the version, and the already-built `build_mom_context(...)` dict. **No AI call anywhere** — it is pure
Jinja over stored data, which is why a preview can be rendered on every keystroke burst.

## 4. Word vs HTML: two renderers, one data source

| Output | Renderer | Code |
|---|---|---|
| **HTML preview** | Jinja `templates/mom_template.html` | `mom_html.render_html(build_html_context(...))` — used by `GET /mom/view` (line 551) |
| **PDF** | headless **Chromium** printing that same HTML | `_mom_styled_pdf()` line 417 → `docgen.html_to_pdf(html, path)` (cached as `MOM_{pr}_v{version}_minute.pdf`) |
| **Email body** | the same HTML, `for_email=True` | `_mom_html_body()` line 450 |
| **Word** | **docxtpl** on `backend/templates/mom_template.docx` | `docgen.render_docx("mom_template.docx", context, path)` with the same `build_mom_context` data |

So **preview = PDF = email body** are three uses of one HTML string (the one source of truth you asked for),
while **Word is the team's own .docx template** filled with the same context. They carry the same sections
and the same values, but they are **not pixel-identical** (different renderers, as the Dockerfile comment
explains: LibreOffice's HTML import drops the stylesheet, which is why Chromium prints the HTML and
docxtpl writes the Word). I will report this honestly rather than claim otherwise, and the verification
compares the *content* of both against the stored record.

## 5. What the live Network tab shows when you type today — **zero requests**

There is no `fetch` in any `onChange` (section 1) and no endpoint to call (section 2) — the collection
path has no methods. So typing fires nothing: there is no request to report, and the request you would
expect (PATCH /api/projects/{id}/mom) does not exist in the live route table.

**emailer.py** (`backend/app/services/emailer.py`): `pr_label(project)`, `mom_recipients(project, details)`
line 26 (attendee emails + the PI, deduplicated — **no project-contact fallback today**),
`build_mom_draft(...)` line 49 → `(subject, body)`, `build_tracking_draft(...)`, and
`send_email(to, subject, body) -> bool` line 280 which is **SMTP-only and returns False when SMTP is not
configured** (it is not configured in production). **No mailto and no Outlook integration in the backend** —
mailto is built in the frontend by `GET /mom/email-link` and opened by the browser, and `mailto:` cannot
carry an attachment, which is exactly why the plan downloads the PDF alongside the compose window.


---

## 6. The fix — backend

### 6.1 One renderer, three callers (refactor in mom.py, behaviour unchanged)

Extract the body of `/mom/view` into a helper so the preview, the PDF and the export can never drift:

~~~python
def render_mom_document(project: Project, mom: MomRecord, details: dict,
                        base_url: str | None = None, for_email: bool = False) -> str:
    """The minute as the self-contained HTML document. One source of truth."""
    from ..services import mom_html
    context = build_mom_context(project, details, mom.version)
    return mom_html.render_html(
        mom_html.build_html_context(
            project=project, details=details, derived=_derive_tracker_fields(project),
            version=mom.version, context=context, base_url=base_url or None,
            for_email=for_email,
        )
    )
~~~

`GET /mom/view` then returns `HTMLResponse(content=render_mom_document(...))` — byte-identical output to
today. `_mom_styled_pdf()` keeps its own cache but is given the same helper internally.

### 6.2 GET /api/projects/{id}/mom/preview — live preview

~~~python
@router.get("/preview")
def mom_preview(project_id: int, base_url: str | None = Query(default=None),
                db: Session = Depends(get_db),
                _user: User = Depends(get_current_user)):
    """The stored MOM as HTML, for the panel's live preview.

    Returns the same string /mom/view serves (and the PDF is printed from), so
    the preview can never drift from the download. No AI call, no regeneration.
    """
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    details = mom.details or {}
    html = render_mom_document(project, mom, details, base_url=base_url)
    return {
        "html": html,
        "document_code": build_mom_context(project, details, mom.version)["document_code"],
        "revision": f"R{mom.version - 1:02d}",
        "version": mom.version,
        "updated_at": mom.updated_at,
        "bytes": len(html),
    }
~~~

JSON with an `html` field, matching the app's convention for the other JSON endpoints; the existing
`/view` keeps returning `text/html` for the "open in a tab" use. Latency = Jinja over one record, a few
milliseconds.

### 6.3 GET /api/projects/{id}/mom/export?format=docx|pdf — the named file, filed as a DELIVERABLE

~~~python
@router.get("/export")
def export_mom(project_id: int, format: Literal["docx", "pdf"] = Query("pdf"),
               db: Session = Depends(get_db),
               user: User = Depends(require_capability(CAP_MOM_MANAGE))):
    """Export the current MOM with the team's own file name, saved on the PR.

    pdf  -> Chromium prints the same HTML the preview shows
    docx -> the team's mom_template.docx through docxtpl
    The file lands in the project's attachments as a DELIVERABLE (the pattern
    used by package:pdf in sow_boq.py) and the audit trail records mom:export.
    """
~~~

* File name: `context["document_code"]` + extension → **IHP-MOM-PR-12864-R01.pdf** (the record's own code
  already is `IHP-MOM-{pr_number}-R{revision_no}`, so the naming cannot drift from the document header).
* Stored at `storage.project_dir(pr, "generated")` and copied into the attachments as
  `stage="DELIVERABLE"`, `version=storage.next_version(...)`, `content_type` = the Word MIME type or
  `application/pdf`, exactly like the binder does.
* Audit: `workflow.log_action(db, user, "mom:export", project, {"file": name, "format": format, "bytes": n, "page_count": p})`.
* Returns `FileResponse(path, filename=name, media_type=...)`.
* `docx_to_pdf` is **not** used for the PDF: Chromium prints the HTML (the same one as the preview), which is
  the app's existing and visually correct path (`_mom_styled_pdf` exists precisely because LibreOffice
  mangled the styling).
* Page count comes from PyMuPDF (`pymupdf.open(path).page_count`) and is reported in the response headers
  (`X-MOM-Pages`) and the audit payload, so the live verification can assert it.

### 6.4 PATCH /api/projects/{id}/mom — autosave (also required by the preview)

~~~python
@router.patch("", response_model=MomOut)
def patch_mom(project_id: int, payload: MomDetailsPatch,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Autosave the MOM fields the panel changed. Never regenerates the document."""
~~~

| Rule | Detail |
|---|---|
| Merge | `payload.model_dump(exclude_unset=True)` merged into a copy of `mom.details or {}`: an unsent key keeps its value, an explicit `""` clears it. |
| Never regenerate | version, docx_filename, pdf_filename, email_subject, email_body and status are untouched. |
| Unknown field | `MomDetailsPatch` declares `model_config = ConfigDict(extra="forbid")` → a key that is not a real field answers **422** ("Extra inputs are not permitted"), never a silent drop. |
| Empty body | **422** "Nothing to update." |
| First edit, no MOM yet | creates the record (version 1, status draft, empty docx_filename, merged details) so the first keystroke is stored. |
| Capabilities | `mom.manage` any field; `mom.agenda` agenda only, each row through the existing `_check_item_access`; neither → 403. |
| Audit | `mom:edit` with the changed field list. |

~~~python
class MomDetailsPatch(BaseModel):
    """Autosave payload: only the fields the panel changed."""
    model_config = ConfigDict(extra="forbid")   # unknown key -> 422, never dropped

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

One guard beside it: `download_mom` answers **409** "Generate the MOM first: the document has not been
rendered yet." when `docx_filename` is empty (the new first-edit state, unreachable today). The same guard
covers `/export`.

### 6.5 GET /api/projects/{id}/mom/email-draft — the draft, no sending

~~~python
@router.get("/email-draft")
def mom_email_draft(project_id: int, db: Session = Depends(get_db),
                    _user: User = Depends(get_current_user)):
    """To / Cc / Subject / Body for the MOM email. Builds a draft; never sends."""
~~~

* **To**: attendee emails, then the project contact (`project.pi_email`) — the fallback the request asks for,
  added in this endpoint (the existing `emailer.mom_recipients` keeps its current behaviour and is reused for
  the attendee part).
* **Cc**: `IHP.design@kaust.edu.sa` (constant `MOM_CC`, overridable by a query parameter).
* **Subject**: `IHP-MOM-PR-{pr}-R{rev} – {meeting_title}` — the code plus an en dash, as specified.
* **Body**: the short template — "Dear all, please find attached the Minutes of Meeting for
  PR-{pr} – {title}. Please review and confirm the accuracy of this document. Regards, In-House Projects."
* **attachment**: `{"filename": code + ".pdf", "download_url": "/api/projects/{id}/mom/export?format=pdf",
  "ready": bool}` — the panel downloads it so the user can drag it into the compose window.
* **409** when neither attendee emails nor a project contact exist:
  "No attendee emails and no project contact — cannot build the email draft."
* Response also carries `"attachment_supported": false` and `"path_taken": "mailto + downloaded PDF (mailto
  cannot carry an attachment)"` so the UI states which path it used, as required.

**mailto vs .eml:** the panel builds `mailto:` from this JSON and opens it, and downloads the PDF beside it.
The app already has a full-fidelity alternative — `GET /mom/email.eml` produces an .eml **with the minute
attached**, which Outlook opens with the attachment ready. The panel keeps that control untouched and the
plan labels the two paths in the UI ("Compose (PDF downloaded)" vs "Open as .eml with attachment").


---

## 7. The fix — frontend (frontend/src/components/project/MomPanel.tsx + lib/api.ts)

### 7.1 lib/api.ts — four additions

~~~typescript
export interface MomDetailsPatch { /* meeting_title, meeting_location, meeting_number,
   meeting_date, meeting_time, organizer, invitation, attendees, agenda - all optional */ }

/** Autosave one slice of the MOM. keepalive is for the pagehide flush. */
export function patchMom(projectId: number, patch: MomDetailsPatch,
                         opts: { keepalive?: boolean } = {}): Promise<MomRecord>;

/** The stored MOM as the same HTML the PDF is printed from. */
export interface MomPreview {
  html: string; document_code: string; revision: string;
  version: number; updated_at: string | null; bytes: number;
}
export function getMomPreview(projectId: number): Promise<MomPreview>;

/** Download the named export; the file name comes from Content-Disposition. */
export function downloadMomExport(projectId: number, format: 'docx' | 'pdf'): Promise<void>;

export interface MomEmailDraft {
  to: string[]; cc: string[]; subject: string; body: string;
  attachment: { filename: string; download_url: string; ready: boolean };
  attachment_supported: boolean; path_taken: string; note?: string | null;
}
export function getMomEmailDraft(projectId: number): Promise<MomEmailDraft>;
~~~

`downloadMomExport` uses the existing `saveAsDownload(res, fallback)` helper (written for the Procore comment
log), reading the server's `Content-Disposition` name when present and falling back to
`IHP-MOM-PR-{pr}-R{rev}.{ext}`. Everything else keeps `request<T>()`, the bearer header, the 401 redirect and
the FastAPI-detail error surfacing.

### 7.2 MomPanel.tsx — live preview, download, email, autosave

**Debounce 400 ms**, one PATCH per burst, and a preview refresh straight after each accepted PATCH:

| Trigger | What happens |
|---|---|
| any input change | local state + `scheduleSave(slice)`; the indicator turns "Saving…" |
| 400 ms after the last keystroke | `flush()` then PATCH; on 200 the indicator turns "Saved" and `refreshPreview()` runs |
| `onBlur` of a field or row | immediate flush |
| `visibilitychange` to hidden, and `pagehide` | flush with keepalive true (covers "type then refresh") |
| before Generate / status / agenda add / edit / delete | `await flush()` so the heavier action never runs on stale data |
| on mount, and whenever `mom.version` changes | `refreshPreview()` |

**The preview**: the minute is a full HTML document with its own stylesheet, so it is mounted in an iframe
rather than injected into the page — the only way it can look exactly like the PDF without its CSS leaking
into the app:

~~~tsx
<iframe
  title={'MOM preview ' + prNumber}
  srcDoc={preview?.html ?? ''}
  sandbox=""
  className="h-[70vh] w-full rounded-lg border border-apple-border bg-white"
/>
~~~

The empty sandbox blocks scripts and navigation (the minute needs neither) and keeps the app's dark theme out
of the document. Above it: the document code, the revision, and the last refresh time.

**Download**: two controls, **Download Word** and **Download PDF**, each calling `downloadMomExport` and then
`onChanged()` so AttachmentsSection picks the new DELIVERABLE up immediately. They sit in the existing
header row beside the current controls; nothing is removed.

**Email**: the new **Email** button calls `getMomEmailDraft`.

* 200 → build the mailto URL from to / cc / subject / body (all URL-encoded), open it with
  `window.location.href = mailto`, then download the PDF so the file is on disk to attach, and show the
  response note in the panel: "Outlook compose opened with the PDF downloaded — mailto cannot carry an
  attachment, so attach the file before sending." The `path_taken` string is printed verbatim.
* 409 → the FastAPI sentence appears in the panel's existing error line and **no compose window opens**.
* The existing ".eml with the minute attached" and "Open in Outlook" controls stay exactly as they are: the
  .eml path is the full-fidelity alternative when the attachment must be automatic.

**Save indicator** in the existing header: amber "Saving…", emerald "Saved 14:32:05", red clickable
**"Save failed — retry"** with the FastAPI detail in the error line. Nothing from the PATCH response is
written back over the inputs, so the cursor never jumps.

**Untouched**: the layout, the DOCX preview modal, Generate, Send, the agenda editor, the status buttons and
every other panel.

## 8. Tests to add (backend/tests/test_mom_media.py — 10 tests)

1. `test_preview_returns_the_document` — 200, the html carries the meeting title, the attendees and the footer sentence; `document_code` is IHP-MOM-…-R01.
2. `test_preview_equals_the_web_view` — `GET /preview`'s html is byte-identical to `GET /view`'s body (the one-source-of-truth assertion).
3. `test_preview_after_a_first_patch` — a project with no MOM: the PATCH creates the draft, then /preview returns a document.
4. `test_patch_persists_and_never_regenerates` — values stored, version and docx unchanged, audit `mom:edit`.
5. `test_patch_rejects_an_unknown_field` — an unknown key answers **422** (extra forbidden), never a silent drop.
6. `test_patch_empty_body_is_422`.
7. `test_export_pdf_attaches_a_deliverable` — monkeypatch `docgen.html_to_pdf` to write a one-page PDF and capture the HTML it was handed; assert that HTML equals `/preview`'s, the name is IHP-MOM-…-R01.pdf, an attachment row exists with stage DELIVERABLE, and audit `mom:export`.
8. `test_export_docx_named_and_attached` — the real docxtpl render, MIME type, file name and attachment row.
9. `test_email_draft_content` — to = attendees + PI, cc = IHP.design, subject starts with the document code, the body carries the "Please review and confirm" line.
10. `test_email_draft_409_without_any_email` — the sentence, and nothing is sent.

The existing 382 tests must stay green.


---

## 9. Live verification — backend/scripts/verify_mom_media.py

Drives the **public HTTPS URL** with a real admin JWT (the browser path), on PR-12864, and restores the record.

~~~python
# 0. snapshot: version, status, details, docx and pdf names, email bodies, updated_at,
#    the attachment ids already on the PR, and which files exist on disk
# 1. PATCH /mom with a new meeting_title -> 200, print the body and the latency (under 1 s)
# 2. GET /mom/preview -> 200 application/json; print the byte size; assert the new title and the
#    footer sentence are inside the html; assert html equals the GET /mom/view body
#    (that is the one-source-of-truth proof)
# 3. GET /mom/export?format=pdf -> 200 application/pdf; print Content-Disposition, byte size and
#    the X-MOM-Pages header; assert the name is IHP-MOM-PR-12864-R01.pdf
# 4. GET /mom/export?format=docx -> 200; the Word MIME type; IHP-MOM-PR-12864-R01.docx
# 5. GET /api/projects/291/attachments -> both new files listed with stage DELIVERABLE
# 6. GET /mom/email-draft -> 200; print to, cc, subject, body and the attachment block; then PATCH the
#    attendee emails away and GET again -> 409, print the sentence, then restore
# 7. GET /api/projects/291/audit -> mom:edit and mom:export present, with their payloads
# 8. latency: PATCH and preview each under 1 s; the PDF export under 60 s
# 9. restore: write the snapshot back, delete the two verification attachments and their files, re-read
#    /defaults and assert it equals the snapshot; print "restored: PR-12864 MOM unchanged"
# SUMMARY: ALL OK, or the list of failed steps
~~~

Plus the two checks on the VPS for the built bundle and the page:

~~~bash
docker exec ihp-frontend-1 grep -rlo MOM.preview /app/.next/static | head -3
curl -s -o /dev/null -w "live page: %{http_code}\n" https://ihp.shariar.dev/projects/291
~~~

## 10. Working order

| Step | Proof |
|---|---|
| 1 | pytest -q → 382 + 10 new |
| 2 | npx tsc --noEmit and npm run build clean |
| 3 | no new migration (the details JSON only) |
| 4 | commit + push, then on the VPS git pull and docker compose up -d --build |
| 5 | verify_mom_media.py → preview equals view, both exports named and attached, email draft 200 and 409, audit, restore |
| 6 | hygiene: PR-12864 MOM identical to the snapshot, both verification attachments gone |

## 11. Version and changelog

**App 1.2.1 — 14 October 2026**: MOM autosave (PATCH /mom, 400 ms debounce, the Saved / Saving / Save failed
indicator, flush on blur, on a hidden tab and before heavy actions), the live HTML preview (GET /mom/preview,
mounted in a sandboxed iframe and refreshed after every save), named exports
(GET /mom/export with format docx or pdf, named IHP-MOM-PR-{pr}-R{rev} and attached as a DELIVERABLE), and the
email draft (GET /mom/email-draft giving To, Cc, Subject and the short body plus the PDF downloaded for
attaching, and a 409 when there is no address). The changelog also records the report's honest note: the
preview, the PDF and the email body share one HTML string, while Word uses the team's own .docx template with
the same data.

## 12. Decisions to confirm

1. **Audit key for the exports**: the plan uses **mom:export** (with the format and the page count). Your DONE
   list mentions package:pdf — that key belongs to the combined Procore binder and stays exactly as it is. Say
   the word if you want the MOM export logged under package:pdf as well.
2. **Word versus preview fidelity**: they share the data but not the renderer (the .docx template versus the
   HTML that the PDF prints). Making Word pixel-identical to the preview is a different job; the honest
   statement is "same content and sections, different renderer".
3. **Debounce**: 400 ms, inside the 300-500 ms band you gave.
4. **The email attachment path**: mailto cannot carry a file, so the plan opens compose and downloads the PDF
   (your stated fallback), while the existing .eml control stays as the automatic-attachment route. If you
   would rather make the .eml the primary Email button, that is a one-line switch.
