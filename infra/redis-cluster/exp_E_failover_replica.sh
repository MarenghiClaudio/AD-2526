#!/usr/bin/env bash
# =================================================================
# exp_E_failover_replica.sh — failover CON repliche (downtime).
#
# Come exp_C, ma sul cluster HA (master+repliche). Uccide un master a
# metà run e misura il DOWNTIME: il tempo che intercorre tra la caduta
# e la ripresa del servizio (quando la replica viene promossa).
#
# Il campionatore interroga TUTTI e 6 i nodi (porte 6379 e 6380) ogni
# secondo, così cattura il throughput a prescindere da chi è master.
#
# NB: uccidi a mano il container del master da una VM (più affidabile
# della password SSH). Lo script ti dice quando.
#
# Utilizzo (da Worker-1):
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" KILL_NODE=10.0.1.4 \
#     bash infra/redis-cluster/exp_E_failover_replica.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}
KILL_NODE=${KILL_NODE:?"IP del master da fermare"}
TEST_TIME=${TEST_TIME:-120}
export RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis/expE_failover_replica}
RUN=$HOME/AD-2526/infra/redis-cluster/run-memtier.sh
mkdir -p "$RESULTS_DIR"

SAMPLE_CSV="$RESULTS_DIR/timeline.csv"
echo "t_sec,total_ops_sec,reachable_nodes" > "$SAMPLE_CSV"

R() { docker run --rm --network host redis:7-alpine redis-cli "$@"; }

# Campionatore: somma ops/sec su tutti e 6 i nodi (6379 + 6380)
sampler() {
  local t=0
  while [ "$t" -lt "$TEST_TIME" ]; do
    local total=0 reach=0
    for ip in $NODES; do
      for port in 6379 6380; do
        ops=$(R -h "$ip" -p "$port" INFO stats 2>/dev/null \
              | grep instantaneous_ops_per_sec | tr -d '\r' | cut -d: -f2 || true)
        if [ -n "${ops:-}" ]; then
          total=$(( total + ops )); reach=$(( reach + 1 ))
        fi
      done
    done
    echo "$t,$total,$reach" >> "$SAMPLE_CSV"
    t=$(( t + 1 )); sleep 1
  done
}

echo ">>> Campionatore timeline (6 nodi) → $SAMPLE_CSV"
sampler &
SAMPLER_PID=$!

echo ">>> Carico memtier (${TEST_TIME}s)"
SEED_IP=$(echo "$NODES" | awk '{print $1}') \
  THREADS=8 CLIENTS=100 PIPELINE=16 TEST_TIME=$TEST_TIME \
  OUT="failover_replica" bash "$RUN" &
MEMTIER_PID=$!

sleep $(( TEST_TIME / 2 ))
echo ""
echo "############################################################"
echo ">>> FERMA ORA IL MASTER su $KILL_NODE (t=$(( TEST_TIME / 2 ))s)"
echo ">>> Dal terminale di quella VM:  docker stop ad2526-redis-cluster"
echo ">>> Osserva: il throughput cala, poi RISALE quando la replica"
echo ">>> viene promossa (questo intervallo è il downtime)."
echo "############################################################"

wait $MEMTIER_PID || true
kill $SAMPLER_PID 2>/dev/null || true

echo ""
echo "Done. Timeline: $SAMPLE_CSV"
echo "Il downtime = secondi in cui total_ops_sec resta ~0 dopo il kill."
echo "Per ripristinare: sulla VM  docker start ad2526-redis-cluster"
