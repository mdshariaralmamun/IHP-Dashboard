# IHP Project Delivery — change log

Every change to the app is recorded here from 11 October 2026 onwards, and the
current version is shown in the app under **Admin → Version**.

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
