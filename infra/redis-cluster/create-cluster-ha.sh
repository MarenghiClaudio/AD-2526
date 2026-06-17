#!/usr/bin/env bash
# =================================================================
# create-cluster-ha.sh — cluster ad alta disponibilità:
# 3 master (porta 6379) + 3 repliche (porta 6380), --cluster-replicas 1.
#
# redis-cli assegna ogni replica a un master su una VM DIVERSA
# (anti-affinità automatica), così la caduta di un nodo non porta via
# anche la sua copia.
#
# Prerequisiti: su ogni VM devono girare ENTRAMBI i container
# (setup-node.sh + setup-replica-node.sh). I nodi devono essere "vergini":
# se erano in un cluster precedente, fai prima un reset (vedi sotto).
#
# Utilizzo (da Worker-1):
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/create-cluster-ha.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}

R() { docker run --rm --network host redis:7-alpine redis-cli "$@"; }

# Reset di tutti i nodi (master 6379 + replica 6380) per ripartire puliti
echo ">>> Reset dei nodi..."
for ip in $NODES; do
  R -h "$ip" -p 6379 CLUSTER RESET HARD >/dev/null 2>&1 || true
  R -h "$ip" -p 6379 FLUSHALL >/dev/null 2>&1 || true
  R -h "$ip" -p 6380 CLUSTER RESET HARD >/dev/null 2>&1 || true
  R -h "$ip" -p 6380 FLUSHALL >/dev/null 2>&1 || true
done
sleep 1

# 6 endpoint: prima i 3 master (6379), poi le 3 repliche (6380)
ENDPOINTS=""
for ip in $NODES; do ENDPOINTS="$ENDPOINTS ${ip}:6379"; done
for ip in $NODES; do ENDPOINTS="$ENDPOINTS ${ip}:6380"; done

echo ">>> Creazione cluster HA (3 master + 3 repliche):"
echo "    $ENDPOINTS"
docker run --rm --network host redis:7-alpine \
  redis-cli --cluster create $ENDPOINTS --cluster-replicas 1 --cluster-yes

echo ""
echo ">>> Stato cluster:"
FIRST=$(echo "$NODES" | awk '{print $1}')
R -h "$FIRST" -p 6379 cluster info | grep -E "cluster_state|cluster_size|cluster_known_nodes"
echo ""
echo ">>> Topologia (master e relative repliche):"
R -h "$FIRST" -p 6379 cluster nodes | awk '{print $2, $3, $9}'
