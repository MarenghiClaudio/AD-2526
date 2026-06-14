#!/bin/bash
set -e

STRATEGIES="no_cache cache_aside write_through push_feed hybrid"
USERS_LIST="10 25 50 75 100 150 200 300"
RUN_TIME="5m"
ENV_FILE="$HOME/AD-2526/.env"
COMPOSE="docker compose -f $HOME/AD-2526/docker-compose.app.yml"

mkdir -p "$HOME/AD-2526/results"

for STRATEGY in $STRATEGIES; do
  echo ""
  echo "=============================="
  echo " Strategia: $STRATEGY"
  echo "=============================="
  sed -i "s/CACHE_STRATEGY=.*/CACHE_STRATEGY=$STRATEGY/" $ENV_FILE
  $COMPOSE up -d backend
  sleep 5

  for USERS in $USERS_LIST; do
    echo "  → $USERS utenti..."
    $COMPOSE --profile benchmark run --rm locust \
      -f /mnt/locust/locustfile.py \
      --users $USERS \
      --spawn-rate 20 \
      --run-time $RUN_TIME \
      --headless \
      --csv=/mnt/results/${STRATEGY}_${USERS}u \
      --only-summary || true
  done
done

echo ""
echo "Done. Risultati in ~/AD-2526/results/"
