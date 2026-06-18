#!/usr/bin/env python3
"""
compare_results.py
Confronta i CSV prodotti da benchmark_runner.py e stampa tabelle comparative.

Uso:
    python compare_results.py              # legge backend/results/
    python compare_results.py <cartella>   # cartella custom
"""

import csv
import sys
from pathlib import Path

RESULTS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backend/results")

ENDPOINTS = [
    "/feed/{user_id}",
    "/feed/{user_id}?with_fof=true",
    "/timeline/{user_id}",
    "/users/{user_id}",
    "/posts",
    "/likes",
    "Aggregated",
]

# (colonna CSV, etichetta, decimali, lower_is_better)
METRICS = [
    ("50%",                    "p50 ms",   0, True),
    ("95%",                    "p95 ms",   0, True),
    ("99%",                    "p99 ms",   0, True),
    ("Average Response Time",  "avg ms",   0, True),
    ("Requests/s",             "req/s",    1, False),
    ("Failure Count",          "failures", 0, True),
]


def load(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return {row["Name"]: row for row in csv.DictReader(f)}


def fmt(val: str, decimals: int) -> str:
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "—"


def print_metric_table(
    metric_col: str,
    label: str,
    decimals: int,
    lower_is_better: bool,
    strategies: list[str],
    data: dict[str, dict],
) -> None:
    ep_w = max(len(ep) for ep in ENDPOINTS) + 2
    col_w = 14
    divider = "  " + "─" * (ep_w + col_w * len(strategies))

    print(f"\n  ┌─ {label} {'─' * max(0, 56 - len(label))}┐")
    header = f"  │ {'Endpoint':<{ep_w}}" + "".join(f"{s:>{col_w}}" for s in strategies) + " │"
    print(header)
    print(divider)

    for ep in ENDPOINTS:
        values = [data.get(s, {}).get(ep, {}).get(metric_col, "") for s in strategies]
        nums = []
        for v in values:
            try:
                nums.append(float(v))
            except (ValueError, TypeError):
                nums.append(None)

        best = None
        valid = [n for n in nums if n is not None]
        if valid:
            best = min(valid) if lower_is_better else max(valid)

        row = f"  │ {ep:<{ep_w}}"
        for i, (raw, num) in enumerate(zip(values, nums)):
            cell = fmt(raw, decimals)
            marker = " *" if (num is not None and num == best and len(valid) > 1) else "  "
            row += f"{cell:>{col_w - 2}}{marker}"
        row += " │"
        print(row)

    print(f"  └{'─' * (ep_w + col_w * len(strategies) + 2)}┘")
    print("    * = migliore per questo endpoint")


def print_summary(strategies: list[str], data: dict[str, dict]) -> None:
    agg_label = "Aggregated"
    col_w = 10
    row_label_w = 12

    print(f"\n  ┌─ RANKING AGGREGATO {'─' * 40}┐")
    header = f"  │ {'Strategia':<20}" + "".join(
        f"{'p50':>{col_w}}{'p95':>{col_w}}{'req/s':>{col_w}}{'fail':>{col_w}}"
    ) + " │"
    print(header)
    print(f"  │ {'':20}" + "".join(
        f"{'ms':>{col_w}}{'ms':>{col_w}}{'':>{col_w}}{'':>{col_w}}"
    ) + " │")
    print("  " + "─" * (20 + col_w * 4 + 4))

    rows = []
    for s in strategies:
        agg = data.get(s, {}).get(agg_label, {})
        p50  = float(agg.get("50%", 0) or 0)
        p95  = float(agg.get("95%", 0) or 0)
        rps  = float(agg.get("Requests/s", 0) or 0)
        fail = int(float(agg.get("Failure Count", 0) or 0))
        rows.append((s, p50, p95, rps, fail))

    rows.sort(key=lambda r: r[1])  # ordina per p50 crescente

    for rank, (s, p50, p95, rps, fail) in enumerate(rows, 1):
        medal = ["🥇", "🥈", "🥉", "  "][min(rank - 1, 3)]
        fail_str = str(fail) if fail else "—"
        print(
            f"  │ {medal} {s:<17}"
            f"{p50:>{col_w}.0f}{p95:>{col_w}.0f}{rps:>{col_w}.1f}{fail_str:>{col_w}} │"
        )

    print(f"  └{'─' * (20 + col_w * 4 + 4)}┘")


def main() -> None:
    csv_files = sorted(RESULTS_DIR.glob("*_stats.csv"))
    if not csv_files:
        print(f"\nNessun file *_stats.csv trovato in {RESULTS_DIR}")
        print("Avvia prima: python benchmark_runner.py")
        sys.exit(1)

    strategies = [f.stem.replace("_stats", "") for f in csv_files]
    data = {s: load(f) for s, f in zip(strategies, csv_files)}

    print(f"\n{'═' * 70}")
    print(f"  CONFRONTO BENCHMARK")
    print(f"  Cartella : {RESULTS_DIR}")
    print(f"  Strategie: {', '.join(strategies)}")
    print(f"{'═' * 70}")

    for metric_col, label, decimals, lower_is_better in METRICS:
        print_metric_table(metric_col, label, decimals, lower_is_better, strategies, data)

    print_summary(strategies, data)
    print()


if __name__ == "__main__":
    main()
