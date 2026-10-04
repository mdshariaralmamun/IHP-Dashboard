"""The next step, the to-do list and cancellation.

One place per PR: which stage comes next, in which follow-up bucket, who owns
it and when it is due - plus the tasks that get it there and the record kept
when a PR is cancelled instead.
"""

import uuid


def _pr(prefix="PR") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _project(client, headers, title="Fume hood relocation") -> dict:
    resp = client.post(
        "/api/projects",
        json={
            "pr_number": _pr(),
            "title": title,
            "description": "Move the hood to the new lab",
            "pi_name": "Dr. Example",
            "pi_email": "pi@example.kaust.edu.sa",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_next_step_roundtrip_and_validation(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]

    empty = client.get(f"/api/projects/{pid}/next-step", headers=admin_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["next_stage"] is None
    assert empty.json()["todos"] == []

    saved = client.put(
        f"/api/projects/{pid}/next-step",
        json={
            "next_stage": "SOW_DRAFT",
            "next_stage_bucket": "design",  # canonicalised to the bucket list
            "next_stage_date": "2026-11-05",
            "next_stage_owner": "planner.one",
            "next_step_note": "Write the SOW after the site visit",
        },
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["next_stage"] == "SOW_DRAFT"
    assert body["next_stage_bucket"] == "DESIGN"
    assert body["next_stage_date"] == "2026-11-05"
    assert body["next_stage_owner"] == "planner.one"

    # The plan is on the project detail (and therefore on the register rows).
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["next_stage"] == "SOW_DRAFT"
    assert detail["next_stage_bucket"] == "DESIGN"

    bad_bucket = client.put(
        f"/api/projects/{pid}/next-step",
        json={"next_stage_bucket": "Marketing"},
        headers=admin_headers,
    )
    assert bad_bucket.status_code == 422

    bad_stage = client.put(
        f"/api/projects/{pid}/next-step",
        json={"next_stage": "TELEPORT"},
        headers=admin_headers,
    )
    assert bad_stage.status_code == 422

    # PATCH-style: a second save must not wipe the fields it does not send.
    again = client.put(
        f"/api/projects/{pid}/next-step",
        json={"next_stage_owner": "planner.two"},
        headers=admin_headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["next_stage_owner"] == "planner.two"
    assert again.json()["next_stage"] == "SOW_DRAFT"


def test_move_now_walks_the_workflow_and_clears_the_plan(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]

    moved = client.put(
        f"/api/projects/{pid}/next-step",
        json={
            "next_stage": "MOM_SENT",
            "next_stage_bucket": "EAR",
            "next_stage_owner": "planner.one",
            "move_now": True,
            "justification": "MOM issued to the PI after the kick-off",
        },
        headers=admin_headers,
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["stage"] == "MOM_SENT"
    assert body["next_stage"] is None  # the planned move was carried out
    assert body["next_stage_owner"] == "planner.one"

    illegal = client.put(
        f"/api/projects/{pid}/next-step",
        json={"next_stage": "CLOSEOUT", "move_now": True},
        headers=admin_headers,
    )
    assert illegal.status_code == 409


def test_todo_crud_and_the_full_picture_list(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]
    first = _project(client, admin_headers, title="Second PR")

    created = client.post(
        f"/api/projects/{pid}/todos",
        json={
            "title": "Book the shutdown window",
            "bucket": "shutdown",
            "assignee_username": "ops.one",
            "due_date": "2026-11-01",
            "note": "Coordinate with the lab manager",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    todo = created.json()
    assert todo["bucket"] == "SHUTDOWN"
    assert todo["status"] == "open"

    second = client.post(
        f"/api/projects/{first['id']}/todos",
        json={"title": "Chase the PI for the drawings", "assignee_username": "me.one"},
        headers=admin_headers,
    )
    assert second.status_code == 201, second.text

    listed = client.get("/api/todos?status=open", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["counts"]["open"] == 2
    assert "SHUTDOWN" in body["counts"]["by_bucket"]
    assert body["counts"]["by_assignee"]["ops.one"] == 1
    mine_map = {r["id"]: r for r in body["rows"]}
    assert mine_map[todo["id"]]["pr_number"] == project["pr_number"]
    assert mine_map[todo["id"]]["project_title"] == project["title"]

    by_bucket = client.get("/api/todos?bucket=SHUTDOWN&status=open", headers=admin_headers)
    assert by_bucket.status_code == 200, by_bucket.text
    assert len(by_bucket.json()["rows"]) == 1

    # Tick it off: completed_at is stamped by the server.
    done = client.patch(
        f"/api/todos/{todo['id']}",
        json={"status": "done"},
        headers=admin_headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["completed_at"] is not None

    open_now = client.get("/api/todos?status=open", headers=admin_headers).json()
    assert open_now["counts"]["open"] == 1

    removed = client.delete(f"/api/todos/{todo['id']}", headers=admin_headers)
    assert removed.status_code == 204

    buckets = client.get("/api/todos/buckets", headers=admin_headers)
    assert buckets.status_code == 200
    assert "PTW/WICF" in buckets.json()["buckets"]
    assert "ICR" in buckets.json()["buckets"]


def test_cancel_keeps_the_reason_and_the_email(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]

    cancelled = client.post(
        f"/api/projects/{pid}/cancel",
        json={
            "reason": "Budget pulled",
            "justification": "ASEPC withdrew the funding for FY26; the PI will "
            "re-initiate under a new PR.",
            "send_email": True,
        },
        headers=admin_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["stage"] == "CANCELLED"
    assert body["cancel_reason"] == "Budget pulled"
    assert "re-initiate" in body["cancel_justification"]
    # No SMTP in tests: the draft comes back so it can still be sent by hand.
    assert body["emailed"] is False
    assert body["email_to"] == "pi@example.kaust.edu.sa"
    assert "cancelled" in body["email_subject"].lower()
    assert "Budget pulled" in body["email_body"]

    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["stage"] == "CANCELLED"
    assert detail["cancel_reason"] == "Budget pulled"
    assert detail["cancel_notified_at"] is None  # nothing was actually sent

    # Cancelling twice is refused, and the workflow makes it terminal.
    again = client.post(
        f"/api/projects/{pid}/cancel",
        json={"reason": "Again", "justification": "Trying to cancel twice over."},
        headers=admin_headers,
    )
    assert again.status_code == 409


def test_cancel_requires_a_real_justification(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]

    short = client.post(
        f"/api/projects/{pid}/cancel",
        json={"reason": "x", "justification": "too short"},
        headers=admin_headers,
    )
    assert short.status_code == 422
    still = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert still["stage"] == "INTAKE"
