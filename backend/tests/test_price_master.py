"""Price-master sync tests (services/price_master.py + /api/mto/pricing/sync).

The Planner's cost-estimates markdown (E:\\ENGINEERING_DATA\\trackers\\...) is
the living materials price list. These tests pin the parser, the keyword
trade classifier, the upsert/deactivate semantics (source-scoped so MACC and
manual pricing rows are never touched), and the admin sync endpoint.
"""

import json

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import MasterPricing
from app.services import price_master, runtime_settings

SAMPLE_MD = """## Sheet1

| IHP - Materials cost estimates |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- |
| REF | DESCRIPTION | Unit | QTY | ITEM PRICE | TOTAL |
| 9001 | Supply 1-inch EMT conduit.( ITCC/Panasonic) | Pcs. | 20 | 31.35 | 627 |
| 9002 | PPR Tee ,DN 25mm,GF | ea | 4 | 14.25 | 57 |
| 9003 | Supply SS duct flange 100mm | Nos | 8 | 34.2 | 273.6 |
| nope | malformed row (skipped) | x | 1 | bad | 0 |
"""


@pytest.fixture()
def md_file(tmp_path):
    path = tmp_path / "CE test.md"
    path.write_text(SAMPLE_MD, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clean_price_master_rows():
    """The test DB is shared across the session — remove every row this
    file creates so the pre-existing pricing tests stay isolated."""
    yield
    db = SessionLocal()
    try:
        rows = db.scalars(select(MasterPricing).where(
            MasterPricing.notes.like("price-master:%")
        )).all()
        for row in rows:
            db.delete(row)
        manual = db.scalar(select(MasterPricing).where(
            MasterPricing.item_code == "P-MANUAL-1"))
        if manual is not None:
            db.delete(manual)
        db.commit()
    finally:
        db.close()


class TestParser:
    def test_parses_data_rows_skips_banner_and_malformed(self, md_file):
        rows = price_master.parse_markdown_table(md_file)
        assert [r["ref"] for r in rows] == ["9001", "9002", "9003"]
        assert rows[0]["description"].startswith("Supply 1-inch EMT")
        assert rows[0]["item_price"] == 31.35
        assert rows[1]["unit"] == "ea"

    def test_trade_inference(self):
        assert price_master.infer_trade("Supply 1-inch EMT conduit") == "electrical"
        assert price_master.infer_trade("PPR Tee DN 25") == "plumbing"
        assert price_master.infer_trade("SS duct volume damper") == "hvac"
        assert price_master.infer_trade("Supply CAT6A cable") == "low_current"
        assert price_master.infer_trade("Firestop sealant CP 601S") == "fire_protection"
        assert price_master.infer_trade("gypsum board panels") == "civil_arch"
        assert price_master.infer_trade("obscure widget") is None


class TestSync:
    def test_insert_then_idempotent_resync(self, md_file):
        db = SessionLocal()
        try:
            first = price_master.sync_from_file(db, md_file)
            assert first["imported"] == 3 and first["updated"] == 0
            item = db.scalar(select(MasterPricing).where(
                MasterPricing.item_code == "9002"))
            assert item.base_unit_rate == 14.25
            assert item.trade == "plumbing"
            assert item.currency == "SAR"
            assert item.notes.startswith("price-master:")

            second = price_master.sync_from_file(db, md_file)
            assert second["imported"] == 0 and second["updated"] == 3
        finally:
            db.close()

    def test_update_price_and_deactivate_removed_refs(self, md_file):
        db = SessionLocal()
        try:
            price_master.sync_from_file(db, md_file)
            # Planner edits the file: 9002 price changes, 9003 removed
            edited = md_file.read_text(encoding="utf-8").replace(
                "| 9002 | PPR Tee ,DN 25mm,GF | ea | 4 | 14.25 | 57 |",
                "| 9002 | PPR Tee ,DN 25mm,GF | ea | 4 | 20.0 | 80 |",
            ).replace(
                "| 9003 | Supply SS duct flange 100mm | Nos | 8 | 34.2 | 273.6 |\n",
                "",
            )
            md_file.write_text(edited, encoding="utf-8")
            result = price_master.sync_from_file(db, md_file)
            assert result["updated"] == 2 and result["imported"] == 0
            assert result["deactivated"] == 1

            kept = db.scalar(select(MasterPricing).where(
                MasterPricing.item_code == "9002"))
            removed = db.scalar(select(MasterPricing).where(
                MasterPricing.item_code == "9003"))
            assert kept.base_unit_rate == 20.0 and kept.is_active
            assert removed is not None and not removed.is_active  # deactivated, kept
        finally:
            db.close()

    def test_manual_and_macc_rows_never_touched(self, md_file):
        db = SessionLocal()
        try:
            manual = MasterPricing(
                item_code="P-MANUAL-1", description="manual entry",
                unit="EA", base_unit_rate=99.0, notes=None,
            )
            db.add(manual)
            db.commit()
            price_master.sync_from_file(db, md_file)
            db.refresh(manual)
            assert manual.is_active and manual.base_unit_rate == 99.0
            assert manual.notes is None  # not re-marked, not scoped to sync
        finally:
            db.close()


class TestSyncEndpoint:
    def test_admin_sync_via_endpoint(self, client, admin_headers, md_file,
                                     tmp_path, monkeypatch):
        # point the runtime setting at the tmp price file
        monkeypatch.setattr(runtime_settings, "_overrides_path",
                            lambda: tmp_path / "settings.json")
        (tmp_path / "settings.json").write_text(
            json.dumps({"PRICE_MASTER_PATH": str(md_file)}), encoding="utf-8")

        resp = client.post("/api/mto/pricing/sync", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["file_rows"] == 3 and body["imported"] == 3
        assert "trade values are keyword-inferred" in body["note"]

    def test_missing_file_is_400(self, client, admin_headers, tmp_path, monkeypatch):
        monkeypatch.setattr(runtime_settings, "_overrides_path",
                            lambda: tmp_path / "settings.json")
        (tmp_path / "settings.json").write_text(
            json.dumps({"PRICE_MASTER_PATH": str(tmp_path / "nope.md")}),
            encoding="utf-8")
        resp = client.post("/api/mto/pricing/sync", headers=admin_headers)
        assert resp.status_code == 400

    def test_non_admin_forbidden(self, client, role_headers):
        resp = client.post("/api/mto/pricing/sync",
                           headers=role_headers["member1"])
        assert resp.status_code == 403
