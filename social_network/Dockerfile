# Data pipeline: crea lo schema PG + carica dataset SNAP Twitter + genera
# post/like sintetici. È un container one-shot: lo lancia docker-compose
# con il profilo "setup".
#
# Build:  docker build -t ad2526-loader ./social_network
# Usage:  vedi docker-compose.yml → service `data_loader` (profile: setup)
#         e README sezione "Setup iniziale".

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Script della pipeline (config, schema, loader, generator, main).
COPY *.py ./

# Il dataset SNAP arriva via volume su /data/twitter_combined.txt
# Il TWITTER_DATA_PATH lo passa docker-compose tramite environment.
ENTRYPOINT ["python", "main.py"]
