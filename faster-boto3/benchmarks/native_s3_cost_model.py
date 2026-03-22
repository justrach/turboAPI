#!/usr/bin/env python3
"""Simple latency model for the native FFI S3 spike.

The point of this file is not to fit a perfect model. It gives us a compact,
explicit way to reason about where the remaining time goes:

    total_latency ~= route_overhead + signer_cost + transport_cost + parse_cost

For the current data we only directly observe end-to-end latency, so this script
keeps the model intentionally simple and solves a few useful derived quantities:

- implied route service time from RPS
- incremental cost of body transfer by payload size
- incremental cost of list parsing vs head/get
- projected speedup if we reduce a chosen component by X%

Usage:
    python benchmarks/native_s3_cost_model.py
    python benchmarks/native_s3_cost_model.py --json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Measurement:
    name: str
    turbo_rps: float
    turbo_p99_ms: float
    fast_rps: float
    fast_p99_ms: float
    payload_bytes: int = 0
    list_items: int = 0

    @property
    def turbo_service_ms(self) -> float:
        return 1000.0 / self.turbo_rps

    @property
    def fast_service_ms(self) -> float:
        return 1000.0 / self.fast_rps

    @property
    def speedup(self) -> float:
        return self.fast_service_ms / self.turbo_service_ms


DATA = [
    Measurement("get_1k", turbo_rps=1312.98, turbo_p99_ms=30.16, fast_rps=1123.02, fast_p99_ms=253.44, payload_bytes=1024),
    Measurement("get_10k", turbo_rps=1309.42, turbo_p99_ms=64.65, fast_rps=1168.51, fast_p99_ms=249.66, payload_bytes=10 * 1024),
    Measurement("head", turbo_rps=1590.59, turbo_p99_ms=41.41, fast_rps=1406.85, fast_p99_ms=195.68),
    Measurement("list_20", turbo_rps=826.19, turbo_p99_ms=55.35, fast_rps=641.28, fast_p99_ms=494.12, list_items=20),
]


def find(name: str) -> Measurement:
    for row in DATA:
        if row.name == name:
            return row
    raise KeyError(name)


def solve_summary() -> dict[str, float | dict[str, float]]:
    head = find("head")
    get_1k = find("get_1k")
    get_10k = find("get_10k")
    list_20 = find("list_20")

    # Treat HEAD as the best proxy for the shared fixed path:
    # route dispatch + signer + socket reuse + round trip without payload parse.
    fixed_native_ms = head.turbo_service_ms

    # Estimate the extra cost of downloading additional bytes in the native path.
    extra_9k_ms = get_10k.turbo_service_ms - get_1k.turbo_service_ms
    bytes_delta = get_10k.payload_bytes - get_1k.payload_bytes
    transfer_cost_per_kb_ms = extra_9k_ms / (bytes_delta / 1024.0) if bytes_delta else 0.0

    # Estimate extra parse/serialization burden for list relative to head.
    list_extra_ms = list_20.turbo_service_ms - head.turbo_service_ms
    list_extra_per_item_ms = list_extra_ms / list_20.list_items if list_20.list_items else 0.0

    # Project what happens if we cut the fixed path or list-specific parse by half.
    projected_head_50pct_fixed = 1000.0 / (fixed_native_ms * 0.5)
    projected_list_50pct_parse = 1000.0 / (head.turbo_service_ms + list_extra_ms * 0.5)

    return {
        "fixed_native_ms_from_head": fixed_native_ms,
        "incremental_transfer_ms_per_kb": transfer_cost_per_kb_ms,
        "incremental_list_parse_ms_total": list_extra_ms,
        "incremental_list_parse_ms_per_item": list_extra_per_item_ms,
        "projected_rps": {
            "head_if_fixed_cost_halved": projected_head_50pct_fixed,
            "list_if_list_parse_halved": projected_list_50pct_parse,
        },
    }


def render_text() -> str:
    summary = solve_summary()
    lines = ["Native FFI Cost Model", ""]
    lines.append("Observed service time from throughput:")
    for row in DATA:
        lines.append(
            f"- {row.name}: turbo {row.turbo_service_ms:.3f} ms, "
            f"fast {row.fast_service_ms:.3f} ms, speedup {row.speedup:.2f}x"
        )
    lines.append("")
    lines.append("Derived estimates:")
    lines.append(f"- fixed native path from head: {summary['fixed_native_ms_from_head']:.3f} ms")
    lines.append(f"- incremental transfer cost: {summary['incremental_transfer_ms_per_kb']:.5f} ms/KB")
    lines.append(f"- incremental list parse total: {summary['incremental_list_parse_ms_total']:.3f} ms")
    lines.append(f"- incremental list parse per item: {summary['incremental_list_parse_ms_per_item']:.5f} ms/item")
    proj = summary["projected_rps"]
    lines.append("")
    lines.append("Counterfactual projections:")
    lines.append(f"- head RPS if fixed path is halved: {proj['head_if_fixed_cost_halved']:.1f}")
    lines.append(f"- list RPS if list parse is halved: {proj['list_if_list_parse_halved']:.1f}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = {
        "measurements": [asdict(row) | {
            "turbo_service_ms": row.turbo_service_ms,
            "fast_service_ms": row.fast_service_ms,
            "speedup": row.speedup,
        } for row in DATA],
        "summary": solve_summary(),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(render_text())


if __name__ == "__main__":
    main()
