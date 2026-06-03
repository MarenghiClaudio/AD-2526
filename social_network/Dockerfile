# Data pipeline: crea lo schema PG + carica dataset SNAP Twitter + genera
# post/like sintetici. È un container one-shot.
# Build context: root del progetto (non ./social_network).
# Build:  docker build -t ad2526-loader -f social_network/Dockerfile .
# Usage:  vedi docker-compose.yml → service `data_loader` (profile: setup)

FROM python:3.12-slim

WORKDIR /app

# Dipendenze: requirements-loader.txt è nella root del progetto.
COPY requirements-loader.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements-loader.txt

# Script della pipeline.
COPY social_network/*.py ./

ENTRYPOINT ["python", "main.py"]
