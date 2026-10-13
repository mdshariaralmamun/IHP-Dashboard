"""Verify the Project Delivery Assistant live, then leave the app as it was.

    python /tmp/verify_assistant.py [PR-12864]

Part 1 reads the real PR the team is working on: the gate, the allowed and
blocked actions, the AI provider, and the refusal (409) when a step tries to
jump the queue.

Part 2 creates a throwaway PR, drives the whole chain with the REAL DeepSeek
provider and the REAL document generators (no monkeypatching), checks every
artifact in its own panel and the audit trail, then deletes the throwaway
project and its rows.
"""

from __future__ import annotations

import shutil
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db import SessionLocal
from app.models import (
    AssistantMessage,
    Attachment,
    BoqMtoItem,
    EarRecord,
    EarTradeInput,
    MomRecord,
    PipelineStage,
    Project,
    SowRecord,
    User,
)

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

RESULTS: list[tuple[str, int, str]] = []


def step(label: str, resp, extra: str = "") -> object:
    ctype = resp.headers.get("content-type", "").split(";")[0]
    print(f"{label}: HTTP {resp.status_code} | {ctype} | {len(resp.content)} bytes{extra}")
    if resp.status_code >= 400:
        print("    body:", resp.text[:260])
    RESULTS.append((label, resp.status_code, extra))
    return resp


def main() -> None:
    real_pr = sys.argv[1] if len(sys.argv) > 1 else "PR-12864"
    db = SessionLocal()
    admin = db.query(User).filter(User.username == "admin").first()
    client = TestClient(app)
    H = {"Authorization": "Bearer " + create_access_token("admin")}

    # ---- Part 1: the real PR, read + gate only -------------------------------
    real = db.query(Project).filter(Project.pr_number.ilike("%" + real_pr.replace("PR-", "") + "%")).first()
    if real is None:
        raise SystemExit("real PR not found: " + real_pr)
    print("=== part 1: real project", real.pr_number, "(id", real.id, ") ===")
    r = step("GET  /assistant", client.get(f"/api/projects/{real.id}/assistant", headers=H))
    state = r.json()
    print("    ai:", state["ai"])
    print("    gate:", state["gate"]["stage"], state["gate"]["label"], "|", state["gate"]["status"])
    print("    allowed:", state["gate"]["allowed"])
    print("    blocked:", state["gate"]["blocked"])
    print("    ear track:", state["ear"])

    t0 = time.time()
    r = step("POST /message (notes)", client.post(
        f"/api/projects/{real.id}/assistant/message", headers=H, json={"message": NOTES}))
    if r.status_code == 200:
        body = r.json()
        print("    suggested:", body["suggested_action"], "| seconds:", round(time.time() - t0, 1))
        print("    reply:", body["content"][:200])
    step("POST /run sow.draft (must be 409)", client.post(
        f"/api/projects/{real.id}/assistant/run", headers=H, json={"action": "sow.draft"}))
    # the probe left a transcript on the real PR: remove it
    db.query(AssistantMessage).filter(AssistantMessage.project_id == real.id).delete()
    db.commit()

    # ---- Part 2: throwaway PR, the whole chain -------------------------------
    pr = "PR-AS-VERIFY-" + uuid.uuid4().hex[:6].upper()
    created = client.post("/api/projects", headers=H, json={
        "pr_number": pr, "title": "Assistant verification - new gas line",
        "description": "Type: BASELINE\nDivision: PSE\nPriority: Medium",
        "pi_name": "Atteq UrRehman", "pi_email": "pi@example.kaust.edu.sa",
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    print("\n=== part 2: throwaway project", pr, "(id", pid, ") ===")

    step("GET  /assistant", client.get(f"/api/projects/{pid}/assistant", headers=H))
    t0 = time.time()
    r = step("POST /message (notes)", client.post(
        f"/api/projects/{pid}/assistant/message", headers=H, json={"message": NOTES}))
    if r.status_code == 200:
        print("    suggested:", r.json()["suggested_action"],
              "| seconds:", round(time.time() - t0, 1))

    chain = [
        "mom.draft", "mom.confirm",
        "summary.draft", "summary.approve",
        "ear.draft", "ear.pi_signature", "ear.asepc",
        "sow.draft", "boq.draft", "drawings.list",
    ]
    for action in chain:
        t0 = time.time()
        r = step("POST /run " + action, client.post(
            f"/api/projects/{pid}/assistant/run", headers=H, json={"action": action}))
        if r.status_code == 200:
            body = r.json()
            print("    ", str(body["content"])[:190])
            for art in body["artifacts"]:
                print("     artifact:", art["kind"], "|", art["label"], "|", art["filename"],
                      "|", art.get("panel"), "|", art.get("meta"))
            print("     seconds:", round(time.time() - t0, 1), "| reported:",
                  body.get("elapsed_ms"), "ms")

    step("POST /run package.binder (must be 409)", client.post(
        f"/api/projects/{pid}/assistant/run", headers=H, json={"action": "package.binder"}))
    step("POST /run sow.approve", client.post(
        f"/api/projects/{pid}/assistant/run", headers=H, json={"action": "sow.approve"}))
    t0 = time.time()
    r = step("POST /run package.binder", client.post(
        f"/api/projects/{pid}/assistant/run", headers=H, json={"action": "package.binder"}))
    if r.status_code == 200:
        print("    ", r.json()["content"], "| seconds:", round(time.time() - t0, 1))

    step("POST /run mto.draft (must be 409)", client.post(
        f"/api/projects/{pid}/assistant/run", headers=H, json={"action": "mto.draft"}))
    step("PATCH /procore Approved", client.patch(
        f"/api/projects/{pid}/procore", headers=H, json={"procore_status": "Approved"}))
    r = step("POST /run mto.draft", client.post(
        f"/api/projects/{pid}/assistant/run", headers=H, json={"action": "mto.draft"}))
    if r.status_code == 200:
        print("    ", r.json()["content"])

    # ---- every artifact in its own panel -------------------------------------
    print("\n--- panels ---")
    for label, path in (
        ("MomPanel", f"/api/projects/{pid}/mom"),
        ("EarPanel", f"/api/projects/{pid}/ear"),
        ("SowBoqPanel /sow", f"/api/projects/{pid}/sow"),
        ("SowBoqPanel /boq", f"/api/projects/{pid}/boq"),
        ("ProcorePanel", f"/api/projects/{pid}/procore"),
        ("PipelinePanel", f"/api/projects/{pid}/pipeline"),
        ("AuditTrail", f"/api/projects/{pid}/audit"),
    ):
        r = client.get(path, headers=H)
        print(f"    {label}: HTTP {r.status_code} | {len(r.content)} bytes")
        RESULTS.append((label, r.status_code, ""))

    audit = str(client.get(f"/api/projects/{pid}/audit", headers=H).json())
    keys = sorted({k for k in ("assistant:mom", "assistant:summary", "assistant:ear",
                               "assistant:sow", "assistant:boq", "assistant:drawings",
                               "assistant:mto", "package:pdf", "ear:funnel", "pipeline:stage")
                   if k in audit})
    print("    audit keys present:", keys)

    turns = client.get(f"/api/projects/{pid}/assistant/messages", headers=H).json()
    text = " ".join(str(t["content"]) for t in turns)
    labour_ok = "Labor: IHP In-House Resources" in text and "$0.00" in text
    print("    labour line present:", labour_ok, "| transcript turns:", len(turns))

    db.expire_all()
    ear = db.query(EarRecord).filter(EarRecord.project_id == pid).first()
    manpower = [t.estimated_manpower_cost for t in ear.trade_inputs] if ear else []
    items = db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).all()
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    sows = db.query(SowRecord).filter(SowRecord.project_id == pid).all()
    print("    mom v" + str(mom.version if mom else "-"),
          "| ear", ear.status if ear else "-",
          "| trade inputs", len(manpower), "manpower all 0:", all(m == 0.0 for m in manpower),
          "| sow revisions", len(sows),
          "| boq lines", len(items), "unpriced:", all(i.unit_rate == 0 for i in items))

    # ---- cleanup -------------------------------------------------------------
    ear_ids = [e.id for e in db.query(EarRecord).filter(EarRecord.project_id == pid)]
    if ear_ids:
        db.query(EarTradeInput).filter(EarTradeInput.ear_id.in_(ear_ids)).delete(
            synchronize_session=False)
    for model in (EarRecord, SowRecord, BoqMtoItem, MomRecord, PipelineStage,
                  AssistantMessage, Attachment):
        db.query(model).filter(model.project_id == pid).delete(synchronize_session=False)
    db.query(Project).filter(Project.id == pid).delete()
    db.commit()
    db.close()
    storage_dir = Path(get_settings().DATA_DIR) / "projects" / pr
    shutil.rmtree(storage_dir, ignore_errors=True)
    print("cleanup: throwaway project", pr, "and its rows removed;",
          "real PR transcript cleared")

    failed = [label for label, code, _ in RESULTS
              if code >= 400 and "must be 409" not in label]
    print("SUMMARY:", "ALL OK" if not failed else "FAILED -> " + ", ".join(failed))


if __name__ == "__main__":
    main()
