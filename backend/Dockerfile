# Backend image: FastAPI + uvicorn, with LibreOffice headless for DOCX->PDF export.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# LibreOffice (headless `soffice`) + fonts for PDF conversion of generated
# documents. --no-install-recommends keeps the image lean.
#
# Chromium as well, because it is the only renderer here that reproduces the
# HTML minute faithfully: LibreOffice's HTML import drops the stylesheet (CSS
# variables, flex layout, colours), so the "web view as PDF" came out as a
# plain black-and-white document with no logo. Chromium prints the page the
# way the browser shows it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-core \
       libreoffice-writer \
       fonts-dejavu \
       chromium \
       fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching, then the app itself.
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY templates ./templates
# scripts/ holds the planner importer that app/api/imports.py reuses, so it
# must ship with the image (its absence crashed the whole API at import).
COPY scripts ./scripts
RUN pip install .

# Run as a non-root user. /data is the runtime file-storage dir (DATA_DIR);
# it is backed by the named volume `ihp_data` from docker-compose.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Compose overrides this with "alembic upgrade head && uvicorn ...".
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
