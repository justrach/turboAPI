#!/usr/bin/env python3
"""Linear-algebra optimizer for S3 benchmark path selection.

This script does two things:

1. Chooses the best currently-measured path per operation.
2. Fits a small linear stage-cost model with ridge-regularized least squares so
   we can see which components are still worth attacking.

The fitted model is intentionally simple. The goal is not a perfect simulator;
the goal is to make path-choice and bottleneck claims explicit and falsifiable.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Measurement:
    op: str
    mode: str
    rps: float
    source: str

    @property
    def service_ms(self) -> float:
        return 1000.0 / self.rps


MEASUREMENTS = [
    # Current validated TurboAPI native-ffi run at wrk -t8 -c200 -d3s.
    Measurement("get_1k", "turbo_native_ffi", 1312.98, "validated_native_ffi_2026-03-23"),
    Measurement("get_10k", "turbo_native_ffi", 1309.42, "validated_native_ffi_2026-03-23"),
    Measurement("head", "turbo_native_ffi", 1590.59, "validated_native_ffi_2026-03-23"),
    Measurement("list_20", "turbo_native_ffi", 826.19, "validated_native_ffi_2026-03-23"),

    # Same validated run's FastAPI baseline.
    Measurement("get_1k", "fastapi_boto3", 1123.02, "paired_baseline_2026-03-23"),
    Measurement("get_10k", "fastapi_boto3", 1168.51, "paired_baseline_2026-03-23"),
    Measurement("head", "fastapi_boto3", 1406.85, "paired_baseline_2026-03-23"),
    Measurement("list_20", "fastapi_boto3", 641.28, "paired_baseline_2026-03-23"),

    # Last trusted TurboAPI + faster-boto3 snapshot before the benchmark regressed.
    Measurement("get_1k", "turbo_faster_boto3", 1527.0, "trusted_snapshot_t8_c200"),
    Measurement("get_10k", "turbo_faster_boto3", 1423.0, "trusted_snapshot_t8_c200"),
    Measurement("head", "turbo_faster_boto3", 1436.0, "trusted_snapshot_t8_c200"),
    Measurement("list_20", "turbo_faster_boto3", 1100.0, "trusted_snapshot_t8_c200"),
]

STAGES = [
    "shared_network",
    "payload_10k_extra",
    "list_parse_extra",
    "fastapi_framework",
    "botocore_stack",
    "turbo_python_framework",
    "faster_boto3_python_shim",
    "ffi_route_fixed",
]


def row_for(m: Measurement) -> list[float]:
    row = dict.fromkeys(STAGES, 0.0)
    row["shared_network"] = 1.0
    if m.op == "get_10k":
        row["payload_10k_extra"] = 1.0
    if m.op == "list_20":
        row["list_parse_extra"] = 1.0

    if m.mode == "fastapi_boto3":
        row["fastapi_framework"] = 1.0
        row["botocore_stack"] = 1.0
    elif m.mode == "turbo_faster_boto3":
        row["turbo_python_framework"] = 1.0
        row["faster_boto3_python_shim"] = 1.0
    elif m.mode == "turbo_native_ffi":
        row["ffi_route_fixed"] = 1.0
    else:
        raise KeyError(m.mode)
    return [row[stage] for stage in STAGES]


def transpose(a: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*a, strict=False)]


def matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    out = [[0.0 for _ in range(len(b[0]))] for _ in range(len(a))]
    for i in range(len(a)):
        for k in range(len(b)):
            aik = a[i][k]
            if aik == 0.0:
                continue
            for j in range(len(b[0])):
                out[i][j] += aik * b[k][j]
    return out


def matvec(a: list[list[float]], x: list[float]) -> list[float]:
    return [sum(ai * xi for ai, xi in zip(row, x, strict=False)) for row in a]


def solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(a)
    aug = [row[:] + [rhs] for row, rhs in zip(a, b, strict=False)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        piv = aug[col][col]
        if abs(piv) < 1e-12:
            raise ValueError("singular matrix")
        inv = 1.0 / piv
        for j in range(col, n + 1):
            aug[col][j] *= inv
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


def ridge_fit(xs: list[list[float]], ys: list[float], alpha: float = 1e-3) -> list[float]:
    xt = transpose(xs)
    xtx = matmul(xt, xs)
    for i in range(len(xtx)):
        xtx[i][i] += alpha
    xty = [sum(xt[row][col] * ys[col] for col in range(len(ys))) for row in range(len(xt))]
    return solve_linear(xtx, xty)


def best_mode_per_op() -> dict[str, dict[str, float | str]]:
    by_op: dict[str, list[Measurement]] = {}
    for m in MEASUREMENTS:
        by_op.setdefault(m.op, []).append(m)
    out: dict[str, dict[str, float | str]] = {}
    for op, rows in by_op.items():
        best = min(rows, key=lambda m: m.service_ms)
        out[op] = {
            "best_mode": best.mode,
            "best_service_ms": best.service_ms,
            "modes": {m.mode: m.service_ms for m in rows},
        }
    return out


def render() -> str:
    xs = [row_for(m) for m in MEASUREMENTS]
    ys = [m.service_ms for m in MEASUREMENTS]
    coeffs = ridge_fit(xs, ys)
    best = best_mode_per_op()

    lines = ["Native S3 Linear Optimizer", ""]
    lines.append("Best measured mode per operation:")
    for op in ("get_1k", "get_10k", "head", "list_20"):
        row = best[op]
        lines.append(
            f"- {op}: {row['best_mode']} at {row['best_service_ms']:.3f} ms "
            f"(choices: " +
            ", ".join(f"{mode}={ms:.3f} ms" for mode, ms in row["modes"].items()) +
            ")"
        )
    lines.append("")
    lines.append("Fitted stage costs (ridge least squares):")
    for stage, coef in zip(STAGES, coeffs, strict=False):
        lines.append(f"- {stage}: {coef:.5f} ms")
    lines.append("")
    lines.append("Interpretation:")
    lines.append("- If get/list stay on current measurements, the cheapest path is still op-specific rather than one global winner.")
    lines.append("- The fitted fixed-cost deltas separate FastAPI framework cost, Python shim cost, and FFI fixed route cost explicitly.")
    lines.append("- Use this as a selector and a ranking tool, not as a ground-truth physical model.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    xs = [row_for(m) for m in MEASUREMENTS]
    ys = [m.service_ms for m in MEASUREMENTS]
    coeffs = ridge_fit(xs, ys)
    best = best_mode_per_op()
    data = {
        "measurements": [
            asdict(m) | {"service_ms": m.service_ms}
            for m in MEASUREMENTS
        ],
        "stage_basis": STAGES,
        "stage_cost_ms": dict(zip(STAGES, coeffs, strict=False)),
        "best_mode_per_op": best,
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(render())


if __name__ == "__main__":
    main()
