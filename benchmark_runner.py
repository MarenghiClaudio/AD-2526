#!/usr/bin/env python3
"""
benchmark_runner.py
Esegue un benchmark Locust completo per ogni strategia di cache.
Per ogni strategia: resetta il DB da zero, avvia lo stack, esegue Locust,
salva i CSV con il nome della strategia.

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

STRATEGIES   = ["no_cache", "cache_aside", "write_through", "push_feed"]
LOCUST_USERS = 50          # utenti simultanei
SPAWN_RATE   = 5           # utenti avviati al secondo
DURATION     = "60s"       # durata del test per strategia

# ─── Percorsi (relativi alla root del progetto) ───────────────────
RESULTS_DIR  = "backend/results"
LOCUST_FILE  = "backend/locustfile.py"
USERS_CSV    = "backend/users.csv"
ENV_FILE     = ".env"

# ═══════════════════════════════════════════════════════════════════

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def set_strategy(strategy: str) -> None:
    """Aggiorna CACHE_STRATEGY in ENV_FILE."""
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
    print(f"  → CACHE_STRATEGY={strategy} scritto in {ENV_FILE}")


def export_users_csv() -> None:
    """Esporta user_id dal DB nel CSV letto da locust."""
    print(f"  → Export {USERS_CSV} dal DB...")
    result = subprocess.run(
        ["docker", "exec", "ad2526-postgres",
         "psql", "-U", "postgres", "-d", "ad",
         "-t", "-A", "-c", "SELECT user_id FROM ad.users ORDER BY user_id;"],
        check=True, capture_output=True, text=True,
    )
    # locustfile.py skippa la prima riga (header) con next()
    Path(USERS_CSV).write_text("user_id\n" + result.stdout, encoding="utf-8")
    count = result.stdout.strip().count("\n") + 1
    print(f"  → {count:,} utenti esportati")


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


def reset_and_load() -> None:
    print("  → Abbattimento stack + volumi...")
    _run(["docker", "compose", "down", "-v"])
    print("  → Caricamento dati (data_loader)...")
    _run(["docker", "compose", "--profile", "setup", "run", "--rm", "data_loader"])


def start_stack() -> None:
    print("  → Avvio stack completo...")
    _run(["docker", "compose", "up", "-d"])


def restart_backend() -> None:
    print("  → Ricreazione container backend...")
    _run(["docker", "compose", "up", "-d", "backend"])


def run_locust(strategy: str) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    csv_prefix = str(Path(RESULTS_DIR) / strategy)
    print(f"  → Locust: {LOCUST_USERS} utenti, {SPAWN_RATE}/s, {DURATION}")
    env = {**os.environ, "USERS_CSV": USERS_CSV}
    _run([
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
    ], env=env)


def main() -> None:
    total = len(STRATEGIES)
    print(f"\n{'═' * 62}")
    print(f"  BENCHMARK — {total} strategie")
    print(f"  utenti={LOCUST_USERS}  spawn={SPAWN_RATE}/s  durata={DURATION}")
    print(f"{'═' * 62}\n")

    for i, strategy in enumerate(STRATEGIES):
        print(f"\n{'─' * 62}")
        print(f"  [{i + 1}/{total}]  {strategy}")
        print(f"{'─' * 62}\n")

        reset_and_load()
        start_stack()
        export_users_csv()

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
