"""The HTML minute the team actually reads.

Three faults reported from a live minute:
  * every trade appeared twice in the agenda (as the heading and again as an
    empty bullet) because the scope text is built for the WORD cell, where the
    trade has to be the first line of the same cell;
  * the action items read "Plumbing: Plumbing: ..." for the same reason;
  * attendee addresses showed as "[email protected]" in the browser because
    Cloudflare's Scrape Shield rewrites plain addresses in any HTML it proxies.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import mom_html
from app.services.mom_html import (
    _drop_repeated_trade,
    defuse_emails,
    organizer_from_invitation,
)

INVITATION = (
    "From: Adrian Ichim <adrian.ichim@kaust.edu.sa>\n"
    "Sent: Sunday, September 14, 2026 10:30 AM\n"
    "To: In-House Projects Design\n"
    "Subject: PR-12592 N2 upgrade investigation\n"
    "Location: B7 L2 A3 (beside LFO 68)"
)

#: What the endpoint hands the renderer: the scope already carries the trade
#: as its first line, exactly like the Word cell.
DETAILS = {
    "meeting_number": "01",
    "meeting_date": "2026-09-14",
    "meeting_time": "10:30 AM - 11:00 AM",
    "meeting_title": "PR-12592 N2 upgrade investigation",
    "invitation": INVITATION,
    "attendees": [
        {
            "name": "Adrian Ichim",
            "title": "Laboratory Supervisor, Clean Energy Research Platform",
            "email": "adrian.ichim@kaust.edu.sa",
        }
    ],
    "agenda": [
        {
            "trade": "Civil/Architectural",
            "scope": (
                "Civil/Architectural:\n"
                "\u00d8 Works under this section include but not limited to "
                "modification of the existing gypsum board wall."
            ),
            "action": "IHP",
            "etc": "",
        },
        {
            "trade": "Plumbing",
            "scope": (
                "Plumbing:\n"
                "\u00d8 Feasibility study to convert the Sixteen (16) existing "
                "compressed air storage cylinders."
            ),
            "action": "IHP",
            "etc": "TBD",
        },
    ],
}


def _project():
    return SimpleNamespace(
        pr_number="PR-12592",
        title="N2 upgrade investigation",
        location="B7 L2 A3",
        pi_name="Adrian Ichim",
    )


def _render(for_email: bool = False, **overrides):
    details = {**DETAILS, **overrides}
    return mom_html.render_html(
        mom_html.build_html_context(
            project=_project(),
            details=details,
            derived={},
            version=1,
            for_email=for_email,
        )
    )


class TestAgendaDuplication:
    def test_a_scope_line_that_only_repeats_the_trade_is_dropped(self):
        assert _drop_repeated_trade(["Plumbing:", "Feasibility study"], "Plumbing") == [
            "Feasibility study"
        ]

    def test_a_real_first_line_is_kept(self):
        assert _drop_repeated_trade(["Feasibility study"], "Plumbing") == [
            "Feasibility study"
        ]

    def test_the_trade_is_not_repeated_as_a_bullet_in_the_minute(self):
        html = _render()
        # The heading stays...
        assert '<span class="trade">Plumbing</span>' in html
        assert '<span class="trade">Civil/Architectural</span>' in html
        # ...and the duplicated, empty-looking bullet is gone.
        assert "<li>Plumbing:</li>" not in html
        assert "<li>Civil/Architectural:</li>" not in html
        # The actual work survives.
        assert "Feasibility study to convert" in html

    def test_the_action_item_does_not_name_the_trade_twice(self):
        html = _render()
        assert "Plumbing: Plumbing:" not in html
        assert "Civil/Architectural: Civil/Architectural:" not in html
        # Named once, so the reader still knows which trade owns the action.
        assert "Plumbing: Feasibility study to convert" in html


class TestOrganizerFromInvitation:
    def test_the_sender_names_the_organizer(self):
        assert organizer_from_invitation(INVITATION) == "Adrian Ichim"

    def test_an_explicit_organizer_line_wins_over_the_sender(self):
        text = (
            "From: Someone Else <else@kaust.edu.sa>\n"
            "Organizer: In-House Projects Design\n"
        )
        assert organizer_from_invitation(text) == "In-House Projects Design"

    def test_a_bare_address_is_used_when_no_name_is_given(self):
        assert organizer_from_invitation("From: <ihp@kaust.edu.sa>") == (
            "ihp@kaust.edu.sa"
        )

    def test_nothing_to_read_gives_none(self):
        assert organizer_from_invitation(None) is None
        assert organizer_from_invitation("Subject: nothing useful") is None

    def test_the_minute_fills_the_organizer_row(self):
        html = _render()
        assert "Adrian Ichim" in html
        # The row must not read N/A while the invitation says who called it.
        assert "<dt>Organizer</dt><dd>Adrian Ichim</dd>" in html

    def test_the_outlook_participant_list_names_the_organizer(self):
        """What a copied invitation actually looks like: no headers, just the
        participants with their role in brackets."""
        text = (
            "Chris Asis (Meeting Organizer)\n"
            "Adrian Ichim (Accepted Meeting)\n"
            "In-House Projects Design"
        )
        assert organizer_from_invitation(text) == "Chris Asis"

    def test_the_pi_is_the_last_resort(self):
        """Showing the requester beats the N/A this row used to print."""
        html = _render(invitation="Subject: nothing that names an organizer")
        assert "<dt>Organizer</dt><dd>Adrian Ichim</dd>" in html

    def test_a_typed_organizer_overrides_the_invitation(self):
        html = _render(organizer="Mohammed Shariar Mamun")
        assert "<dt>Organizer</dt><dd>Mohammed Shariar Mamun</dd>" in html


class TestEmailObfuscation:
    def test_the_browser_view_splits_the_address(self):
        html = _render()
        assert "adrian.ichim@kaust.edu.sa" not in html, (
            "a contiguous address is exactly what Cloudflare rewrites"
        )
        assert "adrian.ichim<span>&#64;</span>kaust.edu.sa" in html

    def test_the_email_body_keeps_the_plain_address(self):
        html = _render(for_email=True)
        assert "adrian.ichim@kaust.edu.sa" in html

    def test_helper_leaves_plain_text_alone(self):
        assert defuse_emails("no address here", for_email=False) == "no address here"
        assert defuse_emails(None, for_email=False) == ""
        assert str(defuse_emails("a@b.co", for_email=False)) == (
            "a<span>&#64;</span>b.co"
        )

    def test_addresses_inside_the_invitation_are_split_too(self):
        html = _render()
        assert "adrian.ichim@kaust.edu.sa" not in html
        assert "adrian.ichim<span>&#64;</span>kaust.edu.sa" in html

class TestEmailDirectory:
    """Addresses are suggested, not retyped."""

    def test_it_remembers_attendees_and_offers_the_pi(
        self, client, admin_headers,
    ):
        resp = client.post(
            "/api/projects",
            headers=admin_headers,
            json={
                "pr_number": "PR-71501",
                "title": "Directory test",
                "pi_name": "Nikolay Gorshkov",
                "pi_email": "nikolay.gorshkov@kaust.edu.sa",
            },
        )
        assert resp.status_code in (200, 201), resp.text
        pid = resp.json()["id"]

        resp = client.post(
            f"/api/projects/{pid}/mom/generate",
            headers=admin_headers,
            json={
                "attendees": [
                    {
                        "name": "Adrian Ichim",
                        "title": "Laboratory Supervisor",
                        "email": "adrian.ichim@kaust.edu.sa",
                    },
                    # Same person, different case: one suggestion, not two.
                    {
                        "name": "adrian ichim",
                        "title": "duplicate",
                        "email": "ADRIAN.ICHIM@kaust.edu.sa",
                    },
                ]
            },
        )
        assert resp.status_code == 200, resp.text

        resp = client.get(
            f"/api/projects/{pid}/mom/email-directory", headers=admin_headers
        )
        assert resp.status_code == 200, resp.text
        entries = resp.json()["entries"]
        by_address = {e["email"].lower(): e for e in entries}
        assert "adrian.ichim@kaust.edu.sa" in by_address, (
            "an attendee of this project's own meeting must be suggested"
        )
        assert by_address["adrian.ichim@kaust.edu.sa"]["name"] == "Adrian Ichim"
        assert "nikolay.gorshkov@kaust.edu.sa" in by_address, (
            "the PI is a candidate without having attended anything"
        )
        assert (
            len([e for e in entries if e["email"].lower() == "adrian.ichim@kaust.edu.sa"])
            == 1
        )

