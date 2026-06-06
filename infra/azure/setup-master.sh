#!/usr/bin/env bash
# =================================================================
# setup-master.sh — VM master: PostgreSQL primary + data loader
#
# Prerequisiti: Ubuntu 22.04, eseguire come root (sudo -E bash ...)
# Il repo deve essere già clonato in PROJECT_DIR prima di eseguire.
#
# Utilizzo:
#   git clone https://github.com/<utente>/<repo> /opt/ad2526
#   cd /opt/ad2526
#   sudo -E bash infra/azure/setup-master.sh
#
# Il dataset twitter_combined.txt viene scaricato automaticamente da SNAP
# se non è già presente in datasets/.
# =================================================================
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/opt/ad2526}

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

step "3/5 — Dataset"
mkdir -p datasets
if [ -f datasets/twitter_combined.txt ]; then
  log "Dataset già presente, skip download."
else
  log "Download SNAP Twitter dataset..."
  curl -L https://snap.stanford.edu/data/twitter_combined.txt.gz \
    | gunzip > datasets/twitter_combined.txt
  log "Download completato: $(wc -l < datasets/twitter_combined.txt) righe."
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
