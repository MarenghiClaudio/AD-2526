# AD-2526

Database choice:
## Source
https://imerit.net/resources/blog/11-best-social-media-datasets-for-machine-learning-all-pbm/

## Datasets from Arizona state university
https://datasets.syr.edu/pages/datasets.html

## Datasets from Stanford university
https://snap.stanford.edu/data/

## Benchmark

`benchmark.ps1` misura le performance del backend FastAPI con e senza cache Redis, garantendo un confronto equo tra i due run: stesso DB, buffer pool PostgreSQL a regime, Redis pre-warm.

### Prerequisiti

- PostgreSQL in ascolto su `localhost:5432`
- Redis in ascolto su `localhost:6379` (es. `docker run -d -p 6379:6379 redis`)
- `pg_dump` e `psql` nel PATH (inclusi nell'installazione di PostgreSQL)
- Dipendenze Python: `psycopg2`, `locust`

### Utilizzo

```powershell
# Run con valori di default (50 utenti, spawn 5/s, durata 60s, warm-up 45s, cooldown 10s)
.\benchmark.ps1

# Run personalizzato
.\benchmark.ps1 -Users 100 -SpawnRate 10 -Duration 2m -WarmupDuration 60s -CooldownSec 15

# Se non viene eseguito aggiungere
powershell -ExecutionPolicy Bypass -File .\benchmark.ps1
```

| Parametro | Default | Descrizione |
|---|---|---|
| `-Users` | `50` | Utenti Locust simultanei |
| `-SpawnRate` | `5` | Utenti avviati al secondo |
| `-Duration` | `60s` | Durata di ogni run misurato |
| `-WarmupDuration` | `45s` | Durata del warm-up (non misurato) |
| `-CooldownSec` | `10` | Secondi di attesa tra i due run |

### Sequenza di esecuzione

1. **Build DB** — genera il database una sola volta
2. **Snapshot** — salva `benchmark_results/db_snapshot.sql`
3. **Run 1 (cache OFF)** — ripristina lo snapshot, avvia il backend, esegue il warm-up, misura con Locust
4. **Cooldown** — pausa tra i run
5. **Run 2 (cache ON)** — ripristina lo stesso snapshot, avvia il backend, pre-scalda Redis, misura con Locust

### Risultati

I CSV vengono salvati in `benchmark_results/`:

| File | Contenuto |
|---|---|
| `no_cache_stats.csv` | Baseline PostgreSQL puro |
| `with_cache_stats.csv` | Con Redis |

Confrontare le colonne `50%` / `95%` / `99%` per endpoint per valutare il beneficio della cache.
