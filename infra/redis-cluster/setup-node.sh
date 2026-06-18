#!/usr/bin/env bash
# =================================================================
# setup-node.sh — avvia un nodo Redis Cluster su una VM (VM-1/2/3).
#
# Idempotente: ricrea il container con l'IP privato della VM come
# cluster-announce-ip. Da eseguire su OGNI nodo del cluster.
#
# Utilizzo (su ogni VM):
#   bash infra/redis-cluster/setup-node.sh
#
# Override opzionali:
#   REDIS_ANNOUNCE_IP=10.0.1.5  bash infra/redis-cluster/setup-node.sh
#   REDIS_MAXMEMORY=10gb        bash infra/redis-cluster/setup-node.sh
# =================================================================
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-$HOME/AD-2526}
# Primo IP privato della VM (su Azure è quello della VNet, es. 10.0.1.x).
ANNOUNCE_IP=${REDIS_ANNOUNCE_IP:-$(hostname -I | awk '{print $1}')}
COMPOSE="docker compose -f $PROJECT_DIR/infra/redis-cluster/docker-compose.redis-node.yml"

echo ">>> Nodo Redis Cluster — announce IP: $ANNOUNCE_IP"

cd "$PROJECT_DIR"
git pull || echo "  [warn] git pull saltato"

REDIS_ANNOUNCE_IP="$ANNOUNCE_IP" \
REDIS_MAXMEMORY="${REDIS_MAXMEMORY:-0}" \
  $COMPOSE up -d --force-recreate

echo ">>> Attesa avvio..."
for i in $(seq 1 20); do
  if docker exec ad2526-redis-cluster redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "  Nodo attivo e announcing $ANNOUNCE_IP:6379 (bus 16379)"
    exit 0
  fi
  sleep 1
done
echo "ERRORE: il nodo non risponde a PING" >&2
exit 1
