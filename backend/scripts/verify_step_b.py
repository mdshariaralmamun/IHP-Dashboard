"""Verify Step B (Procore comment log + Rev 1) against the live app, then clean up."""
import io
import sys

import openpyxl
import pymupdf
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db import SessionLocal
from app.main import app
from app.models import Attachment, ProcoreComment, Project

db = SessionLocal()
pr = sys.argv[1] if len(sys.argv) > 1 else "12718"
project = db.query(Project).filter(Project.pr_number.ilike("%" + pr + "%")).first()
if project is None:
    raise SystemExit("project not found: " + pr)
pid = project.id
before_attachments = {a.id for a in db.query(Attachment).filter(Attachment.project_id == pid).all()}
print("project", pid, project.pr_number, "|", (project.title or "")[:60])

client = TestClient(app)
H = {"Authorization": "Bearer " + create_access_token("admin")}
results = []


def show(label, resp):
    ctype = resp.headers.get("content-type", "")
    print(label + ": HTTP " + str(resp.status_code) + " | " + ctype.split(";")[0] + " | " + str(len(resp.content)) + " bytes")
    if resp.status_code >= 400:
        print("    body:", resp.text[:200])
    results.append((label, resp.status_code))
    return resp


# 1. state + vocabulary
r = show("GET  /procore", client.get("/api/projects/" + str(pid) + "/procore", headers=H))
body = r.json()
print("    reviewers:", body.get("reviewers"))
print("    statuses :", body.get("statuses"))
print("    state    :", {k: v for k, v in body.items() if k != "comments"})

# 2. add a reviewer comment
r = show("POST /procore/comments", client.post(
    "/api/projects/" + str(pid) + "/procore/comments", headers=H,
    json={
        "reviewer": "HSE Team",
        "department": "HSE",
        "discipline": "Fire & Life Safety",
        "comment": "Verification row: confirm the isolation valve tag numbers on the P&ID.",
    },
))
cid = r.json().get("id") if r.status_code == 201 else None
if cid:
    print("    item_no:", r.json().get("item_no"), "| revision:", r.json().get("revision"))

# 3. answer it and close it
if cid:
    show("PATCH /procore/comments/{id}", client.patch(
        "/api/projects/" + str(pid) + "/procore/comments/" + str(cid), headers=H,
        json={
            "ihp_response": "Tag numbers added to SOW section 4.2.",
            "action_taken": "SOW Rev 0 updated; drawing M-101 reissued.",
            "status": "closed",
        },
    ))

# 4. the status the reviewer sets in Procore, by hand
show("PATCH /procore", client.patch(
    "/api/projects/" + str(pid) + "/procore", headers=H,
    json={"procore_status": "Revise and Resubmit", "procore_submittal_date": "2026-10-12"},
))

# 5. Comment Log Sheet .xlsx
r = show("GET  /procore/comments/log.xlsx", client.get(
    "/api/projects/" + str(pid) + "/procore/comments/log.xlsx", headers=H))
if r.status_code == 200:
    ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
    print("    sheet:", ws.title, "| rows:", ws.max_row)
    print("    headers:", [ws.cell(row=10, column=c).value for c in range(1, 8)])
    print("    row 11 :", [str(ws.cell(row=11, column=c).value)[:38] for c in range(1, 8)])

# 6. Comment Log Sheet .pdf (LibreOffice print of the sheet)
show("GET  /procore/comments/log.pdf", client.get(
    "/api/projects/" + str(pid) + "/procore/comments/log.pdf", headers=H))

# 7. dropzone: the stamped Procore Submittal PDF
doc = pymupdf.open()
page = doc.new_page()
page.insert_text((72, 96), "Stamped Procore Submittal (verification upload)")
stamped = doc.tobytes()
doc.close()
show("POST /procore/submittal", client.post(
    "/api/projects/" + str(pid) + "/procore/submittal", headers=H,
    files={"file": ("Procore Submittal Rev 0 (stamped).pdf", stamped, "application/pdf")},
))

# 8. the combined binder, now carrying the comment log
r = show("POST /package/pdf", client.post(
    "/api/projects/" + str(pid) + "/package/pdf", headers=H))
if r.status_code == 200:
    out = pymupdf.open(stream=r.content, filetype="pdf")
    first = out[0]
    print("    binder pages:", out.page_count, "| cover:", round(first.rect.width), "x", round(first.rect.height))
    cover = first.get_text()
    print("    cover revision line:", [ln for ln in cover.split("\n") if "Rev" in ln][:2])
    print("    cover contents:", [ln.strip() for ln in cover.split("\n") if "Comment Log" in ln][:2])
    out.close()

# 9. Generate Revision 1 Package
r = show("POST /procore/revise", client.post(
    "/api/projects/" + str(pid) + "/procore/revise", headers=H))
if r.status_code == 200:
    print("    revise:", r.json())

# 10. Rev 1 binder uses the new revision on its cover
r = show("POST /package/pdf?revision=1", client.post(
    "/api/projects/" + str(pid) + "/package/pdf?revision=1", headers=H))
if r.status_code == 200:
    out = pymupdf.open(stream=r.content, filetype="pdf")
    print("    cover revision line:", [ln for ln in out[0].get_text().split("\n") if "Rev" in ln][:2])
    out.close()

# ---- put production back exactly as it was ----
if cid:
    db.query(ProcoreComment).filter(ProcoreComment.id == cid).delete()
fresh = db.query(Attachment).filter(Attachment.project_id == pid).all()
removed = 0
for att in fresh:
    if att.id not in before_attachments:
        db.delete(att)
        removed += 1
project = db.query(Project).filter(Project.id == pid).first()
project.procore_status = None
project.procore_submittal_date = None
project.procore_revision = 0
db.commit()
db.close()
print("cleanup: comment removed:", bool(cid), "| verification attachments removed:", removed)

failed = [label for label, code in results if code >= 400]
print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))
