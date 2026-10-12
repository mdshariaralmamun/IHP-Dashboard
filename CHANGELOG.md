# IHP Project Delivery — change log

Every change to the app is recorded here from 11 October 2026 onwards, and the
current version is shown in the app under **Admin → Version**.

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
