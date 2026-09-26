"""Seed PR-12630 (socket relocation) through the live API.

Data source: docs/SOW_BOQ_MTO_PROMPT.md §8 — the Planner's worked example.
Every value is Planner-provided; nothing is invented. Scope items carry
DOC source tags citing EAR / PR-12630 (§7 traceability).

Idempotent: reuses an existing PR-12630 project row and skips the SOW /
BOQ seeding when they already exist, so it is safe to re-run.

Usage:
    python -m scripts.seed_pr_12630 [base_url]     # default http://localhost:8001
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"

PR = "PR-12630"
TITLE = "Relocation of 3-phase sockets"
LOCATION = "Building 6, Level-1, Greenhouse"

_E = {"unit": "Lot", "qty": "1", "source_tag": "DOC", "source_doc": PR}

# §8.2 scope items + §8.5 MTO measurement lines, grouped per trade.
TRADE_SECTIONS = {
    "metadata": {  # §8.1
        "ear_number": "12547",
        "original_pr": "12547",
        "requester": "John Rahmer",
        "end_user": "Angelo Gallone",
        "funding": "OPEX",
        "wbs": "12380",
        "division": "Growth Chambers and Facilities",
        "estimated_cost": "USD 480 (excl. VAT)",
    },
    "drawings": [],  # none uploaded yet — QA check 6 reports TBC
    "trades": [
        {"name": "Civil / Architectural", "seen": True, "items": [
            {"description": "Gypsum wall mod, reworks, repairs, repainting, "
                            "fire-rated sealant", "source_doc": "EAR", **_E},
        ], "mto_items": [
            {"ref": "A.1", "description": "Gypsum board wall modification",
             "unit": "Lot", "qty": 1, "computation": "Lump sum"},
        ]},
        {"name": "Electrical", "seen": True, "items": [
            {"description": "Supply & install 1-inch EMT conduit + accessories", **_E},
            {"description": "Supply & install 1-inch flexible EMT conduit "
                            "+ accessories", **_E},
            {"description": "Relocate 3-phase socket UN3200-PR-HA-38,40,42 "
                            "from corridor to same room", **_E},
            {"description": "Testing & Commissioning + Tagging + Panel board "
                            "schedule", **_E},
        ], "mto_items": [
            {"ref": "B.1", "description": "1-inch EMT conduit", "unit": "Lm",
             "qty": "TBC", "computation": "(from drawing)"},
            {"ref": "B.2", "description": "1-inch flexible EMT conduit",
             "unit": "Lm", "qty": "TBC", "computation": "(from drawing)"},
            {"ref": "B.3", "description": "Relocation of 3-phase socket",
             "unit": "Nos", "qty": 3, "computation": "3 sockets"},
            {"ref": "B.4", "description": "Cable pulling", "unit": "Lm",
             "qty": "TBC", "computation": "(from drawing)"},
            {"ref": "B.5", "description": "Testing & Commissioning",
             "unit": "Lot", "qty": 1, "computation": "Lump sum"},
        ]},
        {"name": "Low Current", "seen": False, "items": [], "mto_items": []},
        {"name": "Plumbing", "seen": False, "items": [], "mto_items": []},
        {"name": "HVAC", "seen": False, "items": [], "mto_items": []},
        {"name": "Fire Sprinkler", "seen": False, "items": [], "mto_items": []},
    ],
}

# §8.4 BOQ lines (unit prices TBC — not yet quoted)
BOQ_LINES = [
    ("civil_architectural", "A.1",
     "Gypsum wall mod, reworks, repairs, repainting, fire-rated sealant"),
    ("electrical", "B.1", "Supply 1-inch EMT conduit with accessories"),
    ("electrical", "B.2", "Testing & Commissioning + Tagging + Panel schedule"),
]


def call(method: str, path: str, token: str | None = None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except json.JSONDecodeError:
            return e.code, None


def login() -> str:
    form = urllib.parse.urlencode(
        {"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=form)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]


def main() -> None:
    token = login()
    status, projects = call("GET", "/api/projects", token)
    if status != 200:
        raise SystemExit(f"list projects failed: {status}")
    projects = projects if isinstance(projects, list) else projects.get("items", [])

    existing = next((p for p in projects if p.get("pr_number") == PR), None)
    if existing:
        pid = existing["id"]
        print(f"{PR} already exists (id={pid}) — reusing")
    else:
        status, body = call("POST", "/api/projects", token, {
            "pr_number": PR, "ear_number": "12547", "title": TITLE,
            "location": LOCATION, "funding_source": "OPEX",
        })
        if status not in (200, 201):
            raise SystemExit(f"create project failed: {status} {body}")
        pid = body["id"]
        print(f"created {PR} (id={pid})")

    status, sows = call("GET", f"/api/projects/{pid}/sow", token)
    if sows:
        print(f"SOW already present ({sows[0]['revision_name']}) — skipping")
    else:
        status, body = call("POST", f"/api/projects/{pid}/sow", token,
                            {"trade_sections": TRADE_SECTIONS})
        if status not in (200, 201):
            raise SystemExit(f"create SOW failed: {status} {body}")
        print(f"seeded SOW {body['revision_name']} with §8 scope + MTO lines")

    status, items = call("GET", f"/api/projects/{pid}/boq", token)
    if items:
        print(f"BOQ already has {len(items)} lines — skipping")
    else:
        for trade, code, desc in BOQ_LINES:
            status, body = call("POST", f"/api/projects/{pid}/boq", token, {
                "trade": trade, "item_code": code, "description": desc,
                "unit": "Lot", "quantity": 1, "unit_rate": 0,
            })
            if status not in (200, 201):
                raise SystemExit(f"BOQ line {code} failed: {status} {body}")
        print(f"seeded {len(BOQ_LINES)} BOQ lines (§8.4, prices TBC)")

    print(f"\nReady. Project id={pid}. Generate with:")
    print(f"  POST /api/projects/{pid}/generate/sow|boq|mto|package")


if __name__ == "__main__":
    main()
