#!/usr/bin/env bash
# =================================================================
# setup-replica-node.sh — avvia il SECONDO container Redis (porta 6380)
# su una VM, per la topologia ad alta disponibilità (master+repliche).
#
# Da eseguire su OGNI VM, DOPO setup-node.sh (che avvia il master su 6379).
#
# Utilizzo:  bash infra/redis-cluster/setup-replica-node.sh
# =================================================================
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-$HOME/AD-2526}
ANNOUNCE_IP=${REDIS_ANNOUNCE_IP:-$(hostname -I | awk '{print $1}')}
COMPOSE="docker compose -f $PROJECT_DIR/infra/redis-cluster/docker-compose.redis-replica.yml"

echo ">>> Nodo replica Redis (porta 6380) — announce IP: $ANNOUNCE_IP"
cd "$PROJECT_DIR"

REDIS_ANNOUNCE_IP="$ANNOUNCE_IP" $COMPOSE up -d --force-recreate

for i in $(seq 1 20); do
  if docker exec ad2526-redis-cluster-replica redis-cli -p 6380 ping 2>/dev/null | grep -q PONG; then
    echo "  Nodo replica attivo su $ANNOUNCE_IP:6380 (bus 16380)"
    exit 0
  fi
  sleep 1
done
echo "ERRORE: il nodo replica non risponde" >&2
exit 1
