#!/usr/bin/env bash
# =================================================================
# cluster-reshape.sh — (ri)forma un cluster con i primi N nodi.
#
# Serve all'esperimento B (scaling a parità di richieste): permette di
# misurare con 1, 2 o 3 master usando le STESSE VM.
#
# Usa CLUSTER RESET HARD + MEET + ADDSLOTSRANGE (Redis 7+): assegna
# tutti i 16384 slot equamente tra gli N nodi selezionati. I nodi
# esclusi (quando N<3) restano standalone e inattivi.
#
# Utilizzo (da Worker-1):
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" N=2 bash cluster-reshape.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}
N=${N:?"numero di master (1, 2 o 3)"}

ALL=($NODES)
SEL=("${ALL[@]:0:$N}")

R() { docker run --rm --network host redis:7-alpine redis-cli "$@"; }

echo ">>> Reshape a $N nodi: ${SEL[*]}"

# 1. Reset di TUTTI i nodi (pulizia completa, anche gli esclusi)
for ip in "${ALL[@]}"; do
  R -h "$ip" -p 6379 CLUSTER RESET HARD >/dev/null 2>&1 || true
  R -h "$ip" -p 6379 FLUSHALL >/dev/null 2>&1 || true
done
sleep 1

# 2. MEET: unisci i nodi selezionati (dal primo verso gli altri)
FIRST="${SEL[0]}"
for ip in "${SEL[@]:1}"; do
  R -h "$FIRST" -p 6379 CLUSTER MEET "$ip" 6379 >/dev/null
done
sleep 2

# 3. Assegna i 16384 slot equamente tra gli N nodi
TOTAL=16384
PER=$(( TOTAL / N ))
start=0
for i in "${!SEL[@]}"; do
  ip="${SEL[$i]}"
  if [ "$i" -eq $(( N - 1 )) ]; then
    end=$(( TOTAL - 1 ))      # l'ultimo nodo prende il resto
  else
    end=$(( start + PER - 1 ))
  fi
  echo "    $ip → slot $start-$end"
  R -h "$ip" -p 6379 CLUSTER ADDSLOTSRANGE "$start" "$end" >/dev/null
  start=$(( end + 1 ))
done
sleep 2

# 4. Verifica
echo ">>> Stato:"
R -h "$FIRST" -p 6379 CLUSTER INFO | grep -E "cluster_state|cluster_size"
