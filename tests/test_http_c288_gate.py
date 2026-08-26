"""Deterministic unit coverage for the c288 comparison gate."""

from scripts.benchmark_http_c288 import compare_runs, percentile


def _run(rps: float, p95: float, p99: float, errors: int = 0):
    return {
        "combined_rps": rps,
        "errors": errors,
        "foreground": {"p95_ms": p95, "p99_ms": p99},
    }


def test_percentile_uses_nearest_rank():
    assert percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 99) == 4.0


def test_c288_gate_accepts_metrics_within_ten_percent():
    result = compare_runs(
        [_run(1000, 100, 150), _run(1020, 102, 148)],
        [_run(920, 108, 160), _run(940, 110, 159)],
        max_regression_percent=10,
    )
    assert result["passed"]
    assert not result["failures"]


def test_c288_gate_reproduces_issue_219_failure():
    result = compare_runs(
        [_run(2522.32, 131.47, 171.37), _run(2522.32, 131.47, 171.37)],
        [_run(1997.45, 161.58, 250.97), _run(1997.45, 161.58, 250.97)],
        max_regression_percent=10,
    )
    assert not result["passed"]
    assert len(result["failures"]) == 3
    assert round(result["candidate_minus_control_percent"]["combined_rps_percent"], 2) == -20.81
    assert round(result["candidate_minus_control_percent"]["foreground_p95_percent"], 2) == 22.9
    assert round(result["candidate_minus_control_percent"]["foreground_p99_percent"], 2) == 46.45


def test_c288_gate_fails_on_any_response_error():
    result = compare_runs(
        [_run(1000, 100, 150)],
        [_run(1000, 100, 150, errors=1)],
        max_regression_percent=10,
    )
    assert not result["passed"]
    assert result["failures"] == ["HTTP or response-shape errors were observed"]
