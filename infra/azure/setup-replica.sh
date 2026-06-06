#!/usr/bin/env bash
# =================================================================
# setup-replica.sh — VM replica: PostgreSQL hot standby
#
# Prerequisiti: Ubuntu 22.04, eseguire come root (sudo -E bash ...)
# Il repo deve essere già clonato e il master già in esecuzione.
#
# Utilizzo:
#   git clone https://github.com/<utente>/<repo> /opt/ad2526
#   cd /opt/ad2526
#   export MASTER_IP=10.0.0.4
#   export REPLICA_ID=1          # 1, 2 o 3 (solo per i log)
#   export REPLICATION_PASSWORD=replpassword
#   sudo -E bash infra/azure/setup-replica.sh
# =================================================================
set -euo pipefail

MASTER_IP=${MASTER_IP:?'Imposta MASTER_IP con l IP privato del master'}
REPLICA_ID=${REPLICA_ID:-1}
REPLICATION_PASSWORD=${REPLICATION_PASSWORD:-replpassword}
PROJECT_DIR=${PROJECT_DIR:-/opt/ad2526}
DATA_DIR=/opt/ad2526/replica-data

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
step() { echo ""; echo ">>> $*"; }

step "1/5 — Installazione Docker"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg lsb-release git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

step "2/5 — Aggiornamento repository"
if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "ERRORE: $PROJECT_DIR non è un repository git."
  echo "Clona il repo prima di eseguire questo script:"
  echo "  git clone https://github.com/<utente>/<repo> $PROJECT_DIR"
  exit 1
fi
git -C "$PROJECT_DIR" pull
cd "$PROJECT_DIR"

step "3/5 — Verifica connettività al master ($MASTER_IP:5432)"
if ! bash -c ">/dev/tcp/$MASTER_IP/5432" 2>/dev/null; then
  echo "ERRORE: impossibile raggiungere $MASTER_IP:5432"
  echo "Verifica che il master sia avviato e che la porta 5432 sia aperta nel NSG."
  exit 1
fi
log "Master raggiungibile."

step "4/5 — pg_basebackup dalla VM master"
# Rimuove dati precedenti se esistono
rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"

# pg_basebackup gira dentro un container temporaneo per avere psql/pg_basebackup
# senza installare PostgreSQL sull'host.
# Il flag -R crea automaticamente standby.signal e primary_conninfo.
log "Avvio pg_basebackup (può richiedere qualche minuto)..."
docker run --rm \
  -e PGPASSWORD="$REPLICATION_PASSWORD" \
  -v "$DATA_DIR:/var/lib/postgresql/data" \
  postgres:16-alpine \
  pg_basebackup \
    --host="$MASTER_IP" \
    --port=5432 \
    --username=replicator \
    --pgdata=/var/lib/postgresql/data/pgdata \
    --wal-method=stream \
    --write-recovery-conf \
    --progress \
    --verbose

# Corregge i permessi (postgres user dentro il container è uid 999)
chown -R 999:999 "$DATA_DIR"
log "pg_basebackup completato."

step "5/5 — Avvio replica"
REPLICA_DATA_DIR="$DATA_DIR" \
  docker compose -f docker-compose.replica.yml up -d

log "Attesa replica healthy..."
for i in $(seq 1 20); do
  if docker compose -f docker-compose.replica.yml exec -T postgres \
    pg_isready -U postgres > /dev/null 2>&1; then break; fi
  sleep 3
done

echo ""
echo "================================================================"
echo "  REPLICA $REPLICA_ID PRONTA"
echo "  PostgreSQL (read-only): $(hostname -I | awk '{print $1}'):5432"
echo ""
echo "  Verifica replica attiva:"
echo "    docker compose -f docker-compose.replica.yml exec postgres \\"
echo "      psql -U postgres -c 'SELECT pg_is_in_recovery();'"
echo "    # deve restituire: t (true)"
echo "================================================================"
