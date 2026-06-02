# Backend — Social Network API

Backend FastAPI con caching layer plug-in. La strategia attiva si seleziona
via `.env` (`CACHE_STRATEGY`) senza modificare le route.

## Architettura

```
backend/
├── .env                       # configurazione runtime (DB, Redis, FYP, strategy attiva)
├── Dockerfile                 # immagine del backend
├── requirements.txt
├── locustfile.py              # load generator (read 95% / write 5%, Zipf)
└── app/
    ├── main.py                # bootstrap FastAPI + lifespan + router wiring
    ├── config.py              # Settings via pydantic-settings
    ├── db.py                  # ThreadedConnectionPool psycopg2 + Depends(get_db)
    ├── cache.py               # ConnectionPool Redis + CacheService + Keys
    ├── core/
    │   ├── timing.py          # Timer + RequestTiming
    │   ├── request_state.py   # aggancia il timer a request.state
    │   └── responses.py       # ApiResponse[T] + Timing + build_response
    ├── middleware/
    │   └── request_logger.py  # log strutturato per-request (JSONL, hit incluso)
    ├── strategies/            # ★ caching strategy plug-in
    │   ├── base.py            # contratto CacheStrategy + StrategyContext
    │   ├── cache_aside.py     # lazy loading + TTL (default)
    │   ├── no_cache.py        # bypass (= baseline Fase 1)
    │   ├── deps.py            # Depends FastAPI per strategy + context
    │   ├── __init__.py        # registry STRATEGIES
    │   └── README.md          # come aggiungere una nuova strategy
    └── features/
        ├── users/             # GET  /users/{user_id}
        ├── posts/             # GET  /posts/{post_id}, POST /posts
        ├── likes/             # POST /likes, DELETE /likes
        ├── follows/           # POST /follows, DELETE /follows
        └── feed/              # GET  /timeline/{id}, GET /feed/{id}[?with_fof]
```

Per ogni feature: `routes.py` (endpoint HTTP) + `repository.py` (SQL puro,
data access) + `schemas.py` (modelli Pydantic). Le route delegano la
logica di lettura/invalidazione a una `CacheStrategy` (vedi
[`app/strategies/README.md`](app/strategies/README.md)).

## Strategie di caching

| Nome | Comportamento | Quando usarla |
|---|---|---|
| `no_cache` | bypassa Redis, tutte le letture a PG | baseline Fase 1, controllo A/B |
| `cache_aside` | lazy loading + TTL, invalidazione event-based | default Fase 2 |

Per aggiungere una nuova strategy vedi
[`app/strategies/README.md`](app/strategies/README.md). Workflow tipico:

1. Crea `app/strategies/<nome>.py` con una classe che eredita da `CacheStrategy`
2. Registrala in `app/strategies/__init__.py` (dict `STRATEGIES`)
3. Cambia `CACHE_STRATEGY=<nome>` in `.env`, riavvia uvicorn

## Setup

Da dentro `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

Il file `.env` è già pronto con default coerenti con i dati di Fase 1.
Modificare `DB_PASSWORD` se diverso.

## Esecuzione

```bash
uvicorn app.main:app --reload
```

Docs interattiva (Swagger): http://localhost:8000/docs

## Endpoint

| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/health` | Smoke check |
| GET | `/users/{user_id}` | Profilo + counter (post / follower / following) |
| GET | `/posts/{post_id}` | Post + like_count |
| POST | `/posts` | Crea post (`{user_id, content}`) |
| POST | `/likes` | Mette like (`{user_id, post_id}`, idempotente) |
| DELETE | `/likes` | Toglie like (idempotente) |
| POST | `/follows` | Segue (`{follower_id, followed_id}`, idempotente) |
| DELETE | `/follows` | Smette di seguire (idempotente) |
| GET | `/timeline/{user_id}?limit=50` | Feed cronologico (solo follow diretti) |
| GET | `/feed/{user_id}?limit=50` | FYP a 1° grado |
| GET | `/feed/{user_id}?with_fof=true` | FYP esteso al 2° grado |

Tutte le response sono dentro `ApiResponse[T]`:

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "timing": { "total_ms": 12.4, "db_ms": 9.8 }
}
```

## Misurazione

Tre livelli, complementari:

1. **Body della response** → campo `timing.total_ms` / `timing.db_ms`.
   Per debug a occhio durante lo sviluppo.

2. **Log strutturato per-request** → `requests.log` (path configurabile
   via `REQUEST_LOG_PATH`, "-" per stderr). Una riga JSON per request:

   ```json
   {"ts":..., "method":"GET", "path":"/feed/42", "status":200,
    "total_ms":12.4, "db_ms":9.8, "user_id":"42", "client":"..."}
   ```

   Analisi offline con pandas:

   ```python
   import pandas as pd
   df = pd.read_json("requests.log", lines=True)
   df.groupby("path")["total_ms"].describe(percentiles=[.5, .95, .99])
   ```

3. **Locust** → benchmark veri (percentili, throughput, scalabilità).

   ```bash
   locust -f locustfile.py --host http://localhost:8000
   ```

   UI su http://localhost:8089. Per accesso skewed realistico, esportare
   prima il pool degli user_id:

   ```sql
   \copy (SELECT user_id FROM ad.users) TO 'users.csv' WITH CSV
   ```

   e tenere `users.csv` nella stessa cartella del `locustfile.py`.
   Senza, lo script userà id contigui 1..N (smoke test only).

## Parametri del FYP

Tutti modificabili da `.env` senza toccare il codice:

| Variabile | Default | Significato |
|---|---|---|
| `FYP_WEIGHT_RECENCY` | 1.0 | Peso del termine recency |
| `FYP_WEIGHT_AFFINITY` | 2.0 | Peso del termine affinity |
| `FYP_WEIGHT_POPULARITY` | 0.5 | Peso del termine `ln(1+likes)` |
| `FYP_RECENCY_TAU_HOURS` | 24 | Costante di decadimento esponenziale |
| `FYP_RECENCY_WINDOW_DAYS` | 30 | Si guardano solo i post recenti |
| `FYP_AFFINITY_DIRECT` | 1.0 | Affinity per chi seguo direttamente |
| `FYP_AFFINITY_FOF` | 0.1 | Affinity per follower-of-follower |
| `FYP_DEFAULT_LIMIT` | 50 | LIMIT di default |
| `FYP_MAX_LIMIT` | 200 | Cap massimo richiedibile via `?limit=` |
