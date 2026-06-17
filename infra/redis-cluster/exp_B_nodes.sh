#!/usr/bin/env bash
# =================================================================
# Esperimento B — throughput vs NUMERO DI NODI, carico FISSO.
#
# Risponde a: "come scala Redis a parità di richieste all'aumentare
# dei nodi". Riconfigura il cluster a 1 → 2 → 3 master (stesse VM) e
# lancia memtier con parametri IDENTICI. Atteso: scaling ~lineare.
#
# Prerequisito: i 3 nodi avviati (setup-node.sh su ognuno).
#
# Utilizzo (da Worker-1):
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/exp_B_nodes.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}
export RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis/expB_nodes}
RESHAPE=$HOME/AD-2526/infra/redis-cluster/cluster-reshape.sh
RUN=$HOME/AD-2526/infra/redis-cluster/run-memtier.sh

# Carico costante per tutti i passi (deve essere abbastanza alto da
# tenere occupati i nodi, ma non così tanto da saturare il client).
T=8; C=100; P=16; TIME=120

for N in 1 2 3; do
  echo ""
  echo "##############################################"
  echo " CLUSTER A $N NODI — carico fisso t=$T c=$C p=$P"
  echo "##############################################"
  NODES="$NODES" N=$N bash "$RESHAPE"
  sleep 3
  SEED_IP=$(echo "$NODES" | awk '{print $1}') \
    THREADS=$T CLIENTS=$C PIPELINE=$P TEST_TIME=$TIME \
    OUT="nodes_${N}" bash "$RUN"
done

echo ""
echo "Done. Risultati in $RESULTS_DIR"
echo "Confronta ops/sec in nodes_1.json vs nodes_2.json vs nodes_3.json"
