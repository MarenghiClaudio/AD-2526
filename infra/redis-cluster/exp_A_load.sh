#!/usr/bin/env bash
# =================================================================
# Esperimento A — throughput vs CARICO, cluster FISSO (3 nodi).
#
# Risponde a: "come scala Redis all'aumentare delle richieste a
# parità di nodi". Aumenta progressivamente thread/connessioni/pipeline
# e misura ops/sec finché il throughput si appiattisce (saturazione).
#
# Prerequisito: cluster a 3 nodi già formato (create-cluster.sh).
#
# Utilizzo (da Worker-1):
#   SEED_IP=10.0.1.5 bash infra/redis-cluster/exp_A_load.sh
# =================================================================
set -euo pipefail

SEED_IP=${SEED_IP:?"Imposta SEED_IP con l'IP di un nodo del cluster"}
export SEED_IP
export RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis/expA_load_3nodes}
RUN=$HOME/AD-2526/infra/redis-cluster/run-memtier.sh

# Configurazioni di carico crescente: "threads clients pipeline"
CONFIGS=(
  "2 25 1"
  "4 50 1"
  "4 50 8"
  "4 50 16"
  "8 50 16"
  "8 100 16"
  "8 100 32"
  "12 100 32"
)

for CFG in "${CONFIGS[@]}"; do
  read -r T C P <<< "$CFG"
  echo ""
  echo "=============================================="
  echo " Carico: threads=$T clients=$C pipeline=$P"
  echo "=============================================="
  THREADS=$T CLIENTS=$C PIPELINE=$P TEST_TIME=60 \
    OUT="load_t${T}_c${C}_p${P}" bash "$RUN"
done

echo ""
echo "Done. Risultati in $RESULTS_DIR"
