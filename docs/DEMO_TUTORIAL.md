# IHP Project Delivery — Demo tutorial

A guided tour of the full project lifecycle in the KAUST IHP Project
Delivery Platform, using the seeded demo portfolio. Read it once, then
follow the steps against your running local dev server.

---

## 0. Before you start

| Item | Value |
| --- | --- |
| App URL | http://localhost:3000 |
| API URL | http://localhost:8001 (docs at `/docs`) |
| Admin login | `admin` / `admin123` |
| Demo users | `chris.asis`, `abdulkader.rokaya`, `nadia.haddad`, `ahmed.alam` (all `demo-pass-1`) |
| Seed script | `backend/scripts/seed_demo.py` |

Start the dev servers with `start-dev.ps1` (or `start-dev.bat` /
`start-dev.sh`). The seed script is idempotent — run it any time you
want a clean demo dataset.

```powershell
cd backend
.venv\Scripts\python.exe -m scripts.seed_demo
```

What the seed creates:

| PR | Stage | Disposition | Highlights |
| --- | --- | --- | --- |
| PR-12623 | INTAKE | — | Bare new PR; metadata + audit only |
| PR-12643 | MOM_CONFIRMED | — | MOM with action items, ready for disposition |
| PR-20001 | SOW_APPROVED | PROJECT | EAR (approved), SOW (approved), 5 BOQ lines, WCF filed, planned construction |
| PR-20002 | CLOSEOUT | PROJECT | Full lifecycle walked through, closeout with 3 punch items, completed construction |
| PR-20003 | MTO_APPROVED | ICR | ICR fast-track branch — EAR / SOW / Construction blocked, 3 ICR handoff milestones |

The dashboard at http://localhost:3000/dashboard/construction shows
project #6 (PR-20001) as "active" because it has both a filed WCF and
BOQ items; project #7 (PR-20002) is the completed example; the other
three are pre-construction so they don't show on the construction
dashboard.

---

## 1. Sign in

1. Go to http://localhost:3000.
2. The header should show **Admin / Platform Administrator** already
   because you're seeded as `admin`.
3. If you ever need to re-login, hit **Log out** (top right) and sign
   in with `admin` / `admin123`.

You'll land on the project register (the `/` page). The five demo
projects plus one leftover from the original seed (`PR-99001`) are
listed.

---

## 2. Walk a new PR through intake (project #4 — PR-12623)

PR-12623 is the blankest project — it has only the metadata. This is
the natural starting point for a brand-new PR.

1. Click the row for **PR-12623** (or go to
   `http://localhost:3000/projects/4`).
2. You see the title block with the stage badge (`INTAKE`) and the
   "Overview & All Stages" tab open.
3. The **1. MOM** panel is empty: no MOM yet. (This is correct — at
   `INTAKE` you haven't scheduled the meeting.)
4. The audit trail at the bottom shows the project-creation event and
   the `intake:pr_received` event.
5. Open the **Attachments** tab. Upload a PDF — this exercises the
   `attachments.upload` capability for `admin`.

To move it past INTAKE without filling in every detail (you can do this
in the UI by editing the MOM, but the MOM form is the natural entry
point), use the MOM panel on the next project.

---

## 3. Inspect a MOM-confirmed PR (project #5 — PR-12643)

1. Open http://localhost:3000/projects/5.
2. The **1. MOM** panel should show a confirmed MOM with:
   - meeting date, attendees, and two action items
   - the email body and subject
3. Click **2. Disposition**. The disposition panel is where Engineering
   decides whether this PR is a **PROJECT** (full lifecycle) or
   **ICR** (fast-track to MTO). For PR-12643, no disposition has been
   set yet — that's the next action in real life.
4. The audit trail shows three entries: `project:create`, `mom:draft`,
   and the auto-generated `stage:MOM_SENT` + `stage:MOM_CONFIRMED`
   transitions with the `confirmed_by: PI` detail.

The MOM panel's `mom:draft` action uses the
`mom.manage` capability, which by default is held by `engineering` and
`admin`.

---

## 4. The deep one — PR-20001 (SOW_APPROVED)

Project #6 is the one you'll spend the most time with. Every panel has
content.

1. Open http://localhost:3000/projects/6.
2. Tab through each:
   - **1. MOM** — none (this PR was created in a flow where MOM was
     pre-completed; the audit trail records the synthetic transitions).
   - **2. Disposition** — `PROJECT` is set.
   - **3. EAR** — Engineering Assessment, **approved**. It has
     summary, three recommendations stored as JSON, a budget estimate,
     and two AI review findings (one pass, one warn).
   - **4. SOW / BOQ** — one SOW (Rev 1, approved) with three trade
     sections, and **5 BOQ lines** in the design MTO. You'll see
     delivery statuses: 2 delivered, 1 in_transit, 1 ordered, 1 pending.
   - **5-6. Construction** — status `planned`, schedule with four
     trade windows, and a filed **WCF permit**
     (WCF-2026-0847, filed by Chris Asis).
   - **7. Closeout** — not yet started; the panel shows the empty
     state.

This is what a mid-flight PROJECT looks like. The construction
dashboard's KPIs and the "All Projects" tab pull from this project's
WCF and BOQ rows.

### Try an action

1. Open the **4. SOW / BOQ** tab. Mark BOQ item `P-205` (house
   vacuum line) as **delivered** via the dropdown. The page reloads,
   and the audit trail at the bottom gains a new entry.
2. Switch to **5-6. Construction** and click **File work permit** (or
   update the WCF data). The status pill on the project header
   changes if you progress the construction status.

These actions exercise `sow.manage`, `boq.manage`, and
`work_permit.manage` capabilities. The audit log records who did what
and when.

---

## 5. The completed one — PR-20002 (CLOSEOUT)

Project #7 is fully built and currently in closeout.

1. Open http://localhost:3000/projects/7.
2. **5-6. Construction** shows `completed` with actual `started_at` /
   `completed_at` dates and a four-trade schedule. The WCF was filed
   back in June.
3. **7. Closeout** has a populated `CloseoutRecord`:
   - status `in_progress`
   - testing & commissioning notes
   - as-built drawings **submitted**
   - O&M manuals **submitted**
   - warranty: 2026-08-25 → 2027-08-25, provider Carrier Saudi
   - client sign-off by Layla Karimi on 2026-08-26
   - **three punch list items**: one resolved, one open, one verified
4. Try closing the open punch item: click the "Mark resolved" action
   on item #2 (breaker B-12 label). The `resolved_at` is auto-stamped
   and the audit trail grows.

This is the data the closeout handover to Facilities uses.

---

## 6. The ICR fast-track — PR-20003

Project #8 is the ICR-classified project. This is the most important
page to read carefully because it's where most users get confused.

1. Open http://localhost:3000/projects/8.
2. The stage badge says **MTO_APPROVED**, and the disposition pill
   (next to the stage) says **ICR**.
3. Notice the panel behaviors:
   - **1. MOM** and **2. Disposition** are populated (you still go
     through them — they're not skipped).
   - **3. EAR**, **4. SOW/BOQ**, **5-6. Construction**, **7. Closeout**
     each show a yellow "ICR skips this step" notice. The backend
     returns HTTP 409 if you try to call them directly, which is the
     defense-in-depth that prevents the ICR branch from drifting into
     project territory.
   - The **Attachments** tab still works (attachments are allowed at
     any stage).
4. The ICR handoff flow lives outside the standard tab stepper —
   look for the ICR milestones in the project detail's
   `icr_handoffs` panel (or call `/api/icr/handoffs` from the
   Swagger UI). In the seed, three milestones are recorded:
   `MTO_REVIEW` (completed), `PROJECT_CONTROL_ASSIGN` (in progress),
   `EAT_SCHEDULED` (pending).

The ICR flow is what the procurement team uses for buy-and-install work
that doesn't need a separate construction crew. MTO approval is the
terminal event — the project never reaches `CLOSEOUT`.

---

## 7. The construction dashboard

Go to http://localhost:3000/dashboard/construction.

- **Active Construction** counts projects with a `ConstructionRecord`
  in `planned` / `in_progress` OR a filed WCF. With the seed, that's
  PR-20001 (planned) and PR-20002 (completed — but it has a WCF, so
  counts as having been on the radar). ICR projects are excluded.
- **Active WCF Permits** counts projects where `wcf_data.filed_at` is
  set. Both #6 and #7 have WCFs.
- **Design BOQ Lines** sums design-kind `BoqMtoItem` rows; **BOQ
  Delivery Rate** is the % of those marked `delivered` or `installed`.
- The **All Projects** tab shows each PROJECT-classified project
  (ICR excluded) with WCF count and BOQ delivery progress. The
  pre-construction projects (#4, #5) don't show up because they're
  not "in construction" by the dashboard's definition.

---

## 8. The audit trail (every project)

Every project page ends with an **AuditTrail** that shows, in reverse
chronological order, every action the system has recorded: project
creation, MOM draft/send/confirm, stage transitions, BOQ updates, WCF
filings, punch list resolutions. The transition rows include the
`from` and `to` stage in the `detail` JSON.

This is the system-of-record for "what happened on this PR." It's
populated exclusively through `workflow.log_action()` — there is no
other write path to the audit log, which is what makes it trustworthy.

---

## 9. The role / capability matrix

The seed gives you one user per role so you can see capability gating
in action. To test it:

1. In the top-right header, click **Log out**.
2. Sign in as `chris.asis` / `demo-pass-1` (role: `trade`).
3. Open a project. The MOM, EAR, SOW panels are read-only. The
   Construction panel and the punch list are editable (Chris is a
   trade worker, not engineering or procurement).
4. Log out and sign in as `nadia.haddad` / `demo-pass-1` (role:
   `engineering`). Now MOM, EAR, SOW, BOQ are editable, but
   procurement actions aren't.
5. Sign back in as `admin` to restore full access.

The full capability matrix lives in `backend/app/core/rbac.py`
(`ROLE_DEFAULT_PERMISSIONS`).

---

## 10. Re-seeding and starting over

If you break something, or just want a clean slate:

```powershell
cd backend
.venv\Scripts\python.exe -m scripts.seed_demo
```

The script wipes only the demo PR numbers (`PR-12623`, `PR-12643`,
`PR-20001`, `PR-20002`, `PR-20003`) and their child rows. Real
projects you create by hand are left alone.

If you want a *truly* empty database (which is rarely what you want,
because the admin user is recreated by the lifespan anyway), delete
`backend/dev.db` and restart the backend — `lifespan` will rebuild
the schema and seed the admin user with `admin` / `admin123`.

---

## 11. Cheat sheet — where everything lives

| Concern | File |
| --- | --- |
| Workflow state machine | `backend/app/services/workflow.py` |
| RBAC + capability matrix | `backend/app/core/rbac.py` |
| Project detail API | `backend/app/api/projects.py` |
| Construction + dashboard | `backend/app/api/construction.py` |
| BOQ / SOW / EAR / MOM endpoints | `backend/app/api/{sow_boq,ear,mom,closeout}.py` |
| ICR branch | `backend/app/api/icr.py` |
| AI provider (graceful degradation) | `backend/app/ai/{provider,retrieval,corpus}.py` |
| Frontend project page | `frontend/src/app/projects/[id]/page.tsx` |
| Frontend stage panels | `frontend/src/components/project/{Mom,Disposition,Ear,SowBoq,Construction,Closeout}Panel.tsx` |
| Construction dashboard | `frontend/src/app/dashboard/construction/page.tsx` |
| API client | `frontend/src/lib/api.ts` |
| Capability hook | `frontend/src/lib/useUser.ts` |
| Demo seed | `backend/scripts/seed_demo.py` |

---

## 12. What's intentionally not in the seed

These are real gaps, not bugs. Knowing them saves time:

- **No email transport.** SMTP settings are off, so MOM emails go
  into a draft folder rather than out the door. The MOM record
  still has `email_subject` / `email_body` so the UI shows what
  *would* have been sent.
- **No AI corpus.** The Ollama client is wired up but if you don't
  have a local `llama3.2:3b` model, `/api/ai/ask` returns an
  extractive answer. The seed doesn't include any corpus documents.
- **No document files.** `ear_records.docx_filename` is set, but
  the actual `.docx` isn't generated. Use the EAR panel's
  **Generate document** action to create one in
  `backend/data/projects/<pr>/ear/`.
- **No `MaterialTrackingItem` or standalone `WorkPermit` table.**
  Per the audit, the v1 schema keeps WCF data on
  `ConstructionRecord.wcf_data`. The construction dashboard has
  no Materials or Permits tab for that reason.
