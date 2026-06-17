#!/usr/bin/env bash
# =================================================================
# create-cluster.sh — forma il cluster dai 3 nodi già avviati.
#
# Da eseguire UNA SOLA VOLTA, da una macchina che raggiunge tutti i
# nodi (es. Worker-1). Prima devi aver avviato setup-node.sh su VM-1/2/3.
#
# 3 master, nessuna replica (--cluster-replicas 0): sharding puro.
#
# Utilizzo:
#   NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/create-cluster.sh
# =================================================================
set -euo pipefail

NODES=${NODES:?"Imposta NODES con i 3 IP: NODES='ip1 ip2 ip3'"}

ENDPOINTS=""
for ip in $NODES; do
  ENDPOINTS="$ENDPOINTS ${ip}:6379"
done

echo ">>> Creazione cluster a 3 master (no replica):"
echo "    nodi: $ENDPOINTS"

# --network host: il container deve raggiungere gli IP privati delle VM
# sulle porte 6379 (dati) e 16379 (bus).
# --cluster-yes: niente prompt interattivo.
docker run --rm --network host redis:7-alpine \
  redis-cli --cluster create $ENDPOINTS --cluster-replicas 0 --cluster-yes

echo ""
echo ">>> Verifica stato cluster:"
FIRST_IP=$(echo $NODES | awk '{print $1}')
docker run --rm --network host redis:7-alpine \
  redis-cli -h "$FIRST_IP" -p 6379 cluster info | grep -E "cluster_state|cluster_known_nodes|cluster_size"
