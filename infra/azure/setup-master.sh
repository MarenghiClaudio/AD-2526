#!/usr/bin/env bash
# =================================================================
# setup-master.sh — VM master: PostgreSQL primary + data loader
#
# Prerequisiti: Ubuntu 22.04, eseguire come root (sudo -E bash ...)
#
# Utilizzo:
#   export REPO_URL=https://github.com/<utente>/<repo>
#   export DOWNLOAD_DATASET=1    # per scaricare twitter_combined.txt
#   sudo -E bash infra/azure/setup-master.sh
# =================================================================
set -euo pipefail

REPO_URL=${REPO_URL:?'Imposta REPO_URL'}
PROJECT_DIR=${PROJECT_DIR:-/opt/ad2526}
DOWNLOAD_DATASET=${DOWNLOAD_DATASET:-0}

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

step "2/5 — Clone repository"
if [ -d "$PROJECT_DIR/.git" ]; then
  git -C "$PROJECT_DIR" pull
else
  git clone "$REPO_URL" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

step "3/5 — Dataset"
mkdir -p datasets
if [ -f datasets/twitter_combined.txt ]; then
  log "Dataset già presente."
elif [ "$DOWNLOAD_DATASET" = "1" ]; then
  log "Download SNAP Twitter dataset..."
  curl -L https://snap.stanford.edu/data/twitter_combined.txt.gz \
    | gunzip > datasets/twitter_combined.txt
else
  echo "ERRORE: datasets/twitter_combined.txt non trovato."
  echo "Esegui con DOWNLOAD_DATASET=1 oppure copia il file via scp."
  exit 1
fi

step "4/5 — Configurazione .env"
[ -f .env ] || cp infra/azure/.env.master .env

step "5/5 — Avvio PostgreSQL + caricamento dati"
docker compose -f docker-compose.master.yml up -d postgres
log "Attesa PostgreSQL..."
until docker compose -f docker-compose.master.yml exec -T postgres \
  pg_isready -U postgres -d ad > /dev/null 2>&1; do sleep 2; done

log "Caricamento dataset..."
docker compose -f docker-compose.master.yml --profile setup run --rm data_loader

echo ""
echo "================================================================"
echo "  MASTER PRONTO"
echo "  PostgreSQL: $(hostname -I | awk '{print $1}'):5432"
echo ""
echo "  PROSSIMO PASSO:"
echo "  1. Apri TCP 5432 nel NSG Azure verso le VM replica e app"
echo "  2. Annota questo IP privato — serve per MASTER_IP e pg_basebackup"
echo "================================================================"
