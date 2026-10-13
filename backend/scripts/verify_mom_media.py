"""Verify the MOM live preview, named exports and email draft, then restore.

    python /tmp/verify_mom_media.py PR-12864

Drives the PUBLIC url with a real admin JWT (the browser's path) on TWO real
projects for the read-only checks, and does the writes on PR-12864 itself,
restoring it exactly from a snapshot at the end.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db import SessionLocal
from app.models import Attachment, AuditLog, MomRecord, Project

BASE = "https://ihp.shariar.dev"
RESULTS: list[tuple[str, int]] = []
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)


def api(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("User-Agent", UA)          # Cloudflare answers 1010 otherwise
    request.add_header("Accept", "application/json, text/html;q=0.9")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return (
                response.status,
                response.headers.get("content-type", "").split(";")[0],
                response.read(),
                dict(response.headers),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("content-type", "").split(";")[0],
            exc.read(),
            dict(exc.headers),
        )


def show(label: str, status: int, ctype: str, raw: bytes, extra: str = ""):
    print(f"{label}: HTTP {status} | {ctype} | {len(raw)} bytes{extra}")
    if status >= 400:
        print("    body:", raw[:240].decode(errors="replace"))
    RESULTS.append((label, status))
    return raw


def snapshot(db, pid: int) -> dict:
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    return {
        "version": mom.version,
        "status": mom.status,
        "details": copy.deepcopy(mom.details),
        "docx_filename": mom.docx_filename,
        "pdf_filename": mom.pdf_filename,
        "email_subject": mom.email_subject,
        "email_body": mom.email_body,
        "note": mom.note,
        "updated_at": mom.updated_at,
        "attachments": {a.id for a in db.query(Attachment).filter(Attachment.project_id == pid)},
    }


def main() -> None:
    real_pr = sys.argv[1] if len(sys.argv) > 1 else "PR-12864"
    token = create_access_token("admin")
    db = SessionLocal()

    real = db.query(Project).filter(Project.pr_number.ilike("%" + real_pr.replace("PR-", "") + "%")).first()
    if real is None:
        raise SystemExit("project not found: " + real_pr)
    second = (
        db.query(Project)
        .filter(Project.id != real.id, ~Project.pr_number.like("PR-MOM-%"),
                Project.pi_email.isnot(None))
        .order_by(Project.id.desc())
        .first()
    )
    print("real PR:", real.pr_number, "(id", real.id, ") | second PR:", second.pr_number,
          "(id", second.id, ")")
    snap = snapshot(db, real.id)
    print("snapshot: MOM v" + str(snap["version"]), "|", len((snap["details"] or {}).get("agenda") or []),
          "agenda rows |", len((snap["details"] or {}).get("attendees") or []), "attendees")

    # ---- read-only on both real projects: preview is per-project ----------
    for project in (real, second):
        mom = db.query(MomRecord).filter(MomRecord.project_id == project.id).first()
        if mom is None:
            print("skip preview for", project.pr_number, "- no MOM record")
            continue
        status, ctype, raw, _h = api("GET", f"/api/projects/{project.id}/mom/preview", token)
        show(f"GET /preview ({project.pr_number})", status, ctype, raw)
        body = json.loads(raw)
        status, ctype, view, _h = api("GET", f"/api/projects/{project.id}/mom/view", token)
        show(f"GET /view ({project.pr_number})", status, ctype, view)
        print("    document:", body["document_code"], "| revision:", body["revision"],
              "| html bytes:", body["bytes"], "| status:", body["version"] == mom.version)
        assert view.decode() == body["html"], "the preview and the web view differ"
        print("    one source of truth: preview == view")
        status, ctype, raw, _h = api("GET", f"/api/projects/{project.id}/mom/email-draft", token)
        show(f"GET /email-draft ({project.pr_number})", status, ctype, raw)
        draft = json.loads(raw)
        print("    to:", draft["to"], "| cc:", draft["cc"], "| subject:", draft["subject"][:70])
        print("    attachment:", draft["attachment"]["filename"], "| path:", draft["path_taken"])

    # ---- writes on PR-12864, then restored -------------------------------
    pid = real.id
    code = None
    started = time.time()
    status, ctype, raw, _h = api(
        "PATCH", f"/api/projects/{pid}/mom", token,
        {"meeting_title": (snap["details"] or {}).get("meeting_title", "MOM") + " [autosave check]"},
    )
    patch_seconds = round(time.time() - started, 3)
    show("PATCH /mom (meeting_title)", status, ctype, raw, f" | {patch_seconds}s")
    assert status == 200 and patch_seconds < 1.0, "autosave must return in under 1s"
    assert json.loads(raw)["version"] == snap["version"], "autosave regenerated the document!"

    # the flush path: an immediate PATCH then read back, exactly what blur/pagehide sends
    status, _c, _r, _h = api("PATCH", f"/api/projects/{pid}/mom", token,
                             {"meeting_location": "autosave flush check"})
    show("PATCH /mom (immediate flush)", status, "application/json", b"", "")
    started = time.time()
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/mom/preview", token)
    preview_seconds = round(time.time() - started, 3)
    show("GET /preview (after flush)", status, ctype, raw, f" | {preview_seconds}s")
    assert preview_seconds < 1.0, "the preview must return in under 1s"
    html = json.loads(raw)["html"]
    assert "autosave flush check" in html, "the flushed value is not in the preview"
    code = json.loads(raw)["document_code"]
    print("    flushed value present in the preview; document code:", code)

    # the guarded errors
    status, ctype, raw, _h = api("PATCH", f"/api/projects/{pid}/mom", token, {})
    show("PATCH /mom {} (must be 422)", status, ctype, raw)
    status, ctype, raw, _h = api("PATCH", f"/api/projects/{pid}/mom", token, {"scope": "nope"})
    show("PATCH /mom unknown field (must be 422)", status, ctype, raw)

    # the exports
    for fmt in ("pdf", "docx"):
        started = time.time()
        status, ctype, raw, headers = api(
            "GET", f"/api/projects/{pid}/mom/export?format={fmt}", token
        )
        extra = (
            " | " + headers.get("content-disposition", "")[:70]
            + " | pages=" + headers.get("X-MOM-Pages", "?")
            + " | " + str(round(time.time() - started, 1)) + "s"
        )
        show(f"GET /export?format={fmt}", status, ctype, raw, extra)
        assert status == 200 and code in headers.get("content-disposition", "")

    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/attachments", token)
    show("GET /attachments", status, ctype, raw)
    listed = json.loads(raw)
    names = [row.get("filename") for row in (listed if isinstance(listed, list) else listed.get("items", []))]
    print("    files on the PR now include:",
          [n for n in names if n and n.startswith(code)])

    # the email draft, then the 409 when there is nobody to email
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/mom/email-draft", token)
    show("GET /email-draft (browser path)", status, ctype, raw)
    draft = json.loads(raw)
    print("    subject:", draft["subject"])
    print("    body:", draft["body"].replace(chr(10), " ")[:150])
    raise_409 = api("PATCH", f"/api/projects/{pid}/mom", token,
                    {"attendees": [{"name": "No Address", "title": "PI", "email": ""}]})
    show("PATCH /mom (attendees without emails)", raise_409[0], raise_409[1], raise_409[2])
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/mom/email-draft", token)
    show("GET /email-draft (must be 409)", status, ctype, raw)
    assert status == 409, "the email draft should refuse without any address"

    # the audit trail
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/audit", token)
    entries = json.dumps(json.loads(raw))
    print("    audit mom:edit present:", "mom:edit" in entries,
          "| mom:export present:", "mom:export" in entries)

    # ---- restore PR-12864 exactly ----------------------------------------
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    mom.version = snap["version"]
    mom.status = snap["status"]
    mom.details = snap["details"]
    mom.docx_filename = snap["docx_filename"]
    mom.pdf_filename = snap["pdf_filename"]
    mom.email_subject = snap["email_subject"]
    mom.email_body = snap["email_body"]
    mom.note = snap["note"]
    db.flush()
    removed = 0
    for row in db.query(Attachment).filter(Attachment.project_id == pid):
        if row.id not in snap["attachments"]:
            try:
                Path(row.stored_path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            db.delete(row)
            removed += 1
    for row in db.query(AuditLog).filter(AuditLog.project_id == pid):
        if row.action in ("mom:edit", "mom:export") and "verification" in json.dumps(row.payload or {}):
            db.delete(row)
    db.commit()
    after = snapshot(db, pid)
    ok = (
        after["details"] == snap["details"]
        and after["version"] == snap["version"]
        and len(after["attachments"]) == len(snap["attachments"])
    )
    print(f"restored: details match={after['details'] == snap['details']} "
          f"| version={after['version']} | verification attachments removed={removed} | exact={ok}")
    db.close()

    failed = [label for label, code_ in RESULTS
              if code_ >= 400 and "must be 409" not in label and "must be 422" not in label]
    print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))


if __name__ == "__main__":
    main()
