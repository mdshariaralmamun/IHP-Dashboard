"""Bucket filter tests — ?bucket= on /api/projects (IHP planner buckets).

Buckets are the planner's own MS-Project grouping (EAR, DESIGN, PTW/WICF,
CONSTRUCTION, QUALITY INSPECTION, WCH, WCC ...), persisted on
Project.planner_bucket by the planner import and backfill script.
"""

import itertools

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Project

_seq = itertools.count()


@pytest.fixture(autouse=True)
def _cleanup():
    """Shared session DB — remove the projects this file creates."""
    yield
    db = SessionLocal()
    try:
        for p in db.scalars(
            select(Project).where(Project.pr_number.like("PR-9200-%"))
        ).all():
            db.delete(p)
        db.commit()
    finally:
        db.close()


def _make_with_bucket(client, headers, bucket: str) -> str:
    pr = f"PR-9200-{next(_seq)}"
    resp = client.post("/api/projects", headers=headers, json={
        "pr_number": pr, "title": "Bucket filter test",
    })
    assert resp.status_code in (200, 201), resp.text
    db = SessionLocal()
    try:
        db.get(Project, resp.json()["id"]).planner_bucket = bucket
        db.commit()
    finally:
        db.close()
    return pr


class TestBucketFilter:
    def test_filter_matches_and_exposes_field(self, client, admin_headers):
        pr = _make_with_bucket(client, admin_headers, "DESIGN")

        resp = client.get("/api/projects", headers=admin_headers,
                          params={"bucket": "DESIGN"})
        assert resp.status_code == 200
        items = resp.json()
        match = next(p for p in items if p["pr_number"] == pr)
        assert match["planner_bucket"] == "DESIGN"

    def test_filter_is_case_insensitive(self, client, admin_headers):
        pr = _make_with_bucket(client, admin_headers, "WCH")
        resp = client.get("/api/projects", headers=admin_headers,
                          params={"bucket": "wch"})
        assert any(p["pr_number"] == pr for p in resp.json())

    def test_other_buckets_excluded(self, client, admin_headers):
        pr = _make_with_bucket(client, admin_headers, "WCC")
        resp = client.get("/api/projects", headers=admin_headers,
                          params={"bucket": "EAR"})
        assert not any(p["pr_number"] == pr for p in resp.json())

    def test_unbucketed_project_only_without_filter(self, client, admin_headers):
        pr = f"PR-9200-{next(_seq)}"
        resp = client.post("/api/projects", headers=admin_headers, json={
            "pr_number": pr, "title": "No bucket",
        })
        assert resp.status_code in (200, 201)
        listing = client.get("/api/projects", headers=admin_headers).json()
        assert any(p["pr_number"] == pr for p in listing)  # in full list
        filtered = client.get("/api/projects", headers=admin_headers,
                              params={"bucket": "EAR"}).json()
        assert not any(p["pr_number"] == pr for p in filtered)  # not in EAR
