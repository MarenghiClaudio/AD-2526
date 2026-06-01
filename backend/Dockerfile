# Backend FastAPI per il progetto AD-2526.
# Build:  docker build -t ad2526-backend ./backend
# Run :   gestito da docker-compose.yml alla root del repo.

FROM python:3.12-slim

# Build deps per psycopg2-binary (wheel non sempre disponibile su ARM/alpine).
# Su slim-bookworm è già tutto a posto; teniamo questo blocco minimale.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer cache friendly: prima le dipendenze, poi il codice.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Codice applicativo (no .env, no .venv, no requests.log — vedi .dockerignore).
COPY app/ ./app/

# Healthcheck: il container è "healthy" solo se /health risponde 200.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

# I parametri specifici (workers, host) li passa il docker-compose tramite
# `command:` per poterli sovrascrivere senza ricostruire l'immagine.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "8"]
