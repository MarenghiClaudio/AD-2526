#!/usr/bin/env bash
# =================================================================
# setup-worker.sh — Provisioning di una VM worker (AD-2526)
#
# Installa Docker, avvia il backend FastAPI con la strategia
# di caching assegnata e Redis locale. PostgreSQL risiede sul master.
#
# Prerequisiti:
#   - Ubuntu 22.04 LTS
#   - Eseguire come root (o con sudo -E)
#   - Il master deve essere già configurato e raggiungibile
#
# Utilizzo (esempio worker 1 con strategia cache_aside):
#   export REPO_URL=git@github.com:MarenghiClaudio/AD-2526.git
#   export MASTER_IP=10.0.0.4          # IP privato della VM master
#   export CACHE_STRATEGY=cache_aside  # strategia per questo worker
#   export WORKER_ID=1                 # identificativo (1-4)
#   sudo -E bash infra/azure/setup-worker.sh
#
# Strategie disponibili:
#   no_cache | cache_aside | write_through | push_feed | hybrid
# =================================================================
set -euo pipefail

REPO_URL=${REPO_URL:?'REPO_URL non impostato'}
MASTER_IP=${MASTER_IP:?'MASTER_IP non impostato (IP privato della VM master)'}
CACHE_STRATEGY=${CACHE_STRATEGY:?'CACHE_STRATEGY non impostato'}
WORKER_ID=${WORKER_ID:-1}
PROJECT_DIR=${PROJECT_DIR:-$HOME/AD-2526}

VALID_STRATEGIES="no_cache cache_aside write_through push_feed hybrid"
if ! echo "$VALID_STRATEGIES" | grep -qw "$CACHE_STRATEGY"; then
  echo "Errore: CACHE_STRATEGY='$CACHE_STRATEGY' non valida."
  echo "Strategie disponibili: $VALID_STRATEGIES"
  exit 1
fi

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
step() { echo ""; echo ">>> $*"; }

# ------------------------------------------------------------------
step "1/5 — Installazione Docker"
# ------------------------------------------------------------------
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
log "Docker $(docker --version | cut -d' ' -f3) installato."

# ------------------------------------------------------------------
step "2/5 — Clone repository"
# ------------------------------------------------------------------
if [ -d "$PROJECT_DIR/.git" ]; then
  log "Directory già esistente — git pull."
  git -C "$PROJECT_DIR" pull
else
  git clone "$REPO_URL" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

# ------------------------------------------------------------------
step "3/5 — Verifica connettività al master ($MASTER_IP:5432)"
# ------------------------------------------------------------------
log "Test connessione al master..."
if ! curl -s --connect-timeout 5 "telnet://$MASTER_IP:5432" > /dev/null 2>&1; then
  # fallback: usa /dev/tcp (built-in bash)
  if ! bash -c ">/dev/tcp/$MASTER_IP/5432" 2>/dev/null; then
    echo ""
    echo "ATTENZIONE: non riesco a raggiungere $MASTER_IP:5432."
    echo "Verifica che:"
    echo "  1. Il master sia in esecuzione (docker compose ... up -d postgres)"
    echo "  2. La porta 5432 sia aperta nel NSG Azure verso questo worker"
    echo "  3. L'IP $MASTER_IP sia quello privato corretto"
    echo ""
    read -rp "Continuare comunque? [s/N] " choice
    [[ "$choice" =~ ^[sSyY]$ ]] || exit 1
  fi
fi
log "Master raggiungibile."

# ------------------------------------------------------------------
step "4/5 — Configurazione .env (worker $WORKER_ID — $CACHE_STRATEGY)"
# ------------------------------------------------------------------
cp infra/azure/.env.worker.template .env
sed -i "s|^MASTER_IP=.*|MASTER_IP=$MASTER_IP|" .env
sed -i "s|^CACHE_STRATEGY=.*|CACHE_STRATEGY=$CACHE_STRATEGY|" .env
log ".env configurato: MASTER_IP=$MASTER_IP, CACHE_STRATEGY=$CACHE_STRATEGY"

# ------------------------------------------------------------------
step "5/5 — Build e avvio backend + Redis"
# ------------------------------------------------------------------
docker compose -f docker-compose.worker.yml up -d --build

log "Attesa backend healthy (max 60s)..."
for i in $(seq 1 20); do
  if curl -fsS "http://localhost:8000/health" > /dev/null 2>&1; then
    break
  fi
  sleep 3
done

HEALTH=$(curl -s "http://localhost:8000/health" 2>/dev/null || echo '{"status":"timeout"}')

echo ""
echo "================================================================"
echo "  WORKER $WORKER_ID SETUP COMPLETATO"
echo ""
echo "  Backend:    http://$(hostname -I | awk '{print $1}'):8000"
echo "  Strategia:  $CACHE_STRATEGY"
echo "  Master DB:  $MASTER_IP:5432"
echo "  Health:     $HEALTH"
echo ""
echo "  Comandi utili:"
echo "    # Log backend in tempo reale"
echo "    docker compose -f docker-compose.worker.yml logs -f backend"
echo ""
echo "    # Cambiare strategia (modifica .env e riavvia)"
echo "    sed -i 's/CACHE_STRATEGY=.*/CACHE_STRATEGY=write_through/' .env"
echo "    docker compose -f docker-compose.worker.yml up -d backend"
echo ""
echo "    # Svuotare Redis (reset cache)"
echo "    docker compose -f docker-compose.worker.yml exec redis redis-cli FLUSHALL"
echo "================================================================"
