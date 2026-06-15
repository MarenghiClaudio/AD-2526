#!/usr/bin/env python3
"""
Genera grafici di benchmark dalle CSV di Locust prodotte da sweep.sh.

Dipendenze:  pip install pandas matplotlib numpy

Output: charts/  (PNG 150 dpi, pronti per documentazione Word/LaTeX).
"""

from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Percorsi ─────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent
RESULTS = ROOT / "results"
CHARTS  = ROOT / "charts"
CHARTS.mkdir(exist_ok=True)

# ── Strategie ─────────────────────────────────────────────────────────────────
STRATEGIES = ["no_cache", "cache_aside", "write_through", "push_feed", "hybrid"]
LABELS = {
    "no_cache":      "No Cache (baseline)",
    "cache_aside":   "Cache Aside",
    "write_through": "Write Through",
    "push_feed":     "Push Feed",
    "hybrid":        "Hybrid",
}
COLORS = {
    "no_cache":      "#e74c3c",
    "cache_aside":   "#3498db",
    "write_through": "#2ecc71",
    "push_feed":     "#f39c12",
    "hybrid":        "#9b59b6",
}
MARKERS = {
    "no_cache":      "o",
    "cache_aside":   "s",
    "write_through": "^",
    "push_feed":     "D",
    "hybrid":        "P",
}

# Endpoint mostrati nei grafici per-endpoint
KEY_ENDPOINTS = {
    "GET /timeline/{user_id}":           "GET /timeline",
    "GET /feed/{user_id}":               "GET /feed (FYP)",
    "GET /feed/{user_id}?with_fof=true": "GET /feed?with_fof",
    "GET /users/{user_id}":              "GET /users",
    "POST /posts":                        "POST /posts",
}

# ── Stile globale ─────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi":     150,
    "font.family":    "sans-serif",
    "font.size":      11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "legend.fontsize": 9,
    "axes.grid":      True,
    "grid.alpha":     0.35,
    "lines.linewidth": 2,
    "lines.markersize": 7,
})

# ── Caricamento dati ──────────────────────────────────────────────────────────
# Greedy su [a-z_]+ così write_through, cache_aside ecc. sono catturati interi
_PAT = re.compile(r"^([a-z_]+)_(\d+)u_stats\.csv$")

def load_all() -> pd.DataFrame:
    frames = []
    for f in sorted(RESULTS.glob("*_stats.csv")):
        m = _PAT.match(f.name)
        if not m:
            continue
        strategy, users = m.group(1), int(m.group(2))
        if strategy not in STRATEGIES:
            continue
        df = pd.read_csv(f)
        df["strategy"] = strategy
        df["users"]    = users
        df["endpoint"] = df["Type"].str.strip() + " " + df["Name"].str.strip()
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"Nessun *_Xu_stats.csv trovato in {RESULTS}")
    return pd.concat(frames, ignore_index=True)

# ── Helper ────────────────────────────────────────────────────────────────────
def _save(fig, name: str):
    path = CHARTS / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path.name}")

# ── 1. Quattro grafici aggregati separati ─────────────────────────────────────
def plot_aggregated(df: pd.DataFrame):
    agg = df[df["Name"].str.strip() == "Aggregated"].copy()
    agg["fail_pct"] = (
        agg["Failure Count"] / agg["Request Count"].replace(0, np.nan) * 100
    ).fillna(0)

    panels = [
        ("Requests/s", "Throughput (req/s)",  "throughput_vs_users.png"),
        ("50%",        "Latenza mediana (ms)", "p50_vs_users.png"),
        ("99%",        "Latenza p99 (ms)",     "p99_vs_users.png"),
        ("fail_pct",   "Failure rate (%)",     "failure_rate_vs_users.png"),
    ]
    for col, ylabel, fname in panels:
        fig, ax = plt.subplots(figsize=(8, 5))
        for s in STRATEGIES:
            sub = agg[agg["strategy"] == s].sort_values("users")
            if sub.empty:
                continue
            ax.plot(sub["users"], sub[col],
                    label=LABELS[s], color=COLORS[s], marker=MARKERS[s])
        ax.set_xlabel("Utenti concorrenti")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{ylabel} — confronto strategie")
        ax.legend(loc="best")
        _save(fig, fname)

# ── 2. Dashboard 2×2 ──────────────────────────────────────────────────────────
def plot_dashboard(df: pd.DataFrame):
    agg = df[df["Name"].str.strip() == "Aggregated"].copy()
    agg["fail_pct"] = (
        agg["Failure Count"] / agg["Request Count"].replace(0, np.nan) * 100
    ).fillna(0)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Benchmark — confronto strategie di caching", fontsize=15, fontweight="bold")

    panels = [
        (axes[0, 0], "Requests/s", "Throughput (req/s)"),
        (axes[0, 1], "50%",        "Latenza mediana (ms)"),
        (axes[1, 0], "99%",        "Latenza p99 (ms)"),
        (axes[1, 1], "fail_pct",   "Failure rate (%)"),
    ]
    for ax, col, title in panels:
        for s in STRATEGIES:
            sub = agg[agg["strategy"] == s].sort_values("users")
            if sub.empty:
                continue
            ax.plot(sub["users"], sub[col],
                    label=LABELS[s], color=COLORS[s], marker=MARKERS[s])
        ax.set_title(title)
        ax.set_xlabel("Utenti concorrenti")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.35)

    fig.tight_layout()
    _save(fig, "dashboard.png")

# ── 3. p50 + p99 per endpoint chiave ─────────────────────────────────────────
def plot_per_endpoint(df: pd.DataFrame):
    for ep_key, ep_label in KEY_ENDPOINTS.items():
        sub = df[df["endpoint"] == ep_key]
        if sub.empty:
            continue

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
        fig.suptitle(f"Endpoint: {ep_label}", fontsize=13, fontweight="bold")

        for ax, col, title in [(ax1, "50%", "p50 (ms)"), (ax2, "99%", "p99 (ms)")]:
            for s in STRATEGIES:
                s_df = sub[sub["strategy"] == s].sort_values("users")
                if s_df.empty:
                    continue
                ax.plot(s_df["users"], s_df[col],
                        label=LABELS[s], color=COLORS[s], marker=MARKERS[s])
            ax.set_title(title)
            ax.set_xlabel("Utenti concorrenti")
            ax.set_ylabel("ms")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.35)

        fig.tight_layout()
        safe = re.sub(r"[^a-z0-9]+", "_", ep_key.lower()).strip("_")
        _save(fig, f"endpoint_{safe}.png")

# ── 4. Heatmap p99 a 100 utenti ──────────────────────────────────────────────
def plot_heatmap(df: pd.DataFrame, target_users: int = 100):
    sub = df[
        (df["users"] == target_users) &
        (df["endpoint"].isin(KEY_ENDPOINTS))
    ].copy()
    if sub.empty:
        print(f"  [heatmap] nessun dato per {target_users} utenti, skip.")
        return

    pivot = (
        sub.pivot_table(index="endpoint", columns="strategy", values="99%", aggfunc="mean")
           .reindex(index=list(KEY_ENDPOINTS), columns=STRATEGIES)
    )
    pivot.dropna(how="all", inplace=True)
    if pivot.empty:
        return

    fig, ax = plt.subplots(figsize=(11, 4))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([LABELS[c] for c in pivot.columns], rotation=20, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([KEY_ENDPOINTS.get(e, e) for e in pivot.index])
    plt.colorbar(im, ax=ax, label="p99 (ms)")
    ax.set_title(f"Heatmap p99 — {target_users} utenti concorrenti")

    vmax = np.nanmax(pivot.values)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            if not np.isnan(v):
                color = "white" if v > vmax * 0.55 else "black"
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=9, color=color)

    fig.tight_layout()
    _save(fig, f"heatmap_p99_{target_users}u.png")

# ── 5. Boxplot RPS per strategia (a tutti i carichi) ─────────────────────────
def plot_rps_boxplot(df: pd.DataFrame):
    agg = df[df["Name"].str.strip() == "Aggregated"].copy()
    data  = [agg[agg["strategy"] == s]["Requests/s"].dropna().values for s in STRATEGIES]
    labels = [LABELS[s] for s in STRATEGIES]
    colors = [COLORS[s] for s in STRATEGIES]

    fig, ax = plt.subplots(figsize=(9, 5))
    bp = ax.boxplot(data, patch_artist=True, tick_labels=labels)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.7)
    ax.set_ylabel("Throughput (req/s)")
    ax.set_title("Distribuzione throughput — tutti i carichi testati")
    plt.xticks(rotation=15, ha="right")
    _save(fig, "rps_boxplot.png")

# ── 6. Analisi requests.log (db_ms, cache_ms, hit ratio) ─────────────────────
def load_request_logs() -> pd.DataFrame:
    """Legge tutti i *_requests.log e ritorna un DataFrame con db_ms, cache_ms, cache_hit."""
    frames = []
    for f in sorted(RESULTS.glob("*_requests.log")):
        m = _PAT.match(f.name.replace("_requests.log", "_stats.csv"))
        if not m:
            # prova pattern diretto sul nome del log
            m2 = re.match(r"^([a-z_]+)_(\d+)u_requests\.log$", f.name)
            if not m2:
                continue
            strategy, users = m2.group(1), int(m2.group(2))
        else:
            strategy, users = m.group(1), int(m.group(2))
        if strategy not in STRATEGIES:
            continue
        try:
            df = pd.read_json(f, lines=True)
            df["strategy"] = strategy
            df["users"] = users
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

def plot_timing_breakdown(logs: pd.DataFrame):
    """db_ms mediano vs utenti per strategia."""
    grp = logs.groupby(["strategy", "users"])[["db_ms", "cache_ms", "total_ms"]].median().reset_index()

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Breakdown tempi per request (mediana)", fontsize=13, fontweight="bold")

    for ax, col, title in [
        (axes[0], "db_ms",    "DB time mediano (ms)"),
        (axes[1], "cache_ms", "Cache time mediano (ms)"),
        (axes[2], "total_ms", "Total time mediano (ms)"),
    ]:
        for s in STRATEGIES:
            sub = grp[grp["strategy"] == s].sort_values("users")
            if sub.empty:
                continue
            ax.plot(sub["users"], sub[col],
                    label=LABELS[s], color=COLORS[s], marker=MARKERS[s])
        ax.set_title(title)
        ax.set_xlabel("Utenti concorrenti")
        ax.set_ylabel("ms")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.35)

    fig.tight_layout()
    _save(fig, "timing_breakdown.png")

def plot_db_ratio(logs: pd.DataFrame):
    """Rapporto db_ms/total_ms — se alto, bottleneck è il DB."""
    logs = logs[logs["total_ms"] > 0].copy()
    logs["db_ratio"] = logs["db_ms"] / logs["total_ms"]
    grp = logs.groupby(["strategy", "users"])["db_ratio"].median().reset_index()

    fig, ax = plt.subplots(figsize=(9, 5))
    for s in STRATEGIES:
        sub = grp[grp["strategy"] == s].sort_values("users")
        if sub.empty:
            continue
        ax.plot(sub["users"], sub["db_ratio"] * 100,
                label=LABELS[s], color=COLORS[s], marker=MARKERS[s])
    ax.axhline(50, color="gray", linestyle="--", linewidth=1, label="50% (soglia)")
    ax.set_xlabel("Utenti concorrenti")
    ax.set_ylabel("db_ms / total_ms (%)")
    ax.set_title("Quota DB sul tempo totale — >50% = bottleneck DB")
    ax.legend(fontsize=8)
    _save(fig, "db_ratio.png")

def plot_cache_hit_ratio(logs: pd.DataFrame):
    """Hit ratio Redis per strategia al variare del carico."""
    reads = logs[logs["cache_hit"].notna()].copy()
    grp = reads.groupby(["strategy", "users"])["cache_hit"].mean().reset_index()
    grp["hit_pct"] = grp["cache_hit"] * 100

    fig, ax = plt.subplots(figsize=(9, 5))
    for s in STRATEGIES:
        sub = grp[grp["strategy"] == s].sort_values("users")
        if sub.empty:
            continue
        ax.plot(sub["users"], sub["hit_pct"],
                label=LABELS[s], color=COLORS[s], marker=MARKERS[s])
    ax.set_xlabel("Utenti concorrenti")
    ax.set_ylabel("Cache hit ratio (%)")
    ax.set_title("Cache hit ratio per strategia")
    ax.set_ylim(0, 105)
    ax.legend(fontsize=8)
    _save(fig, "cache_hit_ratio.png")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Carico dati da {RESULTS} ...")
    df = load_all()

    strats  = sorted(df["strategy"].unique())
    users   = sorted(df["users"].unique())
    print(f"  Strategie: {strats}")
    print(f"  Carichi:   {users}\n")
    print(f"Output in {CHARTS}/")

    plot_aggregated(df)
    plot_dashboard(df)
    plot_per_endpoint(df)
    plot_heatmap(df, target_users=100)
    plot_rps_boxplot(df)

    logs = load_request_logs()
    if not logs.empty:
        print(f"\n  Request logs trovati: {len(logs):,} righe")
        plot_timing_breakdown(logs)
        plot_db_ratio(logs)
        plot_cache_hit_ratio(logs)
    else:
        print("\n  Nessun *_requests.log trovato — grafici timing skippati.")

    print("\nFatto.")
