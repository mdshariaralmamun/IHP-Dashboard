"""PR form parser unit tests + /api/intake/parse-pr-form endpoint tests."""

import io

from app.services import pr_form_parser

# Real PR-12623 export text (pipe-separated copy from the request system).
PR_12623 = """\
King Abdullah University of Science and Technology
Campus and Community Project Request System - Request Details
PR-12623 | Initial Submission

Reference Number | PR-12623
Status | Awaiting IHP Review

Requester Name | Abdulrahman El Labban
Requester Email | abdulrahman.ellabban@kaust.edu.sa
Requester Division | Solar Platform
Work Phone/Cell | 0563181865

End User / Funding Approver Name | Abdulrahman El Labban
End User / Funding Approver Division | Solar Platform
End User / Funding Approver Email | abdulrahman.ellabban@kaust.edu.sa
End User / Funding Approver Work Phone/Cell | 0563181865
End User / Funding Approver Executive | HUSAM NIMAN ALSHAREEF

Project Request Title | T1 thermal evaporator replacement
Location | Bldg 5 - Al-Kindi Laboratory
Location Details | Blg 5 level 3 area 1 FLOC-5-3600
Source of Funding | ASEPC
Has the Project Coordinated with Facilities Management | No

Project Request Description | Here attached are the quotation and the technical specification and utility matrix. thanks
NOTE: Please Discard my previous request (12622) and only consider this one. thanks

Attachments | 23045B - Angstrom Quote.pdf, 23073-Angstrom Engineering - General Equipment Utilities Matrix v2.xlsx, 23073-Angstrom Engineering - KAUST Technical Specification Checklist.docx
"""


def test_parse_pipe_format():
    fields = pr_form_parser.parse_pr_form_fields(PR_12623)
    assert fields["pr_number"] == "PR-12623"
    assert fields["title"] == "T1 thermal evaporator replacement"
    assert fields["requester_name"] == "Abdulrahman El Labban"
    assert fields["requester_email"] == "abdulrahman.ellabban@kaust.edu.sa"
    assert fields["requester_division"] == "Solar Platform"
    assert fields["requester_phone"] == "0563181865"
    assert fields["approver_name"] == "Abdulrahman El Labban"
    assert fields["approver_executive"] == "HUSAM NIMAN ALSHAREEF"
    assert fields["location"] == "Bldg 5 - Al-Kindi Laboratory"
    assert fields["location_details"] == "Blg 5 level 3 area 1 FLOC-5-3600"
    assert fields["funding_source"] == "ASEPC"
    assert fields["fm_coordinated"] == "No"
    assert "Discard my previous request" in fields["description"]
    assert fields["attachments"] == [
        "23045B - Angstrom Quote.pdf",
        "23073-Angstrom Engineering - General Equipment Utilities Matrix v2.xlsx",
        "23073-Angstrom Engineering - KAUST Technical Specification Checklist.docx",
    ]


def test_to_intake_mapping():
    project = pr_form_parser.to_intake(pr_form_parser.parse_pr_form_fields(PR_12623))
    assert project["pr_number"] == "PR-12623"
    assert project["title"] == "T1 thermal evaporator replacement"
    assert project["pi_name"] == "Abdulrahman El Labban"
    assert project["pi_email"] == "abdulrahman.ellabban@kaust.edu.sa"
    assert project["funding_source"] == "ASEPC"
    assert (
        project["location"] == "Bldg 5 - Al-Kindi Laboratory, Blg 5 level 3 area 1 FLOC-5-3600"
    )
    assert "Coordinated with Facilities Management: No" in project["description"]
    assert "HUSAM NIMAN ALSHAREEF" in project["description"]
    assert "Angstrom Quote.pdf" in project["description"]


def test_parse_label_on_separate_line():
    text = "Reference Number\nPR-99999\nStatus\nDraft\nProject Request Title\nChiller swap\n"
    fields = pr_form_parser.parse_pr_form_fields(text)
    assert fields["pr_number"] == "PR-99999"
    assert fields["title"] == "Chiller swap"


def test_endpoint_txt(client, admin_headers):
    resp = client.post(
        "/api/intake/parse-pr-form",
        files={"file": ("pr12623.txt", PR_12623.encode(), "text/plain")},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project"]["pr_number"] == "PR-12623"
    assert body["fields"]["attachments"][0].endswith("Angstrom Quote.pdf")


def test_endpoint_docx(client, admin_headers):
    import docx

    document = docx.Document()
    for line in PR_12623.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    resp = client.post(
        "/api/intake/parse-pr-form",
        files={
            "file": (
                "pr.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project"]["pr_number"] == "PR-12623"


def test_endpoint_rejects_non_pr_file(client, admin_headers):
    resp = client.post(
        "/api/intake/parse-pr-form",
        files={"file": ("notes.txt", b"random meeting notes", "text/plain")},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_endpoint_rejects_bad_extension(client, admin_headers):
    resp = client.post(
        "/api/intake/parse-pr-form",
        files={"file": ("pr.xlsx", b"whatever", "application/octet-stream")},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_endpoint_requires_admin(client, role_headers):
    resp = client.post(
        "/api/intake/parse-pr-form",
        files={"file": ("pr.txt", PR_12623.encode(), "text/plain")},
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 403


# ---------- Outlook .msg support ----------

SITE_VISIT_SUBJECT = "PR 12643 Cilled water line connection site visit"


def test_normalize_pr_number():
    assert pr_form_parser.normalize_pr_number(SITE_VISIT_SUBJECT) == "PR-12643"
    assert pr_form_parser.normalize_pr_number("PR-12623") == "PR-12623"
    assert pr_form_parser.normalize_pr_number("fw: pr12601 chiller") == "PR-12601"
    assert pr_form_parser.normalize_pr_number("no number here") is None


def test_title_from_subject():
    assert (
        pr_form_parser.title_from_subject(SITE_VISIT_SUBJECT)
        == "Cilled water line connection site visit"
    )
    assert (
        pr_form_parser.title_from_subject("RE: PR-12623 - T1 thermal evaporator replacement")
        == "T1 thermal evaporator replacement"
    )
    assert pr_form_parser.title_from_subject("PR 12643") is None


def test_endpoint_rejects_invalid_msg(client, admin_headers):
    resp = client.post(
        "/api/intake/parse-pr-form",
        files={"file": ("broken.msg", b"definitely not an OLE msg file", "application/octet-stream")},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_attachments_noise_and_commas():
    text = (
        "Reference Number | PR-1\n"
        "Attachments | one file.pdf, Report, final v2.pdf, "
        "No attachment available., Request created by Jane on Sep 01, 2026 04:57 PM, "
        "Page 2 of 2Generated on Sep 02, 2026 04:00 PM\n"
    )
    fields = pr_form_parser.parse_pr_form_fields(text)
    assert fields["attachments"] == ["one file.pdf", "Report, final v2.pdf"]
