import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "bench_regression.py"
SPEC = importlib.util.spec_from_file_location("bench_regression", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bench_regression = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench_regression)


def configure_artifact_paths(monkeypatch, tmp_path):
    history_dir = tmp_path / "history"
    monkeypatch.setattr(bench_regression, "BASELINE_FILE", str(tmp_path / "baseline.json"))
    monkeypatch.setattr(bench_regression, "RESULTS_FILE", str(tmp_path / "results.json"))
    monkeypatch.setattr(bench_regression, "HISTORY_DIR", str(history_dir))
    return history_dir


def test_main_strict_regression_preserves_baseline_and_records_history(monkeypatch, tmp_path):
    history_dir = configure_artifact_paths(monkeypatch, tmp_path)
    baseline_path = Path(bench_regression.BASELINE_FILE)
    previous_baseline = {name: 150_000.0 for name, *_ in bench_regression.BENCHMARKS}
    baseline_path.write_text(json.dumps(previous_baseline))
    thresholds_path = tmp_path / "thresholds.json"
    thresholds_path.write_text(
        json.dumps(
            {
                "margin_pct": 10,
                "average_threshold_rps": 0,
                "endpoints": {},
                "ci": {
                    "average_threshold_rps": 0,
                    "endpoints": {
                        name: {"min_rps": 1} for name, *_ in bench_regression.BENCHMARKS
                    },
                },
            }
        )
    )
    monkeypatch.setattr(bench_regression, "THRESHOLDS_FILE", str(thresholds_path))

    class StubProcess:
        def kill(self):
            pass

        def wait(self):
            pass

    class StubPipe:
        def read(self):
            return "test-commit\n"

    monkeypatch.setattr(bench_regression.subprocess, "Popen", lambda *args, **kwargs: StubProcess())
    monkeypatch.setattr(bench_regression.os, "popen", lambda *args, **kwargs: StubPipe())
    monkeypatch.setattr(bench_regression, "run_wrk", lambda *args, **kwargs: {
        "requests_per_second": 100_000.0,
        "latency_avg_ms": 0.1,
        "latency_p99_ms": 0.2,
    })
    monkeypatch.setattr(bench_regression.time, "sleep", lambda _: None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        sys,
        "argv",
        ["bench_regression.py", "--save", "--history", "--fail-on-regression"],
    )

    with pytest.raises(SystemExit, match="1"):
        bench_regression.main()

    assert json.loads(baseline_path.read_text()) == previous_baseline
    snapshots = list(history_dir.glob("*.json"))
    assert len(snapshots) == 1
    assert set(json.loads(snapshots[0].read_text())["results"].values()) == {100_000.0}


def test_passing_strict_run_updates_baseline(monkeypatch, tmp_path):
    configure_artifact_paths(monkeypatch, tmp_path)
    baseline_path = Path(bench_regression.BASELINE_FILE)
    baseline_path.write_text(json.dumps({"GET /health": 100_000.0}))

    results = {"GET /health": 150_000.0}
    bench_regression.persist_benchmark_artifacts(
        results,
        {},
        save_mode=True,
        history_mode=False,
        protect_baseline=False,
    )

    assert json.loads(baseline_path.read_text()) == results
