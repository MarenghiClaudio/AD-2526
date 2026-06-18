# Backend FastAPI per il progetto AD-2526.
# Build context: root del progetto (non ./backend).
# Build:  docker build -t ad2526-backend -f backend/Dockerfile .
# Run :   gestito da docker-compose.yml alla root del repo.

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/lists/*

WORKDIR /app

# Dipendenze: requirements.txt è nella root del progetto.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Codice applicativo.
COPY backend/app/ ./app/

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "8"]
