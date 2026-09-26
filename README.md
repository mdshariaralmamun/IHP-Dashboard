# IHP Design and Construction

Project delivery and coordination platform for KAUST In-House Projects (IHP).
Drives lab-modification / new-equipment Project Requests (PRs) from intake
through MOM, EAR, SOW/BOQ, procurement, and construction closeout, with an
AI review layer against KAUST standards and project precedent.

Monorepo:

- `backend/` — FastAPI (Python 3.11), SQLAlchemy 2 + Alembic, PostgreSQL 16 (+pgvector), template-driven document generation (docxtpl / openpyxl, PDF via LibreOffice)
- `frontend/` — Next.js 15 (App Router, TypeScript, Tailwind), proxies `/api/*` to the backend
- `docker-compose.yml` — `db`, `backend`, `frontend`, optional `cloudflared` (profile `tunnel`)
- `.github/workflows/` — CI (pytest + frontend build) and VPS deploy

## Local development

Easiest: double-click `start-dev.bat` (starts both servers in two windows),
or run `start-dev.sh` from Git Bash. Note: the backend uses port **8001**
locally because port 8000 is occupied by another service on this machine.

Manual start — backend (port 8001):

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8001
```

Frontend (port 3000, proxies `/api/*` to `http://localhost:8001` by default,
override with `API_URL`):

```bash
cd frontend
npm run dev
```

Log in with the seeded admin (`ADMIN_USERNAME` / `ADMIN_PASSWORD`, see `.env.example`).

## Deploy (VPS)

One-time: clone repo to `/opt/ihp`, `cp .env.example .env` and fill it in.
Then `docker compose up -d --build` (Cloudflare tunnel: either point your
existing cloudflared at `http://localhost:3000`, or
`docker compose --profile tunnel up -d`). Pushes to `main` auto-deploy via
GitHub Actions once `VPS_HOST` / `VPS_USER` / `VPS_SSH_KEY` secrets are set.

## Workflow stages

INTAKE → MOM_SENT → MOM_CONFIRMED → DISPOSITION → (ICR: straight to MTO →
procurement) | (PROJECT: EAR → SOW revisions → MTO) → PROCUREMENT →
WORK_PERMIT → CONSTRUCTION → CLOSEOUT. Stage 1 (Intake & MOM) is the first
implemented slice; later stages land one at a time.
