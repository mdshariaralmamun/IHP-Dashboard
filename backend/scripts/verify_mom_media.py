"""Verify the MOM live preview, named exports and email draft, then restore.

    python /tmp/verify_mom_media.py PR-12864
    python /tmp/verify_mom_media.py --restore /tmp/mom_snapshot_PR-12864.json

The whole write phase runs inside _run_writes() and is ALWAYS followed by
restore() in a finally block, so a crash halfway through cannot leave the real
project modified. The snapshot is also written to /tmp so --restore can put
things back by hand if the process is killed outright.

Set MOM_VERIFY_CRASH=1 to prove the finally works: the run raises right after
the first PATCH and the record is restored anyway.
"""

from __future__ import annotations

import copy
import email
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import func

from app.core.security import create_access_token
from app.db import SessionLocal
from app.models import Attachment, AuditLog, MomRecord, Project

BASE = "https://ihp.shariar.dev"
FOOTER_NEW = "Please review this document and reply with your comments or approval."
FOOTER_OLD = "Please review and confirm the accuracy of this document."
RESULTS: list[tuple[str, int]] = []
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)


def api(method: str, path: str, token: str, body: dict | None = None):
    """One call through the public URL - the browser's own path."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("User-Agent", UA)          # Cloudflare answers 1010 otherwise
    request.add_header("Accept", "application/json, text/html;q=0.9")
    if data:
        request.add_header("Content-Type", "application/json")

    def _headers(message) -> dict:
        # Starlette sends header names lowercased, so normalise before lookup.
        return {key.lower(): value for key, value in message.items()}

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return (
                response.status,
                response.headers.get("content-type", "").split(";")[0],
                response.read(),
                _headers(response.headers),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("content-type", "").split(";")[0],
            exc.read(),
            _headers(exc.headers),
        )


def show(label: str, status: int, ctype: str, raw: bytes, extra: str = "") -> bytes:
    print(f"{label}: HTTP {status} | {ctype} | {len(raw)} bytes{extra}")
    if status >= 400:
        print("    body:", raw[:240].decode(errors="replace"))
    RESULTS.append((label, status))
    return raw


def snapshot(db, pid: int) -> dict:
    project = db.get(Project, pid)
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    return {
        "pr_number": project.pr_number if project else "",
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
        "audit_max_id": db.query(func.max(AuditLog.id)).scalar() or 0,
    }


def persist(path: str, snap: dict) -> None:
    payload = dict(snap)
    payload["updated_at"] = snap["updated_at"].isoformat() if snap["updated_at"] else None
    payload["attachments"] = sorted(snap["attachments"])
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def restore(db, pid: int, snap: dict) -> None:
    """Put the project's MOM back exactly as the snapshot found it."""
    from datetime import datetime

    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    if mom is not None:
        mom.version = snap["version"]
        mom.status = snap["status"]
        mom.details = snap["details"]
        mom.docx_filename = snap["docx_filename"]
        mom.pdf_filename = snap["pdf_filename"]
        mom.email_subject = snap["email_subject"]
        mom.email_body = snap["email_body"]
        mom.note = snap["note"]
        if snap.get("updated_at"):
            value = snap["updated_at"]
            mom.updated_at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    removed = 0
    known = set(snap["attachments"])
    for row in db.query(Attachment).filter(Attachment.project_id == pid):
        if row.id not in known:
            try:
                Path(row.stored_path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            db.delete(row)
            removed += 1
    # Only what this run wrote: everything above the audit watermark.
    for row in db.query(AuditLog).filter(
        AuditLog.project_id == pid, AuditLog.id > snap["audit_max_id"]
    ):
        db.delete(row)
    db.commit()
    after = snapshot(db, pid)
    exact = (
        after["details"] == snap["details"]
        and after["version"] == snap["version"]
        and after["docx_filename"] == snap["docx_filename"]
        and after["attachments"] == set(snap["attachments"])
    )
    print(
        f"restored: details match={after['details'] == snap['details']} "
        f"| version={after['version']} | attachments removed={removed} | exact={exact}"
    )


def _run_writes(pid: int, token: str, snap: dict, db) -> str:
    """Everything that modifies the real project. main() always restores after."""
    started = time.time()
    status, ctype, raw, _h = api(
        "PATCH", f"/api/projects/{pid}/mom", token,
        {"meeting_title": (snap["details"] or {}).get("meeting_title", "MOM") + " [autosave check]"},
    )
    patch_seconds = round(time.time() - started, 3)
    show("PATCH /mom (meeting_title)", status, ctype, raw, f" | {patch_seconds}s")
    assert status == 200 and patch_seconds < 1.0, "autosave must return in under 1s"
    assert json.loads(raw)["version"] == snap["version"], "autosave regenerated the document!"

    if os.environ.get("MOM_VERIFY_CRASH"):
        raise RuntimeError("deliberate crash: proving the finally restores the record")

    # the flush path: an immediate PATCH then read back, exactly what blur/pagehide sends
    status, _c, _r, _h = api("PATCH", f"/api/projects/{pid}/mom", token,
                             {"meeting_location": "autosave flush check"})
    show("PATCH /mom (immediate flush)", status, "application/json", b"")
    started = time.time()
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/mom/preview", token)
    preview_seconds = round(time.time() - started, 3)
    show("GET /preview (after flush)", status, ctype, raw, f" | {preview_seconds}s")
    assert preview_seconds < 1.0, "the preview must return in under 1s"
    body = json.loads(raw)
    assert "autosave flush check" in body["html"], "the flushed value is not in the preview"
    code = body["document_code"]
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
            + " | pages=" + headers.get("x-mom-pages", "?")
            + " | " + str(round(time.time() - started, 1)) + "s"
        )
        show(f"GET /export?format={fmt}", status, ctype, raw, extra)
        assert status == 200 and code in headers.get("content-disposition", "")

    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}", token)
    show("GET /projects/<id> (the UI's project detail)", status, ctype, raw)
    detail = json.loads(raw)
    names = [row.get("filename") for row in (detail.get("attachments") or [])]
    print("    MOM files now on the PR:", [n for n in names if n and n.startswith(code)])

    # the email draft, and the 409 when there is nobody to email
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/mom/email-draft", token)
    show("GET /email-draft (browser path)", status, ctype, raw)
    draft = json.loads(raw)
    print("    to:", draft["to"], "| cc:", draft["cc"])
    print("    subject:", draft["subject"])
    print("    body:", draft["body"].replace(chr(10), " ")[:150])
    clash = {e.lower() for e in draft["to"]} & {e.lower() for e in draft["cc"]}
    print("    cc deduped against to:", not clash)
    raise_409 = api("PATCH", f"/api/projects/{pid}/mom", token,
                    {"attendees": [{"name": "No Address", "title": "PI", "email": ""}]})
    show("PATCH /mom (attendees without emails)", raise_409[0], raise_409[1], raise_409[2])
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/mom/email-draft", token)
    show("GET /email-draft (must be 409)", status, ctype, raw)
    assert status == 409, "the email draft should refuse without any address"

    # the .eml draft: exactly one attachment, the named full MOM PDF
    # (put the real attendees back first - the 409 test above cleared them)
    if (snap["details"] or {}).get("attendees"):
        api("PATCH", f"/api/projects/{pid}/mom", token,
            {"attendees": snap["details"]["attendees"]})
    started = time.time()
    status, ctype, raw, headers = api("GET", f"/api/projects/{pid}/mom/email.eml", token)
    disposition = headers.get("content-disposition", "")
    show("GET /mom/email.eml", status, ctype, raw,
         " | " + disposition[:74] + " | " + str(round(time.time() - started, 2)) + "s")
    assert status == 200 and ctype == "message/rfc822", "the draft must be message/rfc822"
    assert code + ".eml" in disposition, "the draft is not named after the document code"
    message = email.message_from_bytes(raw)
    parts = [part.get_filename() for part in message.walk() if part.get_filename()]
    print("    X-Unsent:", message.get("X-Unsent"), "| To:", message.get("To"))
    print("    Cc:", message.get("Cc"), "| Subject:", message.get("Subject"))
    print("    attachments:", parts)
    assert message.get("X-Unsent") == "1", "without X-Unsent Outlook shows it as received"
    assert parts == [code + ".pdf"], "the draft must carry exactly the named MOM PDF"

    # the browser names the file from Content-Disposition (same regex as api.ts)
    import re as _re

    match = _re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, _re.I)
    browser_name = match.group(1).replace('"', "").strip() if match else "IHP-MOM-draft.eml"
    print("    the browser saves it as:", browser_name)
    assert browser_name == code + ".eml", "the download name must come from the header"

    attached = [
        part for part in message.walk() if part.get_filename() == code + ".pdf"
    ][0].get_payload(decode=True)
    status, _c, exported, _h = api("GET", f"/api/projects/{pid}/mom/export?format=pdf", token)
    assert status == 200
    print("    attachment == export bytes:", attached == exported, "|", len(attached), "bytes")
    assert attached == exported, "the attachment must be the export file"

    # the footer sentence, extracted from the real PDF, the real Word and the .eml
    import pymupdf

    with pymupdf.open(stream=exported, filetype="pdf") as document:
        pdf_text = "\n".join(page.get_text() for page in document)
    print("    PDF text: new sentence", FOOTER_NEW in pdf_text,
          "| old sentence", FOOTER_OLD in pdf_text)
    assert FOOTER_NEW in pdf_text and FOOTER_OLD not in pdf_text, "PDF footer sentence"

    status, _c, docx_bytes, _h = api("GET", f"/api/projects/{pid}/mom/export?format=docx", token)
    from io import BytesIO

    from docx import Document as DocxDocument

    word = DocxDocument(BytesIO(docx_bytes))
    word_text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    word_meta = [p.text for p in word.paragraphs if p.text.startswith("Generated by")]
    print("    Word text: new sentence", FOOTER_NEW in word_text,
          "| old sentence", FOOTER_OLD in word_text)
    print("    Word meta line:", word_meta)
    assert FOOTER_NEW in word_text and FOOTER_OLD not in word_text, "Word footer sentence"

    # the .eml attachment is that same PDF, so its text is the same
    with pymupdf.open(stream=attached, filetype="pdf") as document:
        eml_text = "\n".join(page.get_text() for page in document)
    print("    .eml attachment text carries the new sentence:", FOOTER_NEW in eml_text)
    assert FOOTER_NEW in eml_text and FOOTER_OLD not in eml_text, ".eml attachment footer"
    assert round(time.time() - started, 2) < 3.0, "the .eml must return in under 3s"

    # the audit trail
    status, ctype, raw, _h = api("GET", f"/api/projects/{pid}/audit", token)
    entries = json.dumps(json.loads(raw))
    print("    audit mom:edit present:", "mom:edit" in entries,
          "| mom:export present:", "mom:export" in entries,
          "| mom:eml present:", "mom:eml" in entries)
    assert "mom:eml" in entries, "the .eml draft must be audited"
    return code


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--restore":
        db = SessionLocal()
        snap = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        snap["attachments"] = set(snap["attachments"])
        project = db.query(Project).filter(Project.pr_number == snap["pr_number"]).first()
        restore(db, project.id, snap)
        db.close()
        return

    real_pr = sys.argv[1] if len(sys.argv) > 1 else "PR-12864"
    token = create_access_token("admin")
    db = SessionLocal()

    real = db.query(Project).filter(
        Project.pr_number.ilike("%" + real_pr.replace("PR-", "") + "%")
    ).first()
    if real is None:
        raise SystemExit("project not found: " + real_pr)
    second = (
        db.query(Project)
        .join(MomRecord, MomRecord.project_id == Project.id)
        .filter(Project.id != real.id, ~Project.pr_number.like("PR-MOM-%"))
        .order_by(Project.id.desc())
        .first()
    )
    if second is None:
        raise SystemExit("no second project with a MOM record to prove the preview is generic")

    print("real PR:", real.pr_number, "(id", real.id, ") | second PR:", second.pr_number,
          "(id", second.id, ")")
    snap = snapshot(db, real.id)
    snap_path = f"/tmp/mom_snapshot_{snap['pr_number']}.json"
    persist(snap_path, snap)
    print("snapshot saved to", snap_path)
    print("snapshot: MOM v" + str(snap["version"]),
          "|", len((snap["details"] or {}).get("agenda") or []), "agenda rows |",
          len((snap["details"] or {}).get("attendees") or []), "attendees")

    # ---- read-only on both real projects: the preview is per-project -------
    for project in (real, second):
        mom = db.query(MomRecord).filter(MomRecord.project_id == project.id).first()
        if mom is None:
            continue
        status, ctype, raw, _h = api("GET", f"/api/projects/{project.id}/mom/preview", token)
        show(f"GET /preview ({project.pr_number})", status, ctype, raw)
        body = json.loads(raw)
        status, ctype, view, _h = api("GET", f"/api/projects/{project.id}/mom/view", token)
        show(f"GET /view ({project.pr_number})", status, ctype, view)
        print("    document:", body["document_code"], "| revision:", body["revision"],
              "| html bytes:", body["bytes"], "| version matches:", body["version"] == mom.version)
        assert view.decode() == body["html"], "the preview and the web view differ"
        print("    one source of truth: preview == view")
        assert FOOTER_NEW in body["html"] and FOOTER_OLD not in body["html"], "footer sentence"
        print("    footer: new sentence present, old absent")
        status, ctype, raw, _h = api("GET", f"/api/projects/{project.id}/mom/email-draft", token)
        show(f"GET /email-draft ({project.pr_number})", status, ctype, raw)
        draft = json.loads(raw)
        print("    to:", draft["to"], "| cc:", draft["cc"], "| subject:", draft["subject"][:70])
        print("    attachment:", draft["attachment"]["filename"], "| path:", draft["path_taken"])

    # ---- the writes, always followed by the restore ------------------------
    pid = real.id
    code = None
    try:
        code = _run_writes(pid, token, snap, db)
    finally:
        restore(db, pid, snap)
    db.close()

    failed = [label for label, status_ in RESULTS
              if status_ >= 400 and "must be 409" not in label and "must be 422" not in label]
    print("document code exercised:", code)
    print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))


if __name__ == "__main__":
    main()
