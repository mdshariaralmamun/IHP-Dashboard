"""Emailing a snapshot of the live tracker (draft-only .eml).

The platform has no mailbox: these endpoints must always hand back a draft
the user's own mail client opens, never send anything from the server, and
never let a malformed or oversized upload through.
"""

from __future__ import annotations

from email import message_from_bytes

import pytest

#: Structurally enough for the endpoint (it validates the declared type and
#: the size, not the pixels), and keeps the test independent of any codec.
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 512


#: One PR number per test — create rejects a duplicate PR.
_PR_SEQ = iter(range(8801, 8900))


@pytest.fixture()
def tracked_project(client, admin_headers):
    resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "pr_number": f"PR-{next(_PR_SEQ)}",
            "title": "Tracker share test project",
            "pi_name": "Niketan Patel",
            "pi_email": "niketan@example.com",
            "location": "B2",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    project = resp.json()
    assert project["tracking_token"], "every project gets a share token"
    return project


def filename_in(part) -> bool:
    """True when the part advertises a filename (so it is a real attachment)."""
    return "filename=" in str(part.get("Content-Disposition", ""))


def _draft(client, url, headers=None, **data):
    payload = {"to": "someone@example.com", **data}
    return client.post(
        url,
        files={"image": ("tracker.png", PNG, "image/png")},
        data=payload,
        headers=headers or {},
    )


class TestTrackingEmailDraft:
    def test_authenticated_draft_is_an_outlook_draft_with_the_image(
        self, client, admin_headers, tracked_project,
    ):
        resp = _draft(
            client,
            f"/api/projects/{tracked_project['id']}/tracking-email",
            headers=admin_headers,
            stage_label="Design",
            base_url="https://ihp.shariar.dev",
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("message/rfc822")
        assert ".eml" in resp.headers["content-disposition"]

        message = message_from_bytes(resp.content)
        # X-Unsent is what makes Outlook open this as an editable draft, and a
        # missing From is what makes it use the user's own account.
        assert message["X-Unsent"] == "1"
        assert message["From"] is None
        assert "PR-8801" in message["Subject"]
        assert "someone@example.com" in message["To"]

        html_parts = [
            part for part in message.walk()
            if part.get_content_type() == "text/html"
        ]
        assert html_parts, "the draft carries an html body"
        body = html_parts[0].get_payload(decode=True).decode()
        assert "Design" in body
        assert "https://ihp.shariar.dev/track/" in body

        # The picture travels inline (so the body can render it) AND as a
        # normal attachment the recipient can save.
        images = [
            part for part in message.walk()
            if part.get_content_type() == "image/png"
        ]
        assert len(images) == 2, f"expected inline + attached, got {len(images)}"
        inline = [p for p in images if p.get("Content-ID")]
        assert len(inline) == 1, "one copy is inline (Content-ID)"
        assert inline[0].get_payload(decode=True) == PNG
        saved = [p for p in images if not p.get("Content-ID")]
        assert saved[0].get_payload(decode=True) == PNG
        assert filename_in(saved[0])

    def test_recipient_defaults_to_the_pi(
        self, client, admin_headers, tracked_project,
    ):
        resp = client.post(
            f"/api/projects/{tracked_project['id']}/tracking-email",
            files={"image": ("tracker.png", PNG, "image/png")},
            data={"to": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        assert "niketan@example.com" in message_from_bytes(resp.content)["To"]

    def test_public_draft_uses_the_share_token(
        self, client, tracked_project,
    ):
        """The person holding the share link can draft the mail; the server
        still sends nothing."""
        resp = _draft(
            client,
            f"/api/projects/track/{tracked_project['tracking_token']}/tracking-email",
        )
        assert resp.status_code == 200, resp.text
        assert message_from_bytes(resp.content)["X-Unsent"] == "1"

    def test_unknown_token_is_404(self, client):
        resp = _draft(client, "/api/projects/track/nope/tracking-email")
        assert resp.status_code == 404

    def test_missing_recipient_is_rejected(
        self, client, tracked_project,
    ):
        resp = client.post(
            f"/api/projects/track/{tracked_project['tracking_token']}/tracking-email",
            files={"image": ("tracker.png", PNG, "image/png")},
            data={"to": ""},
        )
        assert resp.status_code == 400
        assert "recipient" in resp.text.lower()

    def test_non_image_upload_is_rejected(
        self, client, tracked_project,
    ):
        resp = client.post(
            f"/api/projects/track/{tracked_project['tracking_token']}/tracking-email",
            files={"image": ("tracker.txt", b"not an image", "text/plain")},
            data={"to": "someone@example.com"},
        )
        assert resp.status_code == 400

    def test_oversized_snapshot_is_rejected(
        self, client, tracked_project,
    ):
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (9 * 1024 * 1024)
        resp = client.post(
            f"/api/projects/track/{tracked_project['tracking_token']}/tracking-email",
            files={"image": ("tracker.png", big, "image/png")},
            data={"to": "someone@example.com"},
        )
        assert resp.status_code == 413
