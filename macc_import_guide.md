# IHP MACC Price List Import & MTO Budget Summary Guide

## Overview
This guide explains how to import the MACC (Master Attendance & Cost Control) price list into the IHP database and use it to suggest unit rates in Material Take-Off (MTO) budgets at the **MTO stage** (Stage 5 of the IHP workflow).

The MACC file at `E:\ENGINEERING_DATA\Trakers\MACC - Items Price List - Quotation.xlsx` contains item codes, descriptions, trades, units, and unit rates (in SAR). After import, these rates are available via API for BOQ/MTO generation and project budget summaries.

---

## 1. Import the MACC Price List

### Step 1: Ensure Database is Migrated
The `master_pricing` table was added to `backend/app/models.py`. If you haven't run migrations, do so now:

```powershell
cd C:\Users\MOHAMMED MAMUN\IHP Design and Construction\backend
# If using Alembic:
alembic upgrade head
# Or create tables directly (dev only):
.venv\Scripts\python.exe -c "from app.models import Base; Base.metadata.create_all(bind=engine)"
```

### Step 2: Run the Import Script
```powershell
cd C:\Users\MOHAMMED MAMUN\IHP Design and Construction\backend
.venv\Scripts\python.exe -m scripts.import_macc_pricing
```

**What this does:**
- Reads `E:\ENGINEERING_DATA\Trakers\MACC - Items Price List - Quotation.xlsx`
- Normalizes trade names (CIVIL → civil_arch, MECH → mechanical, etc.)
- Upserts (inserts or updates) each item into `master_pricing` table
- Prints a summary: new items, updated items, skipped, errors

**Expected Output:**
```
IHP MACC Price List Importer
==================================================
Reading sheet 'Project Quotation (100 rows x 5 cols)
Import Summary:
  New items : 87
  Updated   : 12
  Skipped   : 99
  Errors    : 0
==================================================
Done. Database updated.
```

### Step 3: Verify Import
```powershell
.venv\Scripts\python.exe -c "
from app.db import SessionLocal
from app.models import MasterPricing
db = SessionLocal()
count = db.scalar(select(MasterPricing))
print(f'Total items in master_pricing: {count}')
# Show a few examples
for p in db.scalars(select(MasterPricing).limit(5)).all():
    print(f'  {p.item_code}: {p.description[:30]} | {p.trade} | {p.unit} | {p.base_unit_rate} SAR')
db.close()
"
```

---

## 2. API Endpoints (Now Available)

All endpoints are under `/api/mto/`:

### Get Price Suggestion for a Specific Item
```http
GET /api/mto/pricing/P-201
```
**Response:** MasterPricing JSON with base_unit_rate, trade, unit, etc.

### List All Price Suggestions (Filtered by Trade)
```http
GET /api/mto/pricing?trade=mechanical
```
**Response:** List of all MasterPricing items, optionally filtered by trade.

### Add/Update a Price Suggestion
```http
POST /api/mto/pricing
```
**Body (JSON):**
```json
{
  "item_code": "P-201",
  "description": "N2 Tie-in, certified",
  "trade": "plumbing",
  "unit": "ls",
  "base_unit_rate": 18000.0,
  "currency": "SAR",
  "description_ar": "توصيل N2",
  "notes": "Imported from MACC Q1 2026"
}
```
**Requires:** `users.manage` capability

---

## 3. Generate MTO Budget from Master Pricing

### Core Endpoint: Generate Budget from MACC Pricing
```http
POST /api/mto/project/{project_id}/generate-budget
```

**Requires:** `construction.manage` capability

**What it does:**
1. Fetches all **design-kind** `BoqMtoItem` rows for the project
2. Looks up `master_pricing` for each `item_code`
3. Calculates subtotal, VAT (15%), totals in SAR and USD
4. Creates/updates `ProjectBudgetSummary` at **MTO stage**
5. Returns full breakdown

**Example Request:**
```http
POST /api/mto/project/1/generate-budget
```

**Example Response:**
```json
{
  "project_id": 1,
  "pr_number": "12579",
  "stage": "MTO",
  "budget_generated_at": "2026-09-09T10:30:00Z",
  "summary": {
    "subtotal_sar": 11087.0,
    "vat_sar": 1663.05,
    "total_sar": 12750.05,
    "total_usd": 3400.28,
    "items_count": 21
  },
  "stage_budget": {
    "budget_sar": 11087.0,
    "estimated_sar": 12750.05,
    "committed_sar": 12750.05,
    "remaining_sar": 0.0
  },
  "items_detail": [
    {
      "item_code": "P-201",
      "description": "N2 Tie-in, certified",
      "trade": "plumbing",
      "unit": "ls",
      "quantity": 1,
      "unit_rate": 18000.0,
      "line_total": 18000.0,
      "pricing_source": "master_pricing_imported_from_MACC"
    },
    {
      "item_code": "M-104",
      "description": "4\" SS header, 4-way",
      "trade": "mechanical",
      "unit": "ea",
      "quantity": 1,
      "unit_rate": 42000.0,
      "line_total": 42000.0,
      "pricing_source": "master_pricing_imported_from_MACC"
    }
    // ... more items
  ],
  "pricing_source": "master_pricing_imported_from_MACC",
  "macc_file": "MACC - Items Price List - Quotation.xlsx"
}
```

### How it Works (Internal Logic)
1. Fetches all `BoqMtoItem` rows where `mto_kind == "design"` for the project
2. For each item, queries `master_pricing` by `item_code`
3. If found → uses `base_unit_rate` from MACC import
4. If not found → falls back to item's stored `unit_rate` (or 0.0)
5. Sums line totals, adds 15% VAT (KAUST standard)
6. Converts SAR → USD at fixed rate 3.75 SAR = 1 USD
7. Creates `ProjectBudgetSummary` at stage "MTO"
8. Updates `ProjectStageBudget` for "MTO" stage

---

## 4. Project Budget Summary at MTO Stage

### Retrieve Budget Summary
```http
GET /api/mto/project/{project_id}/budget-summary
```

**Response:** `ProjectBudgetSummary` JSON with:
- `subtotal_sar`: Sum of all unit rates × quantities (from master pricing)
- `vat_sar`: 15% of subtotal
- `total_sar`: subtotal + VAT
- `total_usd`: total_sar / 3.75
- `items_count`: number of BOQ items included
- `stage_at_snapshot`: e.g., "MTO", "SOW_DRAFT", etc.
- `variance_pct`: budget vs actual variance (if tracked)

### Create/Update Budget Summary
```http
POST /api/mto/project/{project_id}/budget-summary?stage=MTO
```
**Requires:** `users.manage` capability  
Use this when advancing a project to the MTO stage to capture the budget snapshot.

---

## 5. How It Appears in the System

### Project Dashboard (Frontend)
When viewing a project's budget summary:
1. The system queries `/api/mto/project/{id}/budget-summary`
2. Displays subtotal, VAT, total (SAR + USD)
3. Lists items with unit rates sourced from master pricing
4. Shows pricing source: "MACC imported" or "historical estimate"

### MTO Stage Panel
In the project detail page's **5-6. Construction** tab:
- Budget summary is shown at the top
- "Suggested rates" badge appears if master pricing is available
- Users can click "Refresh from MACC" to re-run the budget generation

### Budget Variance Tracking
As the project moves through stages (MTO → SOW → MTO_APPROVED → etc.):
1. Each stage advancement calls `/api/mto/project/{id}/budget-summary?stage={stage}`
2. A new snapshot is created
3. Variance (`variance_sar` / `variance_pct`) is calculated vs. previous snapshot
4. Helps track budget creep or savings

---

## 6. Example Workflow: From Import to Budget

### Step 1: Import MACC Pricing
```powershell
.venv\Scripts\python.exe -m scripts.import_macc_pricing
# Output: 87 new items imported, 12 updated, 0 errors
```

### Step 2: View Available Rates
```http
GET /api/mto/pricing?trade=mechanical
# Shows all mechanical items with SAR unit rates
```

### Step 2: Generate Budget for a Project
```http
POST /api/mto/project/6/generate-budget
# PR-20001 (Lab gas manifold) budget generated at MTO stage
# Subtotal: 11087 SAR, Total: 12750.05 SAR (with 15% VAT)
```

### Step 3: Project Dashboard Shows Budget
- Frontend pulls `/api/mto/project/6/budget-summary`
- Shows: "Budget: 12,750 SAR (3,400 USD) — 21 items"
- Items list shows unit rates from MACC import

### Step 4: Advance to Next Stage
When moving from MTO to MTO_APPROVED:
```http
POST /api/mto/project/6/budget-summary?stage=MTO_APPROVED
# Creates snapshot at MTO_APPROVED stage
# Variance calculated vs. MTO snapshot
```

---

## 6. Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| `404: Item not found in master_pricing` | Run the import script again; check item codes match BOQ exactly |
| `404: Project not found` | Verify project ID exists; use `/api/projects/{id}` first |
| `500: Could not parse rate` | Check MACC Excel has numeric values in Unit Rate column (col E) |
| Budget shows 0.0 SAR | Ensure BOQ items have `item_code` populated; run BOQ generation first |
| VAT not 15% | KAUST standard is 15%; override in code if your jurisdiction differs |
| USD conversion wrong | Fixed rate 3.75 SAR = 1 USD; change constant in `generate-mto-budget-from-pricing` if needed |

### Need to Reset/Reimport?
```powershell
# Delete all master_pricing rows and reimport
.venv\Scripts\python.exe -c "
from app.db import SessionLocal
from app.models import MasterPricing
db = SessionLocal()
db.query(MasterPricing).delete()
db.commit()
print(f'Deleted {db.query(MasterPricing).count()} rows')
"
.venv\Scripts\python.exe -m scripts.import_macc_pricing
```

---

## 7. Files Modified/Created

### Modified:
- `backend/app/models.py` — Added `MasterPricing`, `ProjectBudgetSummary`, `ProjectStageBudget` tables
- `backend/app/schemas.py` — Added `MasterPricingIn`, `MasterPricingOut` schemas
- `backend/app/api/mto.py` — New API endpoint file (20+ endpoints)
- `backend/app/main.py` — Added `/mto` router inclusion

### Created:
- `backend/scripts/import_macc_pricing.py` — CLI import script
- `macc_import_guide.md` — This guide

### Untracked (already existed, now integrated):
- `backend/app/api/imports.py` — MACC file already in project
- `backend/scripts/import_planner.py` — Uses similar import patterns

---

## 8. Quick Start Checklist

- [ ] Run import: ` .venv\Scripts\python.exe -m scripts.import_macc_pricing`
- [ ] Verify: ` .venv\Scripts\python.exe -c "from app.models import MasterPricing; db=SessionLocal(); print(db.scalar(select(MasterPricing)))"`
- [ ] Test API: `GET /api/mto/pricing` — should return list of items
- [ ] Generate budget: `POST /api/mto/project/{id}/generate-budget`
- [ ] View summary: `GET /api/mto/project/{id}/budget-summary`
- [ ] Frontend: Project dashboard should show budget with "MACC imported" badge

---

*Guide generated: 2026-09-09*  
*IHP Automation Platform — MACC Pricing Integration*