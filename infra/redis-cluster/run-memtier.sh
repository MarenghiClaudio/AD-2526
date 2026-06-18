#!/usr/bin/env bash
# =================================================================
# run-memtier.sh — wrapper parametrico di memtier_benchmark.
#
# Da eseguire su Worker-1 (nodo SEPARATO dal cluster, come da best
# practice ufficiale Redis). Colpisce il cluster Redis direttamente,
# bypassando FastAPI: misura Redis puro (throughput + latenza).
#
# Tutti i parametri via env, con default sensati:
#   SEED_IP    IP di un nodo del cluster (obbligatorio)
#   THREADS    thread del client            (default 4)
#   CLIENTS    connessioni per thread       (default 50)
#   PIPELINE   comandi in pipeline          (default 16)
#   RATIO      set:get                      (default 1:10, read-heavy)
#   TEST_TIME  durata in secondi            (default 120)
#   OUT        nome base file output        (default memtier)
#   RESULTS_DIR cartella output             (default ~/AD-2526/results/redis)
# =================================================================
set -euo pipefail

SEED_IP=${SEED_IP:?"Imposta SEED_IP con l'IP di un nodo del cluster"}
THREADS=${THREADS:-4}
CLIENTS=${CLIENTS:-50}
PIPELINE=${PIPELINE:-16}
RATIO=${RATIO:-1:10}
TEST_TIME=${TEST_TIME:-120}
OUT=${OUT:-memtier}
RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis}

mkdir -p "$RESULTS_DIR"

echo ">>> memtier: seed=$SEED_IP t=$THREADS c=$CLIENTS pipeline=$PIPELINE ratio=$RATIO time=${TEST_TIME}s"

# --cluster-mode: segue i redirect MOVED/ASK tra gli shard
# -R --key-pattern=R:R: chiavi random → distribuzione uniforme tra i nodi
# --distinct-client-seed: ogni client usa chiavi diverse (evita hot key)
# --json-out-file: output strutturato per il parsing
docker run --rm --network host \
  --ulimit nofile=1048576:1048576 \
  -v "$RESULTS_DIR:/out" \
  redislabs/memtier_benchmark:latest \
    --cluster-mode \
    -s "$SEED_IP" -p 6379 \
    -t "$THREADS" -c "$CLIENTS" \
    --pipeline "$PIPELINE" \
    --ratio "$RATIO" \
    -R --key-pattern=R:R \
    --distinct-client-seed \
    --test-time "$TEST_TIME" \
    --hide-histogram \
    --json-out-file "/out/${OUT}.json" \
  | tee "$RESULTS_DIR/${OUT}.txt"

echo ">>> Output: $RESULTS_DIR/${OUT}.json (+ .txt)"
