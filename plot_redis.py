#!/usr/bin/env python3
"""
Grafici per i benchmark Redis Cluster (memtier_benchmark).

Legge gli output di:
  results/redis/expA_load_3nodes/load_*.json   → throughput vs carico
  results/redis/expB_nodes/nodes_{1,2,3}.json  → throughput vs nodi
  results/redis/expC_failover/timeline.csv     → throughput nel tempo (failover)

Output: results/redis/charts/*.png

Uso:  py plot_redis.py            (usa results/redis)
      py plot_redis.py <dir>      (cartella redis alternativa)
"""

import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
REDIS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "redis"
REDIS_DIR = REDIS_DIR if REDIS_DIR.is_absolute() else ROOT / REDIS_DIR
CHARTS = REDIS_DIR / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "figure.dpi": 150,
    "font.size": 11,
    "axes.grid": True,
    "grid.alpha": 0.35,
    "lines.linewidth": 2,
    "lines.markersize": 8,
})


# ── Parsing JSON memtier ───────────────────────────────────────────────────────
def _find_totals(obj):
    """Cerca ricorsivamente il dict 'Totals' nell'output memtier."""
    if isinstance(obj, dict):
        if "Totals" in obj and isinstance(obj["Totals"], dict):
            return obj["Totals"]
        for v in obj.values():
            r = _find_totals(v)
            if r is not None:
                return r
    return None


def _deep_get(obj, key):
    """Cerca ricorsivamente una chiave (es. 'p99.00') in dict annidati."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _deep_get(v, key)
            if r is not None:
                return r
    return None


def parse_memtier(path: Path) -> dict:
    """Ritorna {ops_sec, p50, p99} da un file JSON memtier."""
    with open(path) as f:
        data = json.load(f)
    totals = _find_totals(data) or {}
    ops = totals.get("Ops/sec") or _deep_get(data, "Ops/sec")
    p50 = totals.get("p50.00") or _deep_get(totals, "p50.00") or _deep_get(data, "p50.00")
    p99 = totals.get("p99.00") or _deep_get(totals, "p99.00") or _deep_get(data, "p99.00")
    return {
        "ops_sec": float(ops) if ops is not None else float("nan"),
        "p50": float(p50) if p50 is not None else float("nan"),
        "p99": float(p99) if p99 is not None else float("nan"),
    }


def _save(fig, name):
    p = CHARTS / name
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"  {p.name}")


# ── Esperimento A — throughput vs carico ───────────────────────────────────────
def plot_exp_a():
    d = REDIS_DIR / "expA_load_3nodes"
    files = sorted(d.glob("load_*.json"))
    if not files:
        print("  [A] nessun file load_*.json, skip.")
        return
    rows = []
    for f in files:
        m = re.match(r"load_t(\d+)_c(\d+)_p(\d+)\.json", f.name)
        if not m:
            continue
        t, c, p = map(int, m.groups())
        st = parse_memtier(f)
        rows.append({"conc": t * c, "pipe": p, **st})
    rows.sort(key=lambda r: (r["conc"], r["pipe"]))

    x = list(range(len(rows)))
    labels = [f"{r['conc']}c·p{r['pipe']}" for r in rows]

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(x, [r["ops_sec"] for r in rows], "o-", color="#2980b9", label="Ops/sec")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax1.set_xlabel("Carico (connessioni · pipeline)")
    ax1.set_ylabel("Throughput (ops/sec)", color="#2980b9")
    ax1.tick_params(axis="y", labelcolor="#2980b9")

    ax2 = ax1.twinx()
    ax2.plot(x, [r["p99"] for r in rows], "s--", color="#e74c3c", label="p99 (ms)")
    ax2.set_ylabel("Latenza p99 (ms)", color="#e74c3c")
    ax2.tick_params(axis="y", labelcolor="#e74c3c")
    ax2.grid(False)

    fig.suptitle("Esperimento A — throughput vs carico (cluster a 3 nodi)",
                 fontweight="bold")
    _save(fig, "expA_throughput_vs_load.png")


# ── Esperimento B — throughput vs numero di nodi ───────────────────────────────
def plot_exp_b():
    d = REDIS_DIR / "expB_nodes"
    rows = []
    for n in (1, 2, 3):
        f = d / f"nodes_{n}.json"
        if f.exists():
            rows.append({"nodes": n, **parse_memtier(f)})
    if not rows:
        print("  [B] nessun file nodes_*.json, skip.")
        return

    nodes = [r["nodes"] for r in rows]
    ops = [r["ops_sec"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(nodes, ops, "o-", color="#27ae60", label="Throughput misurato")
    # Linea di scaling lineare ideale (riferito al primo punto)
    if ops and ops[0] == ops[0]:  # non-NaN
        ideal = [ops[0] * n / nodes[0] for n in nodes]
        ax.plot(nodes, ideal, "--", color="gray", label="Scaling lineare ideale")
    ax.set_xticks(nodes)
    ax.set_xlabel("Numero di master nel cluster")
    ax.set_ylabel("Throughput (ops/sec)")
    ax.set_title("Esperimento B — throughput vs nodi (carico fisso)", fontweight="bold")
    ax.legend()
    _save(fig, "expB_throughput_vs_nodes.png")

    # Efficienza di scaling (% rispetto all'ideale)
    if ops and ops[0] == ops[0]:
        eff = [o / (ops[0] * n / nodes[0]) * 100 for o, n in zip(ops, nodes)]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(nodes, eff, "o-", color="#8e44ad")
        ax.axhline(100, color="gray", linestyle="--", label="100% (lineare)")
        ax.set_xticks(nodes)
        ax.set_ylim(0, 120)
        ax.set_xlabel("Numero di master")
        ax.set_ylabel("Efficienza di scaling (%)")
        ax.set_title("Esperimento B — efficienza di scaling", fontweight="bold")
        ax.legend()
        _save(fig, "expB_scaling_efficiency.png")


# ── Esperimento C — failover timeline ──────────────────────────────────────────
def plot_exp_c():
    f = REDIS_DIR / "expC_failover" / "timeline.csv"
    if not f.exists():
        print("  [C] timeline.csv assente, skip.")
        return
    import csv
    t, ops, reach = [], [], []
    with open(f) as fh:
        for row in csv.DictReader(fh):
            t.append(int(row["t_sec"]))
            ops.append(int(row["total_ops_sec"]))
            reach.append(int(row["reachable_nodes"]))

    # Istante del kill = primo calo di reachable_nodes
    kill_t = next((t[i] for i in range(1, len(reach)) if reach[i] < reach[i - 1]), None)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t, ops, "-", color="#2980b9", label="Throughput aggregato (ops/sec)")
    if kill_t is not None:
        ax.axvline(kill_t, color="#e74c3c", linestyle="--", linewidth=2,
                   label=f"Kill nodo (t={kill_t}s)")
    ax.set_xlabel("Tempo (s)")
    ax.set_ylabel("Ops/sec (somma nodi superstiti)")
    ax.set_title("Esperimento C — failover di un nodo", fontweight="bold")
    ax.legend()
    _save(fig, "expC_failover_timeline.png")


def plot_exp_d():
    f = REDIS_DIR / "expD_capacity" / "capacity.csv"
    if not f.exists():
        print("  [D] capacity.csv assente, skip.")
        return
    import csv
    nodes, keys, evic = [], [], []
    with open(f) as fh:
        for row in csv.DictReader(fh):
            nodes.append(int(row["nodes"]))
            keys.append(int(row["keys_total"]))
            evic.append(int(row["evicted_total"]))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([n - 0.0 for n in nodes], keys, width=0.5, color="#16a085",
           label="Chiavi trattenute")
    if keys and keys[0] > 0:
        ideal = [keys[0] * n / nodes[0] for n in nodes]
        ax.plot(nodes, ideal, "--o", color="gray", label="Scaling lineare ideale")
    ax.set_xticks(nodes)
    ax.set_xlabel("Numero di nodi (shard)")
    ax.set_ylabel("Chiavi trattenute in cache")
    ax.set_title("Esperimento D — capacità di cache vs nodi (sharding)",
                 fontweight="bold")
    ax.legend()
    _save(fig, "expD_capacity_vs_nodes.png")


def plot_exp_e():
    f = REDIS_DIR / "expE_failover_replica" / "timeline.csv"
    if not f.exists():
        print("  [E] timeline.csv (HA) assente, skip.")
        return
    import csv
    t, ops, reach = [], [], []
    with open(f) as fh:
        for row in csv.DictReader(fh):
            t.append(int(row["t_sec"]))
            ops.append(int(row["total_ops_sec"]))
            reach.append(int(row["reachable_nodes"]))

    # kill = primo calo di reachable; recovery = quando ops risale stabilmente
    kill_t = next((t[i] for i in range(1, len(reach)) if reach[i] < reach[i - 1]), None)
    recov_t = None
    if kill_t is not None:
        peak = max(ops) if ops else 0
        for i in range(t.index(kill_t) + 1, len(ops)):
            if ops[i] > peak * 0.5:
                recov_t = t[i]
                break

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t, ops, "-", color="#2980b9", label="Throughput aggregato (ops/sec)")
    if kill_t is not None:
        ax.axvline(kill_t, color="#e74c3c", linestyle="--", linewidth=2,
                   label=f"Kill master (t={kill_t}s)")
    if recov_t is not None:
        ax.axvline(recov_t, color="#27ae60", linestyle="--", linewidth=2,
                   label=f"Recovery (t={recov_t}s) — downtime ~{recov_t - kill_t}s")
    ax.set_xlabel("Tempo (s)")
    ax.set_ylabel("Ops/sec (somma 6 nodi)")
    ax.set_title("Failover CON repliche — promozione automatica e downtime",
                 fontweight="bold")
    ax.legend()
    _save(fig, "expE_failover_replica.png")


if __name__ == "__main__":
    print(f"Carico dati Redis da {REDIS_DIR}")
    print(f"Output in {CHARTS}/")
    plot_exp_a()
    plot_exp_b()
    plot_exp_c()
    plot_exp_d()
    plot_exp_e()
    print("Fatto.")
