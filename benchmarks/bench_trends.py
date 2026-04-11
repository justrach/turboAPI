#!/usr/bin/env python3
"""
Trend analysis for benchmarks/history/ snapshots.

Usage:
    python benchmarks/bench_trends.py                    # show last 10 snapshots
    python benchmarks/bench_trends.py --all              # show all snapshots
    python benchmarks/bench_trends.py --compare 3         # compare last 3 snapshots
    python benchmarks/bench_trends.py --endpoint "GET /"  # filter to one endpoint
"""

import json
import os
import sys

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")


def load_snapshots(limit=None):
    if not os.path.exists(HISTORY_DIR):
        print("No history directory found. Run benchmarks with --history first.")
        return []

    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".json"))
    if limit:
        files = files[-limit:]

    snapshots = []
    for fname in files:
        with open(os.path.join(HISTORY_DIR, fname)) as f:
            data = json.load(f)
        snapshots.append(data)
    return snapshots


def print_table(snapshots, endpoint_filter=None):
    if not snapshots:
        print("No snapshots found.")
        return

    endpoints = set()
    for s in snapshots:
        endpoints.update(s.get("results", {}).keys())
    endpoints = sorted(endpoints)

    if endpoint_filter:
        endpoints = [e for e in endpoints if endpoint_filter.lower() in e.lower()]

    print(f"{'Timestamp':<22} {'Runner':<10} {'vCPUs':<6} ", end="")
    for ep in endpoints:
        short = ep.replace("GET ", "G:").replace("POST ", "P:")[:15]
        print(f"{short:>16}", end="")
    print(f" {'AVG':>10}")
    print("-" * (42 + 16 * len(endpoints) + 11))

    for s in snapshots:
        ts = s.get("timestamp", "unknown")[:19]
        runner = s.get("runner", "?")
        vcpus = s.get("vcpus", "?")
        results = s.get("results", {})
        print(f"{ts:<22} {runner:<10} {vcpus:<6} ", end="")
        vals = []
        for ep in endpoints:
            v = results.get(ep, 0)
            vals.append(v)
            print(f"{v:>15,.0f}", end="")
        avg = sum(vals) / max(len(vals), 1)
        print(f" {avg:>10,.0f}")


def print_delta(snapshots):
    if len(snapshots) < 2:
        print("Need at least 2 snapshots to compute delta.")
        return

    old = snapshots[-2]
    new = snapshots[-1]
    old_r = old.get("results", {})
    new_r = new.get("results", {})

    endpoints = sorted(set(old_r.keys()) | set(new_r.keys()))

    print(f"\n{'Endpoint':<25} {'Previous':>12} {'Current':>12} {'Delta':>10} {'%':>8}")
    print("-" * 70)
    for ep in endpoints:
        prev = old_r.get(ep, 0)
        curr = new_r.get(ep, 0)
        if prev == 0:
            delta_str = "N/A"
            pct_str = "N/A"
        else:
            delta = curr - prev
            pct = (delta / prev) * 100
            delta_str = f"{delta:+,.0f}"
            pct_str = f"{pct:+.1f}%"
        print(f"{ep:<25} {prev:>12,.0f} {curr:>12,.0f} {delta_str:>10} {pct_str:>8}")

    prev_avg = sum(old_r.values()) / max(len(old_r), 1)
    curr_avg = sum(new_r.values()) / max(len(new_r), 1)
    if prev_avg > 0:
        delta = curr_avg - prev_avg
        pct = (delta / prev_avg) * 100
        print(f"{'AVERAGE':<25} {prev_avg:>12,.0f} {curr_avg:>12,.0f} {delta:+,.0f} {pct:+.1f}%")
    else:
        print(f"{'AVERAGE':<25} {prev_avg:>12,.0f} {curr_avg:>12,.0f}")

    print(f"\n  Previous: {old.get('timestamp', '?')[:19]} ({old.get('runner', '?')})")
    print(f"  Current:  {new.get('timestamp', '?')[:19]} ({new.get('runner', '?')})")


def main():
    limit = 10
    compare = None
    endpoint_filter = None

    args = sys.argv[1:]
    if "--all" in args:
        limit = None
    if "--compare" in args:
        idx = args.index("--compare")
        if idx + 1 < len(args):
            compare = int(args[idx + 1])
        else:
            compare = 2
    if "--endpoint" in args:
        idx = args.index("--endpoint")
        if idx + 1 < len(args):
            endpoint_filter = args[idx + 1]

    if compare:
        snapshots = load_snapshots(limit=compare)
    else:
        snapshots = load_snapshots(limit=limit)

    if compare and len(snapshots) >= 2:
        print_delta(snapshots)
        print()
        print_table(snapshots, endpoint_filter)
    else:
        print_table(snapshots, endpoint_filter)


if __name__ == "__main__":
    main()
