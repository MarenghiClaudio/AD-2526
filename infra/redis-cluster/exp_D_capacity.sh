#!/usr/bin/env bash
# =================================================================
# exp_D_capacity.sh — scaling di CAPACITÀ (memoria) con i nodi.
#
# Risponde a "scala a parità di richieste all'aumentare dei nodi" sulla
# dimensione MEMORIA: con lo sharding, più nodi = più RAM totale = più
# chiavi cachate prima dell'eviction. Questo è lo scaling osservabile
# con l'hardware disponibile (il throughput è client-bound).
#
# Per ogni N in 1,2,3: limita maxmemory per nodo, riempie oltre la
# capacità, misura chiavi trattenute (DBSIZE) ed evizioni.
#
# Utilizzo (da Worker-1):
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/exp_D_capacity.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}
MAXMEM=${MAXMEM:-256mb}
RESHAPE=$HOME/AD-2526/infra/redis-cluster/cluster-reshape.sh
SEED=$(echo "$NODES" | awk '{print $1}')
RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis/expD_capacity}
mkdir -p "$RESULTS_DIR"
CSV="$RESULTS_DIR/capacity.csv"
echo "nodes,keys_total,evicted_total" > "$CSV"

R() { docker run --rm --network host redis:7-alpine redis-cli "$@"; }

for N in 1 2 3; do
  echo ""
  echo "########## CAPACITÀ con $N nodi (maxmemory=$MAXMEM/nodo) ##########"
  NODES="$NODES" N=$N bash "$RESHAPE"
  sleep 2

  ACTIVE=$(echo "$NODES" | tr ' ' '\n' | head -n "$N")

  # maxmemory + policy + flush su ogni nodo attivo
  for ip in $ACTIVE; do
    R -h "$ip" -p 6379 CONFIG SET maxmemory "$MAXMEM" >/dev/null
    R -h "$ip" -p 6379 CONFIG SET maxmemory-policy allkeys-lru >/dev/null
    R -h "$ip" -p 6379 FLUSHALL >/dev/null
  done

  # Riempi: SOLO scritture (ratio 1:0), valori 100B, range grande per sforare
  echo "  Riempimento (60s)..."
  docker run --rm --network host \
    --ulimit nofile=1048576:1048576 \
    redislabs/memtier_benchmark:latest \
      --cluster-mode -s "$SEED" -p 6379 \
      --ratio=1:0 -R -d 100 \
      --key-pattern=R:R --key-minimum=1 --key-maximum=20000000 \
      -t 4 -c 25 --pipeline=16 --test-time=60 --hide-histogram >/dev/null

  # Misura chiavi trattenute + evizioni sui nodi attivi
  keys=0; evic=0
  for ip in $ACTIVE; do
    k=$(R -h "$ip" -p 6379 DBSIZE | tr -d '\r')
    e=$(R -h "$ip" -p 6379 INFO stats | grep evicted_keys | tr -d '\r' | cut -d: -f2)
    keys=$(( keys + ${k:-0} ))
    evic=$(( evic + ${e:-0} ))
  done
  echo "  → $N nodi: chiavi trattenute=$keys, evitte=$evic"
  echo "$N,$keys,$evic" >> "$CSV"
done

echo ""
echo "Done. Risultati in $CSV"
echo "Atteso: chiavi trattenute ~lineari coi nodi (1 nodo ~K, 3 nodi ~3K)"
