# AD-2526 — Caching layer per Social Network API

Architettura dati per un social network in cui PostgreSQL è source of truth
e Redis costituisce un caching layer ad alte prestazioni. Implementa il
backend FastAPI, le strategie di caching plug-in, la pipeline di
generazione dati e il benchmark con Locust.

## Struttura del repo

```
.
├── docker-compose.yml          # stack completo locale (PG + Redis + backend + loader)
├── docker-compose.master.yml   # stack VM master  (PG + Nginx load balancer)
├── docker-compose.worker.yml   # stack VM worker  (backend + Redis locale)
├── datasets/                   # twitter_combined.txt e altri file di input
├── infra/
│   ├── postgres/init/          # script SQL di bootstrap PG
│   └── azure/
│       ├── setup-master.sh     # provisioning VM master
│       ├── setup-worker.sh     # provisioning VM worker
│       ├── .env.master         # template env per il master
│       ├── .env.worker.template# template env per ogni worker
│       └── nginx.conf.template # config load balancer (round-robin)
├── social_network/             # pipeline dati (schema, loader, generator)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── *.py
└── backend/                    # API FastAPI + caching layer
    ├── Dockerfile
    ├── requirements.txt
    ├── locustfile.py
    └── app/
        ├── main.py             # bootstrap FastAPI + lifespan
        ├── config.py           # Settings (pydantic-settings, da .env)
        ├── db.py               # pool psycopg2
        ├── cache.py            # pool Redis + CacheService + Keys
        ├── core/               # timing, response envelope
        ├── middleware/         # request logging strutturato (JSONL)
        ├── strategies/         # ★ caching strategy plug-in
        │   ├── base.py         # contratto CacheStrategy
        │   ├── cache_aside.py  # strategy attiva di default
        │   ├── no_cache.py     # bypass (= baseline Fase 1)
        │   ├── deps.py         # DI FastAPI
        │   └── __init__.py     # registry
        └── features/           # users, posts, likes, follows, feed
            └── <feature>/
                ├── routes.py     # HTTP, delega alla strategy
                ├── repository.py # SQL puro (data access)
                └── schemas.py    # Pydantic models
```

## Quick start (con Docker)

Prerequisiti: **Docker Desktop** acceso.

```bash
# 1. Posiziona il dataset
#    Scarica twitter_combined.txt da SNAP e mettilo in datasets/
ls datasets/twitter_combined.txt

# 2. (Opzionale) Tara il numero di worker uvicorn alla tua CPU
#    Edita /.env (NON backend/.env) e imposta UVICORN_WORKERS = numero
#    di core FISICI della macchina. Default 8.

# 3. Avvia lo stack (postgres + redis + backend)
docker compose up -d

# 4. Popola il DB (one-shot, ~minuti)
docker compose --profile setup run --rm data_loader

# 5. Backend pronto su http://localhost:8000/docs
curl http://localhost:8000/health
```

### Configurazione UVICORN_WORKERS per macchina

Cambiare via `/.env` (root del repo), poi `docker compose up -d --force-recreate backend`.

Per cambiare strategia di caching (vedi sotto), edita `backend/.env`
(`CACHE_STRATEGY=...`) e riavvia il backend:

```bash
docker compose restart backend
```

## Strategie di caching

Il backend supporta caching strategy plug-in. La strategia attiva è
selezionata dalla variabile d'ambiente `CACHE_STRATEGY` (vedi
[`backend/.env`](backend/.env)).

Strategie incluse:

| Nome | Comportamento | Uso |
|---|---|---|
| `no_cache` | Bypassa Redis. Tutte le letture vanno a PG. | Baseline Fase 1, A/B testing |
| `cache_aside` | Lazy loading + TTL. Invalidazione event-based su user/post. | **Default**, Fase 2 |

Per **aggiungere una strategia** vedi
[`backend/app/strategies/README.md`](backend/app/strategies/README.md):
in pratica si aggiunge un file in `strategies/`, si registra in `__init__.py`,
e si attiva via `.env`. Niente modifiche alle route.

Strategie suggerite ai compagni di gruppo:
- **write_through** — cache aggiornata sincrona alle scritture
- **push_feed** — fan-out at write su sorted set Redis
- **hybrid** — push per utenti normali, pull per celebrity (Twitter-style)
- **write_behind** — write su cache, flush asincrono al DB

## Benchmark con Locust

```bash
# Backend in esecuzione, redis up, dati caricati.
cd backend
python -m venv .venv
.venv\Scripts\activate         # Windows
pip install -r requirements.txt

# Esporta il pool di user_id reali (una volta sola)
# Da psql connesso al DB ad:
#   \copy (SELECT user_id FROM ad.users) TO 'users.csv' WITH CSV

# Run di benchmark headless con CSV per analisi pandas
locust -f locustfile.py --host http://localhost:8000 \
  --users 100 --spawn-rate 20 --run-time 5m --headless \
  --csv=results/run01 --csv-full-history
```

Confronta le strategy lanciando lo stesso run con diversi `CACHE_STRATEGY`
in `.env`. I CSV sono direttamente confrontabili.

## Risultati Fase 2 (cache_aside vs no_cache)

| Utenti | Strategy | RPS | p50 | p95 | Fails |
|---|---|---|---|---|---|
| 50 | no_cache | 127 | 140 ms | 570 ms | 0% |
| 50 | cache_aside | **217** | **9 ms** | **140 ms** | 0% |
| 75 | cache_aside | 304 | 11 ms | 230 ms | 0% |
| 100 | no_cache | 127 | 470 ms | 1500 ms | 4.1% |
| 100 | cache_aside | **300** | **56 ms** | **460 ms** | 1.2% |
| 200 | no_cache | 150 | 620 ms | 3100 ms | 24% |
| 200 | cache_aside | 250 | 220 ms | 2400 ms | 12% |

Hit ratio osservato a regime: **~92%** (consistente con la distribuzione
Zipf dell'accesso utenti generato dal locustfile).

## Deployment distribuito (Azure)

### Topologia

```
VM app  (backend + Redis + Locust)
  ├── FastAPI  :8000   ← unico punto di ingresso per il benchmark
  └── Redis    :6379   ← caching layer locale

        ↕ scritture (POST/PUT/DELETE)       ↕ letture (GET, cache miss)
                                              round-robin tra le 3 repliche
VM master  (16 CPU · 64 GB)          VM replica 1  ─┐
  └── PostgreSQL :5432  (primary)    VM replica 2  ─┤─ hot standby
        └── streaming replication →  VM replica 3  ─┘
```

Il routing letture/scritture è automatico: `deps.py` assegna ad ogni
request una connessione al master (mutazioni) o a una replica (letture).
Locust gira sulla stessa VM del backend per minimizzare la latenza di rete
e misurare il sistema in condizioni controllate.

### Compose files per VM

| File | Usato su |
|------|----------|
| `docker-compose.master.yml` | VM master |
| `docker-compose.replica.yml` | VM replica 1/2/3 |
| `docker-compose.app.yml` | VM app |

### Setup — ordine obbligatorio

**1 — VM master**

```bash
# Prima cosa: clona il repo sulla VM (serve git, pre-installato su Ubuntu 22.04)
git clone --branch cluster-cm git@github.com:MarenghiClaudio/AD-2526.git AD-2526
cd AD-2526

# Esegui lo script — scarica il dataset da SNAP e avvia PostgreSQL
sudo -E bash infra/azure/setup-master.sh
```

Aprire TCP **5432** nel NSG Azure verso le VM replica e app.

**2 — VM replica** (eseguire su ciascuna delle 3)

```bash
git clone --branch cluster-cm git@github.com:MarenghiClaudio/AD-2526.git AD-2526
cd AD-2526

export MASTER_IP=<IP privato master>
export REPLICA_ID=1          # 1, 2 o 3
export REPLICATION_PASSWORD=replpassword
sudo -E bash infra/azure/setup-replica.sh
```

Lo script esegue `pg_basebackup` dal master e avvia il nodo in hot standby.
Verifica:
```bash
docker compose -f docker-compose.replica.yml exec postgres \
  psql -U postgres -c 'SELECT pg_is_in_recovery();'
# Atteso: t
```

**3 — VM app**

```bash
git clone --branch cluster-cm git@github.com:MarenghiClaudio/AD-2526.git AD-2526
cd AD-2526

export MASTER_IP=<IP privato master>
export REPLICA_IPS=<IP-replica1>,<IP-replica2>,<IP-replica3>
export CACHE_STRATEGY=cache_aside
sudo -E bash infra/azure/setup-app.sh
```

### Benchmark per strategia

Ogni run usa una strategia diversa, a parità di infrastruttura:

```bash
# Sulla VM app — run headless con CSV
docker compose -f docker-compose.app.yml \
  --profile benchmark run --rm locust \
  --users 100 --spawn-rate 20 --run-time 5m --headless \
  --csv=/mnt/locust/results_distributed/cache_aside

# Cambiare strategia per il run successivo (riavvio in ~3s)
sed -i 's/CACHE_STRATEGY=.*/CACHE_STRATEGY=write_through/' .env
docker compose -f docker-compose.app.yml up -d backend
```

## Sviluppo locale (senza Docker)

Se preferisci girare il backend direttamente sull'host:

```bash
# Avvia solo PG e Redis via docker-compose
docker compose up -d postgres redis

cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --workers 8
```

Lascia `DB_HOST=localhost` e `REDIS_HOST=localhost` in `backend/.env`.

## Roadmap

- ✅ Fase 1: baseline PG nudo, benchmark a 50/100/200 utenti
- ✅ Fase 2: caching layer con Redis single-node, strategia cache-aside
- ✅ Fase 2bis: confronto tra strategie multiple (write-through, push-feed, hybrid)
- ✅ Fase 3: deployment distribuito su Azure (1 master + 3 repliche + 1 app VM, read/write split round-robin)
- ⬜ Fase 3+: Redis Cluster (sharding), test di failover e scalabilità orizzontale
