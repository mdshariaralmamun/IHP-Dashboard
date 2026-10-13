# IHP Project Delivery — change log

Every change to the app is recorded here from 11 October 2026 onwards, and the
current version is shown in the app under **Admin → Version**.

## 1.2.2 — 14 October 2026

### A real auto-attached Outlook draft for the MOM
- **`GET /mom/email.eml` now returns a draft with the MOM PDF already attached.**
  It carries exactly **one** attachment — `IHP-MOM-PR-{pr}-R{rev}.pdf`, the same bytes
  `GET /mom/export?format=pdf` returns, because both now go through one shared
  `mom_pdf_file()` helper built from the same HTML the live preview shows.
  Before, it attached three files (the Word minute, the LibreOffice PDF and the
  minute PDF) and none of them was the named document.
- The message keeps **`X-Unsent: 1`** and no `From` header, so Outlook opens it as an
  editable compose window with To, Cc, Subject and the attachment in place; the
  user sends it from their own mailbox, and no SMTP credentials are involved.
- **Subject** is now the document code plus the meeting title
  (`IHP-MOM-PR-12864-R01 – PR-12864 Installation of new gas line for plasma etcher`)
  and **Cc** is `IHP.design@kaust.edu.sa`, deduped against To. A new audit key
  **`mom:eml`** records the file, recipients and attachment size.
- The draft file is named **`IHP-MOM-PR-{pr}-R{rev}.eml`** (the client takes the name
  from `Content-Disposition`), instead of `MOM_{pr}_v{version}.eml`.
- **Panel**: the primary **Email** button downloads that draft (one line under it:
  "Opens a draft in Outlook with the MOM PDF attached."), the mailto control is
  relabelled **"Email (compose, no attachment)"**, and the manual route is
  **"Download draft (.eml)"**. If the mail client does not open automatically, the
  panel says to open the .eml from the Downloads folder.
- The mailto endpoint and its behaviour are untouched, as are the Procore binder's
  `package:pdf` key, the labour line, the hand-set Procore status and every other panel.
- **Correction kept for the next reader:** that mis-naming was **server-side** — the
  endpoint sent `MOM_{pr}_v{version}.eml`. `downloadFile()` in
  `frontend/src/lib/api.ts` has always read `Content-Disposition`; the file to fix was
  `backend/app/api/mom.py`, not the client.

## 1.2.1 — 14 October 2026

### The MOM panel is live, downloadable and emailable
- **Autosave**: every MOM field saves itself as you type (400 ms debounce, one
  `PATCH /api/projects/{id}/mom` per burst, no Save button). It also flushes on
  blur, when the tab is hidden, on `pagehide` (keepalive) and before any heavier
  action, so typing and immediately refreshing never loses a keystroke. A **Saved /
  Saving… / Save failed — retry** indicator sits in the panel header with the
  document code, and a failed save shows the API's own sentence.
- **Live HTML preview**: `GET /api/projects/{id}/mom/preview` returns the minute
  as the **same HTML the PDF is printed from** (and the same string `/mom/view`
  serves), mounted in a sandboxed frame below the fields and refreshed after every
  save. Preview, PDF and the email body are one source of truth; the Word file
  uses the team's own `.docx` template with the same data (same content, different
  renderer).
- **Named exports**: `GET /api/projects/{id}/mom/export?format=docx|pdf` writes
  **IHP-MOM-PR-{pr}-R{rev}.docx / .pdf**, files it on the PR as a **DELIVERABLE**
  attachment (so it appears in AttachmentsSection immediately) and records
  `mom:export` in the audit trail with the byte size and the page count.
- **Email draft**: `GET /api/projects/{id}/mom/email-draft` returns To (the
  attendees' emails, falling back to the project contact), Cc
  (IHP.design@kaust.edu.sa), the subject and a short body. The panel opens the
  local mail client with that draft **and downloads the PDF** beside it, telling
  you which path was taken, because `mailto:` cannot carry an attachment. Nothing
  is ever sent automatically. With no attendee emails and no project contact the
  endpoint answers **409** with the reason and no compose window opens. The
  existing `.eml` control stays as the automatic-attachment route.
- Unknown fields in an autosave are refused with **422** (`extra="forbid"`)
  instead of being dropped silently, and a draft record that has never been
  rendered reports **409** "Generate the MOM first" instead of "file missing".

## 1.2.0 — 14 October 2026

### The Project Delivery Assistant
- **One conversational panel per project** (above the delivery pipeline): paste the
  meeting notes, the instructions or the scope inputs, press **Propose the next
  step**, and run the step it names. Every step writes the real document through
  the app's own generators — MOM, Project Summary + Cost Estimate, EAR, SOW, BOQ,
  technical drawing list, the combined Procore binder and the design MTO.
- **Nothing is written without an explicit run**: *Propose* records what the team
  pasted and says which step comes next; only **Run** writes, and each result is
  reported inline (document, version, panel, size, audit key).
- **The gates are never skipped**: a step that is not allowed yet is shown greyed
  out with the **pipeline's own sentence** ("Confirm the MOM first (Stage 1) …",
  "The MTO unlocks when Procore is Approved or Approved as Noted"), and the API
  refuses it with a 409 even if the button were clicked. 13 actions in a registry,
  each with a precondition, a panel and an audit key.
- **The EAR funnel runs beside the five-stage spine**, and the panel shows both:
  the five stage chips plus an "EAR · pi signature · beside the spine" chip.
- **Capability-aware**: a Run button appears only when the user holds the action's
  capability (mom.manage, projects.edit, ear.manage, sow.manage, boq.manage);
  otherwise the step is shown with what it needs.
- Six new endpoints: `GET/POST/PATCH/DELETE /api/projects/{id}/assistant` and
  `/message`, `/run`, `/messages`, `/actions`; new `assistant_messages` table.

### MOM quality fixes
- **Prose notes now always produce an agenda**: the model is asked for one row per
  scope point, and when it returns fewer than the notes list, the notes win — the
  assistant splits them itself (bullet points first, then sentences), infers the
  trade and keeps the responsible party ("Action: IHP to issue the SOW" →
  responsible IHP). A single aggregated model row no longer swallows the scope.
- **Template keys fixed**: date / location / time / title are normalised onto the
  template's `meeting_date`, `meeting_location`, `meeting_time`, `meeting_title` —
  they were being dropped before.
- The panel now reports the agenda that the document actually contains, not the raw
  model reply.

### Fixes
- **`sow.approve`** was missing from the assistant registry, so the binder could
  never be unlocked.
- **The hand-set Procore status now unlocks the MTO**: the gate reads
  `project.procore_status = Approved / Approved as Noted` as well as the pipeline's
  stage 4, matching "Procore status is set by hand".
- **A useless model answer no longer produces an empty BOQ**: it falls back to the
  SOW's own measured lines.
- **Project Summary generation** created the `deliverables/` folder it writes into
  (the first Summary for a PR raised FileNotFoundError from python-docx).
- The combined binder and the plan-marker renderer import `pymupdf` instead of the
  deprecated `fitz` alias.

## 1.1.0 — 12 October 2026

### The five-stage delivery spine
- **Pipeline per PR**: Stage 1 *Request registered* → 2 *MOM* → 3 *SOW/BOQ
  submitted* → 4 *Procore submittal* → 5 *MTO / procurement*, each with a status,
  a note and the acting user, on the project page.
- **Gates enforced by the API, explained in the UI**: stage 2 needs the MOM
  confirmed, stage 3 needs stage 2 approved or pending, stage 4 needs stage 3
  issued, and stage 5 waits until Procore approves. A blocked stage shows why
  instead of offering a status that would be refused.

### Combined Procore binder
- **Download Combined Procore Binder (PDF)** merges a cover page, the SOW, the
  BOQ, the **Procore Comment Log** and every non-generated PDF drawing with
  PyMuPDF, so each page keeps its own size and orientation (A3 plots stay A3,
  landscape CAD sheets stay landscape). Broken files are skipped and audited,
  never fatal.
- The binder is attached to the PR as a `DELIVERABLE` and the revision is printed
  on the cover (**Rev 0**, **Rev 1** …), so the copy in Procore can always be
  matched to the copy in the app.

### Procore review round-trip
- **Reviewer comment log** per PR: reviewer (HSE Team, FLP / Fire Protection,
  FMOM / Building Management, Building Operations, CTPS, Proponent / PI — or any
  free-text name), department, discipline, the comment, IHP's response, the
  action taken, open/closed, and the revision the comment was raised on.
- **Comment Log Sheet export** as `PR-XXXXX Comments Logs.xlsx` and PDF, with the
  project title block, submittal date, status and revision.
- **Procore status set by hand** — Under Review | Revise and Resubmit | Approved
  as Noted | Approved — with the **submittal date**, because that is what Procore
  tells the team; the app never guesses the outcome.
- **Dropzone for the stamped Procore Submittal PDF** that comes back reviewed; it
  is versioned and stored with the project.
- **Generate Revision N Package** bumps the revision (Rev 0 → Rev 1), stamps the
  new submittal date, keeps earlier comments on the revision they were raised on
  and reports which items the new package must still answer.

### Fixes
- **The BOQ was silently missing from the binder**: the image had LibreOffice
  Writer but not **Calc**, so `.xlsx` → PDF failed while `soffice` still exited
  0 with "source file could not be loaded". `libreoffice-calc` is now installed,
  every conversion gets its own user profile, and a part that cannot be converted
  is written to the audit trail instead of quietly dropping out of the binder.
- `GET /projects/{id}/sow` called with its arguments swapped, which would have
  failed the first time it was used.
- PyMuPDF is now imported as `pymupdf` (the `fitz` alias is deprecated).

## 1.0.0 — 11 October 2026

### Projects & pipeline
- Per-project **Data room** (any format: PDF, Word, Excel, .msg/.eml, csv, images,
  audio) with text extraction cached per file and a versioned **AI brief**
  (scope by trade, utility matrix, line items, open questions).
- **Per-document generation**: Project Summary, Scope of Work, BOQ, Cost Estimate
  and MTO — each generated on its own, from the team's own Word/Excel templates.
- **Web view + PDF** for every document (Word/Excel rendered in the browser,
  PDF converted on demand and cached).
- **AI chat per project** (this project / standards / everything) with citations.
- **Answerable questions**: the brief's open questions are stored on the project;
  answers and closures survive re-analysis.
- **Next step & to-do** per PR, plus the global **To-do list** grouped by bucket.
- **PI / requester directory** built from the register; 288 of 289 projects carry
  a contact email after the team's contacts file was loaded.

### ICR branch
- **Pull ICR projects** from the O&M *Active Equipment PRs* tab (Construction
  Project classification, typo tolerated) — 15 ICR projects; equipment
  installation and ASEPC proposals are deliberately excluded.
- **ICR materials take-off** from the data room, and the ICR Live Tracking stages.

### Locations & reference data
- Room codes decode to building, level, **area** (bands 6/7/8/9 → Areas 1/3/4/6)
  and now name the **lab**, centre and PI from the site lab list (182 FLOCs).
- Reference masters are found wherever the app runs (fixed a production fault
  where the JSON lists were missing from the installed package).

### Materials & pricing
- **Price master** (2 282 items: the Planner's cost estimates + the store's
  quotation list, with suppliers), searchable by trade, with a **materials
  picker** and **MTO drafts** that save, update and clear.
- **Cost Estimate** priced from the master; BOQ left unpriced for bidding.

### MOM
- Generate MOM (KAUST template) → Word/PDF, email draft, status tracking.
- **Multi-line, resizable scope fields** that wrap and keep line breaks.
- **Paste-an-invitation parser**: PR number, meeting title, date, time, room code
  (decoded, with the lab) and attendees with their roles — endpoint live.

### Boards, dashboards & theme
- EAR / Design / Procore boards with explicit **Save** for assignee and follow-up
  note, and **Move to — stage** per row.
- The team's **EAR funnel** substages (Summary Received by Trade, Waiting for WBS,
  Under PI Signature, Waiting for ASEPC Approval, Approved, Revised) plus the new
  **EAR Issued** workflow stage.
- **Dark theme** fixes: typed text, label colours, placeholders, native dropdown
  popups and hard-coded palette text.

### Platform
- Sendable **invitation/status emails** pre-addressed from the directory (drafts;
  real sending needs SMTP).
- Performance: tracker derivation memoised and the O&M parse cached
  (om-active 696 → ~20 ms, consistency 1 377 → ~8 ms); API JSON gzipped 10×.
- Ollama + nomic-embed-text installed for embeddings; the reference library
  (Specifications 408 docs, MEP BOQ 106, MEP Narrative 26) is indexed.
