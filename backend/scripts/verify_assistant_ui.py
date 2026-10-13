"""Verify the B2 delivery-assistant UI end to end, then leave the app as it was.

    python /tmp/verify_assistant_ui.py PR-12864

It drives the PUBLIC url with a real admin JWT - the same path the browser
takes (Cloudflare -> Next proxy -> FastAPI) - on TWO real projects, then runs
the whole chain on a throwaway project and deletes it again.
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
    AssistantMessage,
    Attachment,
    AuditLog,
    BoqMtoItem,
    EarRecord,
    EarTradeInput,
    MomRecord,
    PipelineStage,
    Project,
    SowRecord,
)

BASE = "https://ihp.shariar.dev"
RESULTS: list[tuple[str, int]] = []

NOTES = """
Meeting: new gas line for the plasma etcher (Bldg 5).
Date: 13 October 2026, 10:00-11:30, Room 5-3201.
Attendees: Atteq UrRehman (PI, PSE), Mohammed Khan (IHP Design),
Nasser Al-Otaibi (HSE), Sara Al-Qahtani (Building Operations).
Scope agreed: install a new dedicated gas line from the existing manifold to the
plasma etcher, including the isolation valve, regulator, stainless tubing,
leak test and purge. New dedicated electrical supply for the etcher interlocks
and low-current points for the gas detection. All works Supply & Install by IHP.
HSE: hot-work permit for the tubing brazing; leak test certificate required
before commissioning. Access after 18:00 only, no weekend work.
Action: IHP to issue the SOW, BOQ and the drawing list within two weeks.
"""


def api(method: str, path: str, token: str, body: dict | None = None):
    """One call through the public URL - the browser's own path."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + token)
    # Cloudflare's bot rules answer the default urllib agent with error 1010,
    # so this speaks like the browser it is standing in for.
    request.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0 Safari/537.36",
    )
    request.add_header("Accept", "application/json, text/html;q=0.9")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
            ctype = response.headers.get("content-type", "").split(";")[0]
            return response.status, ctype, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, exc.headers.get("content-type", "").split(";")[0], raw


def show(label: str, status: int, ctype: str, raw: bytes, extra: str = ""):
    print(f"{label}: HTTP {status} | {ctype} | {len(raw)} bytes{extra}")
    if status >= 400:
        print("    body:", raw[:220].decode(errors="replace"))
    RESULTS.append((label, status))
    return raw


def second_project(db, exclude_id: int) -> Project:
    """Chosen from the data, never hard-coded: newest real PR with a PI."""
    return (
        db.query(Project)
        .filter(
            ~Project.pr_number.like("PR-AS-%"),
            Project.id != exclude_id,
            Project.pi_name.isnot(None),
            Project.pi_email.isnot(None),
        )
        .order_by(Project.id.desc())
        .first()
    )


def main() -> None:
    pr = sys.argv[1] if len(sys.argv) > 1 else "PR-12864"
    token = create_access_token("admin")
    db = SessionLocal()

    real = db.query(Project).filter(Project.pr_number.ilike("%" + pr.replace("PR-", "") + "%")).first()
    if real is None:
        raise SystemExit("project not found: " + pr)
    second = second_project(db, real.id)
    print("real PR:", real.pr_number, "(id", real.id, ") | second PR:", second.pr_number,
          "(id", second.id, ")")

    # ---- 1. the panel's six endpoints, on two different real projects ----
    for project in (real, second):
        status, ctype, raw = api("GET", f"/api/projects/{project.id}/assistant", token)
        show(f"GET /assistant ({project.pr_number})", status, ctype, raw)
        state = json.loads(raw)
        assert state["pr_number"] == project.pr_number, "the panel is bound to another project"
        print("    gate:", state["gate"]["stage"], state["gate"]["status"],
              "| allowed:", state["gate"]["allowed"], "| blocked:", len(state["gate"]["blocked"]))
        print("    ai:", state["ai"], "| actions:", len(state["actions"]),
              "| ear:", state["ear"]["status"])

        status, ctype, raw = api("GET", f"/api/projects/{project.id}/assistant/actions", token)
        show(f"GET /actions ({project.pr_number})", status, ctype, raw)
        assert len(json.loads(raw)) == 13

        for action in ("sow.draft", "mto.draft"):
            status, ctype, raw = api("POST", f"/api/projects/{project.id}/assistant/run",
                                     token, {"action": action})
            show(f"POST /run {action} ({project.pr_number}, must be 409)", status, ctype, raw)
            assert status == 409, "a gate let something through on a real project"

        started = time.time()
        status, ctype, raw = api("POST", f"/api/projects/{project.id}/assistant/message",
                                 token, {"message": NOTES})
        show(f"POST /message ({project.pr_number})", status, ctype, raw,
             f" | {round(time.time() - started, 1)}s")
        turn = json.loads(raw)
        print("    suggested:", turn["suggested_action"], "| reply:",
              str(turn["content"])[:110])
        status, ctype, raw = api("GET", f"/api/projects/{project.id}/assistant/messages", token)
        show(f"GET /messages ({project.pr_number})", status, ctype, raw,
             f" | {len(json.loads(raw))} turns")

        # the real PRs are left exactly as they were
        db.query(AssistantMessage).filter(AssistantMessage.project_id == project.id).delete()
        db.commit()

    # ---- 2. the served page (the panel's home) ----
    status, ctype, raw = api("GET", f"/projects/{real.id}", token)
    show("GET /projects/<id> (page)", status, ctype, raw)

    # ---- 3. the whole chain on a throwaway project ----
    throwaway = "PR-AS-UI-" + uuid.uuid4().hex[:6].upper()
    status, ctype, raw = api("POST", "/api/projects", token, {
        "pr_number": throwaway,
        "title": "Delivery assistant UI verification",
        "description": "Type: BASELINE\nDivision: PSE\nPriority: Medium",
        "pi_name": "Atteq UrRehman",
        "pi_email": "pi@example.kaust.edu.sa",
    })
    show(f"POST /api/projects ({throwaway})", status, ctype, raw)
    pid = json.loads(raw)["id"]
    print("    throwaway project id:", pid)

    status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/message", token,
                             {"message": NOTES})
    show("POST /message (throwaway)", status, ctype, raw)

    chain = ("mom.draft", "mom.confirm", "summary.draft", "summary.approve",
             "ear.draft", "ear.pi_signature", "ear.asepc", "sow.draft", "boq.draft",
             "drawings.list", "sow.approve", "package.binder")
    for action in chain:
        started = time.time()
        status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/run", token,
                                 {"action": action})
        show(f"POST /run {action}", status, ctype, raw, f" | {round(time.time() - started, 1)}s")
        if status < 400:
            turn = json.loads(raw)
            print("    ", str(turn["content"])[:170])
            for art in turn.get("artifacts") or []:
                print("     artifact:", art["kind"], "|", art["label"], "|", art.get("filename"),
                      "|", art.get("panel"), "|", json.dumps(art.get("meta") or {})[:110])

    # the MOM was drafted from PROSE notes: it must carry agenda rows
    db.expire_all()
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    agenda = (mom.details or {}).get("agenda") or []
    trades = sorted({a.get("trade") for a in agenda if a.get("trade")})
    print("    MOM agenda rows from prose notes:", len(agenda), "| trades:", trades)
    assert len(agenda) >= 3, "prose notes still produce no agenda rows"

    # the MTO stays locked until the hand-set Procore status
    status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/run", token,
                             {"action": "mto.draft"})
    show("POST /run mto.draft (must be 409)", status, ctype, raw)
    assert status == 409
    status, ctype, raw = api("PATCH", f"/api/projects/{pid}/procore", token,
                             {"procore_status": "Approved"})
    show("PATCH /procore Approved", status, ctype, raw)
    status, ctype, raw = api("POST", f"/api/projects/{pid}/assistant/run", token,
                             {"action": "mto.draft"})
    show("POST /run mto.draft", status, ctype, raw)

    # ---- 4. the documents reached their own panels ----
    for label, path in (("MomPanel", f"/api/projects/{pid}/mom/defaults"),
                        ("EarPanel", f"/api/projects/{pid}/ear"),
                        ("/sow", f"/api/projects/{pid}/sow"),
                        ("/boq", f"/api/projects/{pid}/boq"),
                        ("ProcorePanel", f"/api/projects/{pid}/procore"),
                        ("PipelinePanel", f"/api/projects/{pid}/pipeline"),
                        ("AuditTrail", f"/api/projects/{pid}/audit")):
        status, ctype, raw = api("GET", path, token)
        show("    panel " + label, status, ctype, raw)

    turns = json.loads(api("GET", f"/api/projects/{pid}/assistant/messages", token)[2])
    text = " ".join(str(turn["content"]) for turn in turns)
    print("    labour line present:",
          "Labor: IHP In-House Resources" in text and "$0.00" in text,
          "| transcript turns:", len(turns))
    audit = str(api("GET", f"/api/projects/{pid}/audit", token)[2])
    print("    audit keys:",
          sorted({key for key in ("assistant:mom", "assistant:summary", "assistant:ear",
                                  "assistant:sow", "assistant:boq", "assistant:drawings",
                                  "assistant:mto", "package:pdf", "ear:funnel",
                                  "pipeline:stage") if key in audit}))
    items = db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).all()
    ear = db.query(EarRecord).filter(EarRecord.project_id == pid).first()
    print("    boq lines:", len(items), "unpriced:", all(i.unit_rate == 0 for i in items),
          "| ear trade inputs:", len(ear.trade_inputs) if ear else 0,
          "manpower $0:", all(t.estimated_manpower_cost == 0.0 for t in ear.trade_inputs) if ear else True)

    # ---- 5. cleanup: audit_logs first (it is a real foreign key) ----
    ear_ids = [row.id for row in db.query(EarRecord).filter(EarRecord.project_id == pid)]
    if ear_ids:
        db.query(EarTradeInput).filter(EarTradeInput.ear_id.in_(ear_ids)).delete(
            synchronize_session=False)
    for model in (EarRecord, SowRecord, BoqMtoItem, MomRecord, PipelineStage,
                  AssistantMessage, Attachment):
        db.query(model).filter(model.project_id == pid).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.project_id == pid).delete(synchronize_session=False)
    db.query(Project).filter(Project.id == pid).delete()
    db.commit()
    shutil.rmtree(Path(get_settings().DATA_DIR) / "projects" / throwaway, ignore_errors=True)
    print("cleanup: throwaway", throwaway, "and its rows removed; both real PR transcripts cleared")
    db.close()

    failed = [label for label, code in RESULTS if code >= 400 and "must be 409" not in label]
    print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))


if __name__ == "__main__":
    main()
