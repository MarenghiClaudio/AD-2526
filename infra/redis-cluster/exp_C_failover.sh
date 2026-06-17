#!/usr/bin/env bash
# =================================================================
# Esperimento C — FALLIMENTO di un nodo durante carico costante.
#
# Risponde a: "come gestisce il fallimento di un nodo". Lancia memtier
# a carico costante; a metà run ferma un nodo Redis. Un campionatore
# legge ogni secondo instantaneous_ops_per_sec dai nodi SUPERSTITI e
# costruisce la timeline (per vedere il crollo e l'eventuale recovery).
#
# NB: con 3 master SENZA repliche, fermare un nodo manda il cluster in
# stato 'fail' per i suoi slot → memtier registra errori. È il
# comportamento atteso (failure "duro"). Per il recovery automatico
# servirebbero le repliche (fase successiva).
#
# Utilizzo (da Worker-1, con ssh verso i nodi):
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" KILL_NODE=10.0.1.4 \
#     bash infra/redis-cluster/exp_C_failover.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}
KILL_NODE=${KILL_NODE:?"IP del nodo da fermare (uno tra NODES)"}
TEST_TIME=${TEST_TIME:-120}
export RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis/expC_failover}
RUN=$HOME/AD-2526/infra/redis-cluster/run-memtier.sh
mkdir -p "$RESULTS_DIR"

SAMPLE_CSV="$RESULTS_DIR/timeline.csv"
echo "t_sec,total_ops_sec,reachable_nodes" > "$SAMPLE_CSV"

R() { docker run --rm --network host redis:7-alpine redis-cli "$@"; }

# --- Campionatore in background: ops/sec aggregati ogni secondo --------
sampler() {
  local t=0
  while [ "$t" -lt "$TEST_TIME" ]; do
    local total=0 reachable=0
    for ip in $NODES; do
      ops=$(R -h "$ip" -p 6379 INFO stats 2>/dev/null \
            | grep instantaneous_ops_per_sec | tr -d '\r' | cut -d: -f2 || true)
      if [ -n "${ops:-}" ]; then
        total=$(( total + ops ))
        reachable=$(( reachable + 1 ))
      fi
    done
    echo "$t,$total,$reachable" >> "$SAMPLE_CSV"
    t=$(( t + 1 ))
    sleep 1
  done
}

echo ">>> Avvio campionatore timeline → $SAMPLE_CSV"
sampler &
SAMPLER_PID=$!

echo ">>> Avvio carico memtier (${TEST_TIME}s)"
SEED_IP=$(echo "$NODES" | awk '{print $1}') \
  THREADS=8 CLIENTS=100 PIPELINE=16 TEST_TIME=$TEST_TIME \
  OUT="failover" bash "$RUN" &
MEMTIER_PID=$!

# --- A metà run, ferma il nodo ----------------------------------------
sleep $(( TEST_TIME / 2 ))
echo ""
echo ">>> >>> KILL del nodo $KILL_NODE a t=$(( TEST_TIME / 2 ))s <<< <<<"
ssh "Karzaladmin@$KILL_NODE" "docker stop ad2526-redis-cluster" \
  || echo "[warn] ssh fallito — ferma manualmente il container sul nodo $KILL_NODE"

wait $MEMTIER_PID || true
kill $SAMPLER_PID 2>/dev/null || true

echo ""
echo "Done. Timeline in $SAMPLE_CSV, aggregato in $RESULTS_DIR/failover.json"
echo "Per ripristinare il nodo: ssh Karzaladmin@$KILL_NODE 'docker start ad2526-redis-cluster'"
