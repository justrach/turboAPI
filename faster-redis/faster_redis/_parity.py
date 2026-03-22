"""Parity harness built on top of native_compare."""

from dataclasses import dataclass, field

from ._shadow import native_compare


@dataclass(frozen=True)
class ParityScenario:
    """Named scenario executed against redis-py and the native client."""

    name: str
    run: object
    tags: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


def compare_scenario(scenario, **kwargs):
    """Run one parity scenario and attach its identity to the compare report."""

    report = native_compare(scenario.run, **kwargs)
    report["name"] = scenario.name
    report["tags"] = list(scenario.tags)
    report["metadata"] = dict(scenario.metadata)
    return report


def run_parity_matrix(scenarios, **kwargs):
    """Run a list of scenarios and return both results and a compact summary."""

    results = [compare_scenario(scenario, **kwargs) for scenario in scenarios]
    summary = {
        "total": len(results),
        "matches": sum(1 for item in results if item["match"]),
        "mismatches": sum(1 for item in results if not item["match"]),
        "by_kind": {},
    }
    for item in results:
        kind = item["kind"] or "match"
        summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + 1
    return {"results": results, "summary": summary}
