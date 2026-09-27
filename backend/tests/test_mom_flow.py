"""Full MOM happy path: PR -> attachments -> generate -> sent -> disputed
-> re-sent -> acknowledged, with audit ordering and versioning checks."""

import uuid

EN_DASH = "\u2013"


def _flow_project(client, headers):
    pr = f"PR-FLOW-{uuid.uuid4().hex[:6].upper()}"
    resp = client.post(
        "/api/projects",
        json={
            "pr_number": pr,
            "title": "Lab renovation",
            "description": "Replace fume hood and benches",
            "location": "Building 2, Room 210",
            "pi_name": "Dr. Flow",
            "pi_email": "flow@example.kaust.edu.sa",
            "funding_source": "Department budget",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_mom_happy_path(client, admin_headers, data_dir):
    project = _flow_project(client, admin_headers)
    pid = project["id"]
    pr = project["pr_number"]

    # Upload two attachments.
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files=[
            ("files", ("scope.txt", b"scope", "text/plain")),
            ("files", ("photos.txt", b"photos", "text/plain")),
        ],
        headers=admin_headers,
    )
    assert resp.status_code == 200
    attachments = resp.json()

    # Generate the MOM.
    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    mom = resp.json()
    assert mom["status"] == "draft"
    assert mom["version"] == 1
    assert mom["email_subject"] == (
        f"PR {pr} {EN_DASH} Lab renovation {EN_DASH} Request confirmation"
    )
    assert "scope.txt" in mom["email_body"]
    assert "photos.txt" in mom["email_body"]
    assert "flow@example.kaust.edu.sa" in mom["email_body"]

    # Generated docx exists on disk; PDF optional (needs LibreOffice).
    mom_dir = data_dir / "projects" / pr / "mom"
    docx_path = mom_dir / mom["docx_filename"]
    assert docx_path.exists()
    assert docx_path.read_bytes()[:2] == b"PK"  # real docx (zip) file
    if mom["pdf_filename"]:
        assert (mom_dir / mom["pdf_filename"]).exists()

    # Download endpoints.
    resp = client.get(
        f"/api/projects/{pid}/mom/download", params={"fmt": "docx"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
    resp = client.get(
        f"/api/projects/{pid}/mom/download", params={"fmt": "pdf"},
        headers=admin_headers,
    )
    if mom["pdf_filename"]:
        assert resp.status_code == 200
    else:
        assert resp.status_code == 404  # PDF not generated (no soffice)

    # Project detail exposes the MOM.
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["mom"]["status"] == "draft"

    # Mark sent -> stage MOM_SENT.
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "sent"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "sent"
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["stage"] == "MOM_SENT"

    # Dispute without note -> 422, nothing changes.
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "disputed"},
        headers=admin_headers,
    )
    assert resp.status_code == 422
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["mom"]["status"] == "sent"

    # Dispute with note -> status disputed, stage stays MOM_SENT, note stored.
    resp = client.post(
        f"/api/projects/{pid}/mom/status",
        json={"status": "disputed", "note": "BOQ mismatch"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "disputed"
    assert resp.json()["note"] == "BOQ mismatch"
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["stage"] == "MOM_SENT"

    # Mark sent again (allowed from disputed).
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "sent"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"

    # Acknowledge -> stage MOM_CONFIRMED.
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "acknowledged"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "acknowledged"
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["stage"] == "MOM_CONFIRMED"

    # Audit endpoint shows every action, chronologically.
    resp = client.get(f"/api/projects/{pid}/audit", headers=admin_headers)
    assert resp.status_code == 200
    trail = resp.json()
    assert [e["action"] for e in trail] == [
        "project:create",
        "attachment:upload",
        "attachment:upload",
        "mom:generate",
        "mom:sent",
        "mom:disputed",
        "mom:sent",
        "mom:acknowledged",
    ]
    assert all(e["user"] == "admin" for e in trail)
    disputed_entry = next(e for e in trail if e["action"] == "mom:disputed")
    assert disputed_entry["detail"]["note"] == "BOQ mismatch"
    sent_entry = next(e for e in trail if e["action"] == "mom:sent")
    assert sent_entry["detail"]["from"] == "INTAKE"
    assert sent_entry["detail"]["to"] == "MOM_SENT"
    ack_entry = next(e for e in trail if e["action"] == "mom:acknowledged")
    assert ack_entry["detail"]["to"] == "MOM_CONFIRMED"

    # Download an attachment by id, bytes match.
    att_id = attachments[0]["id"]
    resp = client.get(
        f"/api/projects/{pid}/attachments/{att_id}/download", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.content == b"scope"


def test_mom_regenerate_increments_version(client, admin_headers):
    project = _flow_project(client, admin_headers)
    pid = project["id"]

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    assert resp.json()["status"] == "draft"

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert resp.json()["docx_filename"].endswith("_v2.docx")

    # Still exactly one MOM record for the project.
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["mom"]["version"] == 2


def test_mom_can_be_regenerated_after_confirmation(client, admin_headers):
    """Re-issuing minutes is allowed at any stage; it only adds a revision.

    It used to be a 409 outside INTAKE/MOM_SENT, which blocked the screen for
    every Planner-imported project and made correcting a confirmed MOM
    impossible. The stage is not touched by generation.
    """
    project = _flow_project(client, admin_headers)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "sent"},
        headers=admin_headers,
    )
    client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "acknowledged"},
        headers=admin_headers,
    )

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2

    from app.db import SessionLocal
    from app.models import Project

    db = SessionLocal()
    try:
        assert db.get(Project, pid).stage == "MOM_CONFIRMED"
    finally:
        db.close()


def test_mom_status_transitions_enforced(client, admin_headers):
    project = _flow_project(client, admin_headers)
    pid = project["id"]

    # No MOM yet -> 404 on status/download.
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "sent"},
        headers=admin_headers,
    )
    assert resp.status_code == 404
    resp = client.get(
        f"/api/projects/{pid}/mom/download", params={"fmt": "docx"},
        headers=admin_headers,
    )
    assert resp.status_code == 404

    # Acknowledge from draft -> 409.
    client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "acknowledged"},
        headers=admin_headers,
    )
    assert resp.status_code == 409

    # Invalid status value -> 422 (schema validation).
    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "bogus"},
        headers=admin_headers,
    )
    assert resp.status_code == 422

# ---------------------------------------------------------------------------
# MOM at a later stage
#
# Planner-imported projects arrive at EAR_REVIEW / CONSTRUCTION, but the team
# still has to produce (or correct) their minutes. Generation used to be
# rejected with 409 outside INTAKE/MOM_SENT, which made the whole MOM screen
# dead for those projects.
# ---------------------------------------------------------------------------


def _project_at_stage(client, headers, stage: str):
    """Create a project and force its stage, with a valid transition path."""
    project = _flow_project(client, headers)
    pid = project["id"]
    from app.db import SessionLocal
    from app.models import Project

    db = SessionLocal()
    try:
        row = db.get(Project, pid)
        row.stage = stage
        db.commit()
    finally:
        db.close()
    return pid


def test_mom_generates_at_a_later_stage(client, admin_headers, data_dir):
    pid = _project_at_stage(client, admin_headers, "EAR_REVIEW")

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    mom = resp.json()
    assert mom["status"] == "draft"
    assert mom["version"] == 1
    assert mom["email_subject"]

    # Regenerating (fixing attendance, adding an agenda item) also works there.
    again = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert again.status_code == 200, again.text
    assert again.json()["version"] == 2


def test_mom_sent_and_acknowledged_never_move_a_later_stage_backwards(
    client, admin_headers
):
    pid = _project_at_stage(client, admin_headers, "EAR_REVIEW")
    assert client.post(
        f"/api/projects/{pid}/mom/generate", headers=admin_headers
    ).status_code == 200

    # Marking it sent on an EAR_REVIEW project must not undo the stage.
    sent = client.post(
        f"/api/projects/{pid}/mom/status",
        json={"status": "sent"},
        headers=admin_headers,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"

    ack = client.post(
        f"/api/projects/{pid}/mom/status",
        json={"status": "acknowledged"},
        headers=admin_headers,
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"

    from app.db import SessionLocal
    from app.models import Project

    db = SessionLocal()
    try:
        assert db.get(Project, pid).stage == "EAR_REVIEW"
    finally:
        db.close()


def test_first_mom_still_advances_an_intake_project(client, admin_headers):
    """The normal intake path keeps working: sent moves INTAKE -> MOM_SENT."""
    project = _flow_project(client, admin_headers)
    pid = project["id"]
    assert client.post(
        f"/api/projects/{pid}/mom/generate", headers=admin_headers
    ).status_code == 200
    sent = client.post(
        f"/api/projects/{pid}/mom/status",
        json={"status": "sent"},
        headers=admin_headers,
    )
    assert sent.status_code == 200, sent.text

    from app.db import SessionLocal
    from app.models import Project

    db = SessionLocal()
    try:
        assert db.get(Project, pid).stage == "MOM_SENT"
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Sending the MOM from the user's own Outlook
#
# The platform has no mailbox access, so the MOM is exported as an .eml that
# opens as a compose window in Outlook: recipients, subject, body and the
# attached minute. These tests pin the file structure.
# ---------------------------------------------------------------------------


def _mom_with_participants(client, headers):
    project = _flow_project(client, headers)
    pid = project["id"]
    details = {
        "meeting_title": "PR 12693 Nanofabricator Lite Site Visit",
        "meeting_number": "01",
        "meeting_date": "2026-09-09",
        "meeting_time": "10:30 AM",
        "meeting_location": "3-2635",
        "attendees": [
            {"name": "Chris Asis", "title": "Meeting Organizer", "email": "chris.asus@kaust.edu.sa"},
            {"name": "Nazek El Atab", "title": "Accepted Meeting", "email": "nazek.elatab@kaust.edu.sa"},
            {"name": "In-House Projects Design", "title": "", "email": "ihp.design@kaust.edu.sa"},
        ],
        "agenda": [
            {"trade": "Civil/Architectural", "scope": "Modify the gypsum board wall.", "action": "IHP", "etc": ""},
            {"trade": "General", "scope": "Toxic gas purging by the Proponent.", "action": "PI", "etc": "TBD"},
        ],
    }
    resp = client.post(
        f"/api/projects/{pid}/mom/generate", json=details, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return pid, project, details


def _parse_eml(raw: bytes):
    from email import policy
    from email.parser import BytesParser

    return BytesParser(policy=policy.default).parsebytes(raw)


def test_mom_email_draft_carries_recipients_and_attachments(client, admin_headers):
    pid, project, details = _mom_with_participants(client, admin_headers)

    resp = client.get(f"/api/projects/{pid}/mom/email.eml", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("message/rfc822")
    assert ".eml" in resp.headers["content-disposition"]

    message = _parse_eml(resp.content)
    # Recipients: every participant, in order, plus the PI.
    to = message["To"]
    assert "chris.asus@kaust.edu.sa" in to
    assert "nazek.elatab@kaust.edu.sa" in to
    assert "ihp.design@kaust.edu.sa" in to
    assert "flow@example.kaust.edu.sa" in to
    # Outlook opens it as an editable draft, and picks the sender account.
    assert message["X-Unsent"] == "1"
    assert message["From"] is None
    assert project["pr_number"] in message["Subject"]

    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Participants (3)" in body
    assert "Meeting details:" in body
    assert "Agenda - Preliminary Scope of Work" in body
    assert "Action by: IHP" in body
    assert "ETC: TBD" in body

    names = [part.get_filename() for part in message.iter_attachments()]
    assert any(name and name.endswith(".docx") for name in names), names


def test_mom_email_draft_accepts_explicit_recipients(client, admin_headers):
    pid, _project, _details = _mom_with_participants(client, admin_headers)

    resp = client.get(
        f"/api/projects/{pid}/mom/email.eml",
        params={"to": "planner@kaust.edu.sa, boss@kaust.edu.sa", "cc": "pm@kaust.edu.sa"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    message = _parse_eml(resp.content)
    assert message["To"] == "planner@kaust.edu.sa, boss@kaust.edu.sa"
    assert message["Cc"] == "pm@kaust.edu.sa"
    assert "chris.asus@kaust.edu.sa" not in message["To"]


def test_mom_email_draft_without_a_mom_is_404(client, admin_headers):
    project = _flow_project(client, admin_headers)
    resp = client.get(f"/api/projects/{project['id']}/mom/email.eml", headers=admin_headers)
    assert resp.status_code == 404


def test_mom_email_requires_auth(client, admin_headers):
    project = _flow_project(client, admin_headers)
    resp = client.get(f"/api/projects/{project['id']}/mom/email.eml")
    assert resp.status_code == 401

# ---------------------------------------------------------------------------
# House format: trade-headed agenda rows, the pasted invitation and the
# no-attachment Outlook link.
# ---------------------------------------------------------------------------


def test_agenda_rows_carry_the_trade_heading_and_bullets():
    from app.api.mom import _agenda_display_scope

    rendered = _agenda_display_scope(
        {"trade": "Plumbing", "scope": "Supply and install the CDA network.\nTest and commission."}
    )
    lines = rendered.splitlines()
    assert lines[0] == "Plumbing:"
    # A trade that already carries its qualifier keeps the house style.
    from app.api.mom import _agenda_display_scope as scope_of

    assert scope_of(
        {"trade": "Civil/Architectural (Equipment Layout)", "scope": "Wall works."}
    ).splitlines()[0] == "Civil/Architectural (Equipment Layout)"
    assert lines[1].startswith("\u00d8 Supply and install")
    assert lines[2].startswith("\u00d8 Test and commission")


def test_agenda_is_ordered_civil_plumbing_hvac_electrical_general():
    from app.api.mom import _sort_agenda_by_trade

    agenda = [
        {"trade": "General"},
        {"trade": "Electrical"},
        {"trade": "HVAC"},
        {"trade": "Plumbing"},
        {"trade": "Civil/Architectural"},
    ]
    assert [item["trade"] for item in _sort_agenda_by_trade(agenda)] == [
        "Civil/Architectural",
        "Plumbing",
        "HVAC",
        "Electrical",
        "General",
    ]


def test_invitation_is_rendered_in_the_minute_and_the_email(client, admin_headers, data_dir):
    project = _flow_project(client, admin_headers)
    pid = project["id"]
    invitation = (
        "PR 12693 Nanofabricator Lite Site Visit\n"
        "Wed, Sep 9, 10:30 AM - 11:00 AM\n"
        "3-2635\n"
        "Participants (5)"
    )
    resp = client.post(
        f"/api/projects/{pid}/mom/generate",
        json={"meeting_title": "Site Visit", "invitation": invitation},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    mom = resp.json()
    assert mom["details"]["invitation"] == invitation

    # The Word minute carries the invitation as its own section.
    import zipfile

    docx = data_dir / "projects" / project["pr_number"] / "mom" / mom["docx_filename"]
    with zipfile.ZipFile(docx) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", "replace")
    assert "Invitation:" in xml
    assert "Wed, Sep 9, 10:30 AM - 11:00 AM" in xml

    # ... and so does the email body.
    link = client.get(f"/api/projects/{pid}/mom/email-link", headers=admin_headers)
    assert link.status_code == 200, link.text
    payload = link.json()
    assert "Invitation:" in payload["body"]
    assert payload["mailto"].startswith("mailto:")
    assert "subject=" in payload["mailto"] and "body=" in payload["mailto"]
    assert payload["to"]


def test_email_link_and_eml_can_omit_the_attachments(client, admin_headers):
    pid, _project, _details = _mom_with_participants(client, admin_headers)

    plain = client.get(
        f"/api/projects/{pid}/mom/email.eml", params={"attach": "false"}, headers=admin_headers
    )
    assert plain.status_code == 200, plain.text
    message = _parse_eml(plain.content)
    assert list(message.iter_attachments()) == []
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Agenda - Preliminary Scope of Work" in body
    assert "Attachments:" not in body

    with_doc = client.get(
        f"/api/projects/{pid}/mom/email.eml", params={"attach": "true"}, headers=admin_headers
    )
    assert list(_parse_eml(with_doc.content).iter_attachments())

def test_qualified_trade_names_keep_their_house_rank():
    """\"Civil/Architectural (Equipment Layout)\" must stay first, not fall last."""
    from app.api.mom import _sort_agenda_by_trade

    agenda = [
        {"trade": "General"},
        {"trade": "Electrical:"},
        {"trade": "Civil/Architectural (Equipment Layout)"},
        {"trade": "Plumbing"},
        {"trade": "HVAC"},
    ]
    assert [item["trade"] for item in _sort_agenda_by_trade(agenda)] == [
        "Civil/Architectural (Equipment Layout)",
        "Plumbing",
        "HVAC",
        "Electrical:",
        "General",
    ]
