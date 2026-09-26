# Backend image: FastAPI + uvicorn, with LibreOffice headless for DOCX->PDF export.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# LibreOffice (headless `soffice`) + fonts for PDF conversion of generated
# documents. --no-install-recommends keeps the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-core \
       libreoffice-writer \
       fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching, then the app itself.
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY templates ./templates
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
