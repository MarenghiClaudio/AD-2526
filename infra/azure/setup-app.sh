#!/usr/bin/env bash
# =================================================================
# setup-app.sh — VM applicativa: backend FastAPI + Redis + Locust
#
# Prerequisiti: Ubuntu 22.04, eseguire come root (sudo -E bash ...)
# Il repo deve essere già clonato; master e repliche già in esecuzione.
#
# Utilizzo:
#   git clone --branch cluster-cm git@github.com:MarenghiClaudio/AD-2526.git AD-2526
#   cd /opt/ad2526
#   export MASTER_IP=10.0.0.4
#   export REPLICA_IPS=10.0.0.5,10.0.0.6,10.0.0.7
#   export CACHE_STRATEGY=cache_aside
#   sudo -E bash infra/azure/setup-app.sh
# =================================================================
set -euo pipefail

MASTER_IP=${MASTER_IP:?'Imposta MASTER_IP'}
REPLICA_IPS=${REPLICA_IPS:?'Imposta REPLICA_IPS (comma-separated)'}
CACHE_STRATEGY=${CACHE_STRATEGY:-cache_aside}
PROJECT_DIR=${PROJECT_DIR:-$HOME/AD-2526}

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
step() { echo ""; echo ">>> $*"; }

step "1/4 — Installazione Docker"
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

step "2/4 — Aggiornamento repository"
if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "ERRORE: $PROJECT_DIR non è un repository git."
  echo "Clona il repo prima di eseguire questo script:"
  echo "  git clone --branch cluster-cm git@github.com:MarenghiClaudio/AD-2526.git $PROJECT_DIR"
  exit 1
fi
git -C "$PROJECT_DIR" pull
cd "$PROJECT_DIR"

step "3/4 — Configurazione .env"
cp infra/azure/.env.app.template .env
sed -i "s|^MASTER_IP=.*|MASTER_IP=$MASTER_IP|"         .env
sed -i "s|^DB_HOSTS_READ=.*|DB_HOSTS_READ=$REPLICA_IPS|" .env
sed -i "s|^CACHE_STRATEGY=.*|CACHE_STRATEGY=$CACHE_STRATEGY|" .env
log "MASTER_IP=$MASTER_IP  |  REPLICA_IPS=$REPLICA_IPS  |  STRATEGY=$CACHE_STRATEGY"

step "4/4 — Build e avvio backend + Redis"
docker compose -f docker-compose.app.yml up -d --build

log "Attesa backend healthy..."
for i in $(seq 1 20); do
  curl -fsS "http://localhost:8000/health" > /dev/null 2>&1 && break
  sleep 3
done

HEALTH=$(curl -s "http://localhost:8000/health" 2>/dev/null || echo '{"status":"timeout"}')

echo ""
echo "================================================================"
echo "  APP VM PRONTA"
echo "  Backend:  http://$(hostname -I | awk '{print $1}'):8000"
echo "  Locust:   http://$(hostname -I | awk '{print $1}'):8089  (vedi sotto)"
echo "  Strategia attiva: $CACHE_STRATEGY"
echo "  Health: $HEALTH"
echo ""
echo "  BENCHMARK (headless):"
echo "    docker compose -f docker-compose.app.yml \\"
echo "      --profile benchmark run --rm locust \\"
echo "      --users 100 --spawn-rate 20 --run-time 5m --headless \\"
echo "      --csv=/mnt/locust/results_distributed/$CACHE_STRATEGY"
echo ""
echo "  CAMBIARE STRATEGIA tra un run e l'altro:"
echo "    sed -i 's/CACHE_STRATEGY=.*/CACHE_STRATEGY=write_through/' .env"
echo "    docker compose -f docker-compose.app.yml up -d backend"
echo "================================================================"
