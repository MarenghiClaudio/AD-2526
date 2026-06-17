#!/usr/bin/env bash
# =================================================================
# probe_downtime.sh — misura il DOWNTIME del failover.
#
# A differenza di memtier (che resta sulla vecchia topologia), questa
# sonda usa redis-cli in cluster-mode (-c): ad ogni richiesta segue i
# redirect e riconosce il nuovo master, quindi si RIPRENDE dopo la
# promozione della replica. Registra ~5 volte al secondo se il servizio
# risponde (1) o no (0) per una chiave dello shard che fai cadere.
#
# Procedura:
#   1) lancia questo script da Worker-1
#   2) a metà, da VM corrispondente:  docker stop ad2526-redis-cluster
#   3) la sonda registra la finestra di down e la ripresa
#
# Utilizzo:
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" KILL_NODE=10.0.1.4 \
#     bash infra/redis-cluster/probe_downtime.sh
# =================================================================
set -u

NODES=${NODES:?"NODES='ip1 ip2 ip3'"}
KILL_NODE=${KILL_NODE:?"IP del master che fermerai"}
DUR=${DUR:-90}
RESULTS_DIR=${RESULTS_DIR:-$HOME/AD-2526/results/redis/expF_downtime}
mkdir -p "$RESULTS_DIR"
CSV="$RESULTS_DIR/probe.csv"

# SEED: un nodo che SOPRAVVIVE (non quello che uccidi)
SEED=$(echo "$NODES" | awk '{print $1}')
if [ "$SEED" = "$KILL_NODE" ]; then SEED=$(echo "$NODES" | awk '{print $2}'); fi

R() { docker run --rm --network host redis:7-alpine redis-cli "$@"; }

# 1. range di slot del nodo da uccidere
RANGE=$(R -h "$SEED" -p 6379 cluster nodes | grep "${KILL_NODE}:6379" | grep master | awk '{print $9}' | tr -d '\r')
if [ -z "$RANGE" ]; then
  echo "ERRORE: $KILL_NODE non risulta master. Topologia:"
  R -h "$SEED" -p 6379 cluster nodes | awk '{print $2,$3,$9}'
  exit 1
fi
START=${RANGE%-*}; ENDS=${RANGE#*-}
echo ">>> $KILL_NODE possiede gli slot $RANGE"

# 2. trova una chiave che cade in quegli slot (così la sonda colpisce QUEL shard)
echo ">>> Cerco una chiave sullo shard target..."
KEY=$(docker run --rm --network host redis:7-alpine sh -c "
  for i in \$(seq 1 100000); do
    s=\$(redis-cli -h $SEED -p 6379 cluster keyslot \"k\$i\")
    if [ \"\$s\" -ge $START ] && [ \"\$s\" -le $ENDS ]; then echo \"k\$i\"; break; fi
  done")
echo ">>> Chiave sonda: $KEY"

echo "epoch_sec,available" > "$CSV"
echo ">>> Sonda attiva per ${DUR}s. ORA, a metà, ferma il master su $KILL_NODE:"
echo "      docker stop ad2526-redis-cluster"

# 3. loop di sonda dentro UN container (redis-cli -c con timeout breve)
docker run --rm --network host redis:7-alpine sh -c "
  end=\$(( \$(date +%s) + $DUR ))
  while [ \$(date +%s) -lt \$end ]; do
    t=\$(date +%s)
    if redis-cli -c -t 1 -h $SEED -p 6379 set $KEY 1 >/dev/null 2>&1; then
      echo \"\$t,1\"
    else
      echo \"\$t,0\"
    fi
    sleep 0.2
  done
" | tee -a "$CSV"

echo ""
echo ">>> Fatto. Dati in $CSV"
echo ">>> Ricordati di riavviare il nodo: docker start ad2526-redis-cluster"
