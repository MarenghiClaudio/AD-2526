#!/usr/bin/env python3
"""
benchmark_runner.py
Esegue un benchmark Locust completo per ogni strategia di cache.

Primo avvio (nessuno snapshot):
  1. Reset completo (down -v) + data_loader → snapshot pg_snapshot.pgdump
  2. Per ogni strategia: restore da snapshot, run Locust, salva CSV.

Avvii successivi (snapshot presente):
  - Salta il reset/data_loader (già fatto).
  - Usa direttamente lo snapshot → ogni restore richiede ~10-20s invece di
    svariati minuti.

Per forzare la ricostruzione dello snapshot (es. dopo aver cambiato dataset):
  FORCE_REBUILD = True  (oppure: cancella pg_snapshot.pgdump a mano)

Uso:
    python benchmark_runner.py

Richiede:
    - Docker in esecuzione
    - locust installato nell'ambiente Python attivo (pip install locust)
"""

# ╔══════════════════════════════════════════════════════════════════╗
# ║                    PARAMETRI BENCHMARK                           ║
# ╠══════════════════════════════════════════════════════════════════╣
# ║  Modifica questi valori prima di avviare il benchmark.           ║
# ╚══════════════════════════════════════════════════════════════════╝

STRATEGIES    = ["no_cache", "cache_aside", "write_through", "push_feed", "hybrid"]
LOCUST_USERS  = 100          # utenti simultanei
SPAWN_RATE    = 10           # utenti avviati al secondo
DURATION      = "300s"       # durata del test per strategia
FORCE_REBUILD = True        # True = ricrea snapshot anche se esiste già

# ─── Controllo bias ───────────────────────────────────────────────
# RESET_PG_CACHE: riavvia postgres tra una run e l'altra per svuotare
#   shared_buffers. Elimina il vantaggio che le run tarde hanno perché
#   trovano i dati già in memoria. Aggiunge ~20s per strategia.
RESET_PG_CACHE = True

# RANDOMIZE_ORDER: mescola l'ordine delle strategie prima del benchmark.
#   Elimina il bias di posizione (prima run = sistema freddo,
#   ultima run = sistema caldo). Utile per benchmark multi-run.
RANDOMIZE_ORDER = False

# ─── Percorsi (relativi alla root del progetto) ───────────────────
RESULTS_DIR   = "backend/results"
LOCUST_FILE   = "backend/locustfile.py"
USERS_CSV     = "backend/users.csv"
ENV_FILE      = ".env"
SNAPSHOT_FILE = "pg_snapshot.pgdump"   # dump binario PostgreSQL
PG_CONTAINER  = "ad2526-postgres"
PG_USER       = "postgres"
PG_DB         = "ad"

# ═══════════════════════════════════════════════════════════════════

import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


# ─── env / strategia ─────────────────────────────────────────────

def set_strategy(strategy: str) -> None:
    path = Path(ENV_FILE)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated, found = [], False
    for line in lines:
        if line.startswith("CACHE_STRATEGY="):
            updated.append(f"CACHE_STRATEGY={strategy}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"CACHE_STRATEGY={strategy}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print(f"  → CACHE_STRATEGY={strategy}")


# ─── Docker helpers ───────────────────────────────────────────────

def reset_and_load() -> None:
    print("  → Reset completo stack + volumi...")
    _run(["docker", "compose", "down", "-v", "--remove-orphans"])
    print("  → Caricamento dati (data_loader)...")
    _run(["docker", "compose", "--profile", "setup", "run", "--rm", "data_loader"])


def start_stack() -> None:
    print("  → Avvio stack completo...")
    _run(["docker", "compose", "up", "-d"])


def restart_backend() -> None:
    print("  → Ricreazione container backend...")
    _run(["docker", "compose", "up", "-d", "backend"])


def restart_postgres() -> None:
    """Riavvia postgres per azzerare shared_buffers (buffer cache fredda)."""
    print("  → Restart postgres (reset buffer cache)...", end="", flush=True)
    _run(["docker", "compose", "restart", "postgres"])
    deadline = time.time() + 60
    while time.time() < deadline:
        result = subprocess.run(
            ["docker", "exec", PG_CONTAINER, "pg_isready", "-U", PG_USER],
            capture_output=True,
        )
        if result.returncode == 0:
            print(" ✓")
            return
        print(".", end="", flush=True)
        time.sleep(2)
    print(" ✗ timeout")


def wait_backend(timeout: int = 120) -> bool:
    print(f"  → Attesa backend healthy (max {timeout}s)", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            print(" ✓")
            return True
        except Exception:
            print(".", end="", flush=True)
            time.sleep(3)
    print(" ✗ timeout")
    return False


# ─── Snapshot pg_dump / pg_restore ───────────────────────────────

def create_snapshot() -> None:
    """Dump del DB in formato custom PostgreSQL (binario compresso)."""
    print(f"  → pg_dump → {SNAPSHOT_FILE} ...")
    _run([
        "docker", "exec", PG_CONTAINER,
        "pg_dump", "-U", PG_USER, "-d", PG_DB,
        "--format=custom", "-f", f"/tmp/{SNAPSHOT_FILE}",
    ])
    _run(["docker", "cp", f"{PG_CONTAINER}:/tmp/{SNAPSHOT_FILE}", SNAPSHOT_FILE])
    size_mb = Path(SNAPSHOT_FILE).stat().st_size / 1024 / 1024
    print(f"  → Snapshot creato: {SNAPSHOT_FILE} ({size_mb:.1f} MB)")


def restore_snapshot() -> None:
    """
    Ripristina il DB dallo snapshot senza toccare i container Docker.
    Il postgres resta attivo; si ferma solo il backend per liberare le
    connessioni durante il DROP SCHEMA.
    """
    print(f"  → Ripristino da {SNAPSHOT_FILE} ...")
    t0 = time.time()

    # Ferma il backend per evitare connessioni aperte durante il DROP.
    _run(["docker", "compose", "stop", "backend"])

    # Svuota Redis: ogni strategia deve partire con cache fredda.
    _run(["docker", "exec", "ad2526-redis", "redis-cli", "FLUSHALL"])

    # Copia il dump nel container.
    _run(["docker", "cp", SNAPSHOT_FILE, f"{PG_CONTAINER}:/tmp/{SNAPSHOT_FILE}"])

    # Termina connessioni residue al DB (output soppresso).
    subprocess.run([
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", "postgres", "-t", "-c",
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname='{PG_DB}' AND pid <> pg_backend_pid();",
    ], capture_output=True)

    # Drop dello schema: pg_restore lo ricrea autonomamente dal dump.
    _run([
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DB, "-c",
        "DROP SCHEMA IF EXISTS ad CASCADE;",
    ])

    # Restore: il dump contiene già CREATE SCHEMA ad + tabelle + dati.
    _run([
        "docker", "exec", PG_CONTAINER,
        "pg_restore", "-U", PG_USER, "-d", PG_DB,
        "--no-owner", "--no-privileges",
        f"/tmp/{SNAPSHOT_FILE}",
    ])

    elapsed = time.time() - t0
    print(f"  → Restore completato in {elapsed:.1f}s")


# ─── users.csv ───────────────────────────────────────────────────

def export_users_csv() -> None:
    print(f"  → Export {USERS_CSV} ...")
    result = subprocess.run(
        ["docker", "exec", PG_CONTAINER,
         "psql", "-U", PG_USER, "-d", PG_DB,
         "-t", "-A", "-c", "SELECT user_id FROM ad.users ORDER BY user_id;"],
        check=True, capture_output=True, text=True,
    )
    Path(USERS_CSV).write_text("user_id\n" + result.stdout, encoding="utf-8")
    count = result.stdout.strip().count("\n") + 1
    print(f"  → {count:,} utenti esportati")


# ─── Locust ──────────────────────────────────────────────────────

def run_locust(strategy: str) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    csv_prefix = str(Path(RESULTS_DIR) / strategy)
    print(f"  → Locust: {LOCUST_USERS} utenti, {SPAWN_RATE}/s, {DURATION}")
    result = subprocess.run([
        sys.executable, "-m", "locust",
        "-f", LOCUST_FILE,
        "--headless",
        "--host", "http://localhost:8000",
        "-u", str(LOCUST_USERS),
        "-r", str(SPAWN_RATE),
        "--run-time", DURATION,
        "--csv", csv_prefix,
        "--csv-full-history",
        "--only-summary",
    ], env={**os.environ, "USERS_CSV": USERS_CSV})
    # exit 0 = ok, exit 1 = test completato con failures (accettabile),
    # exit 2+ = errore interno di locust (blocca il benchmark).
    if result.returncode > 1:
        raise subprocess.CalledProcessError(result.returncode, result.args)


# ─── main ────────────────────────────────────────────────────────

def main() -> None:
    strategies = list(STRATEGIES)
    if RANDOMIZE_ORDER:
        random.shuffle(strategies)

    total = len(strategies)
    snapshot = Path(SNAPSHOT_FILE)

    print(f"\n{'═' * 62}")
    print(f"  BENCHMARK — {total} strategie")
    print(f"  utenti={LOCUST_USERS}  spawn={SPAWN_RATE}/s  durata={DURATION}")
    print(f"  reset_pg_cache={RESET_PG_CACHE}  ordine={'casuale' if RANDOMIZE_ORDER else 'fisso'}")
    print(f"  snapshot: {SNAPSHOT_FILE} ({'presente' if snapshot.exists() and not FORCE_REBUILD else 'da creare'})")
    print(f"{'═' * 62}\n")

    need_build = FORCE_REBUILD or not snapshot.exists()

    if need_build:
        print("  → Prima esecuzione: setup completo + creazione snapshot.\n")
        reset_and_load()
        start_stack()
        if not wait_backend(timeout=180):
            print("  ✗ Backend non disponibile dopo il setup iniziale. Abort.")
            sys.exit(1)
        export_users_csv()
        create_snapshot()
    else:
        print(f"  → Snapshot trovato: ogni run farà pg_restore invece del data_loader.\n")
        start_stack()   # no-op se già in esecuzione

    for i, strategy in enumerate(strategies):
        print(f"\n{'─' * 62}")
        print(f"  [{i + 1}/{total}]  {strategy}")
        print(f"{'─' * 62}\n")

        # Il primo run usa il DB già pronto (da build o dallo start_stack).
        # I run successivi ripristinano lo snapshot per uno stato pulito.
        if i > 0 or need_build:
            if i > 0:
                restore_snapshot()
            if RESET_PG_CACHE:
                restart_postgres()

        set_strategy(strategy)
        restart_backend()

        if not wait_backend():
            print(f"  ✗ Backend non disponibile — skip {strategy}")
            continue

        run_locust(strategy)
        print(f"\n  ✓  {RESULTS_DIR}/{strategy}_stats.csv")

    print(f"\n{'═' * 62}")
    print("  Benchmark completati.")
    print(f"  Risultati:  {RESULTS_DIR}/")
    print(f"  Confronto:  python compare_results.py")
    print(f"{'═' * 62}\n")


if __name__ == "__main__":
    main()
