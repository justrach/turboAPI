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
    normalize: object = None


def compare_scenario(scenario, **kwargs):
    """Run one parity scenario and attach its identity to the compare report."""

    report = native_compare(scenario.run, **kwargs)
    if scenario.normalize is not None:
        if report["primary_error"] is None:
            report["primary_result"] = scenario.normalize(report["primary_result"])
        if report["native_error"] is None:
            report["native_result"] = scenario.normalize(report["native_result"])
        report["match"] = report["primary_error"] == report["native_error"] and report["primary_result"] == report["native_result"]
        report["kind"] = None if report["match"] else "result"
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


def core_parity_scenarios():
    """Starter scenario corpus for measuring client parity."""

    def normalize_stream_entries(entries):
        if not isinstance(entries, list):
            return entries
        normalized = []
        for item in entries:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict):
                normalized.append(("<stream-id>", item[1]))
            elif isinstance(item, list) and len(item) == 2 and isinstance(item[1], list):
                normalized.append([item[0], normalize_stream_entries(item[1])])
            else:
                normalized.append(item)
        return normalized

    return [
        ParityScenario("get-missing", lambda c: c.get("missing"), tags=("read", "string")),
        ParityScenario("set-basic", lambda c: c.set("k", "v"), tags=("write", "string")),
        ParityScenario("mset-basic", lambda c: c.mset({"a": "1", "b": "2"}), tags=("write", "string")),
        ParityScenario("exists", lambda c: (c.set("e", "1"), c.exists("e"))[-1], tags=("write", "read")),
        ParityScenario("hgetall", lambda c: (c.hset("h", mapping={"x": "1", "y": "2"}), c.hgetall("h"))[-1], tags=("hash",)),
        ParityScenario("client-id", lambda c: isinstance(c.client_id(), int), tags=("server",)),
        ParityScenario("acl-whoami", lambda c: c.acl_whoami(), tags=("acl",)),
        ParityScenario("acl-list", lambda c: c.acl_list(), tags=("acl",)),
        ParityScenario("acl-getuser", lambda c: c.acl_getuser("default"), tags=("acl",)),
        ParityScenario("config-get", lambda c: c.config_get("timeout"), tags=("server",)),
        ParityScenario(
            "config-set",
            lambda c: (lambda value: c.config_set("timeout", value))(c.config_get("timeout")["timeout"]),
            tags=("server", "config"),
        ),
        ParityScenario("config-resetstat", lambda c: c.config_resetstat(), tags=("server", "config")),
        ParityScenario("object-encoding", lambda c: (c.flushdb(), c.set("obj", "v"), c.object("ENCODING", "obj"))[-1], tags=("object",)),
        ParityScenario("object-refcount", lambda c: (c.flushdb(), c.set("obj", "v"), c.object("REFCOUNT", "obj"))[-1], tags=("object",)),
        ParityScenario("object-idletime", lambda c: (c.flushdb(), c.set("obj", "v"), isinstance(c.object("IDLETIME", "obj"), int))[-1], tags=("object",)),
        ParityScenario(
            "zrange-withscores",
            lambda c: (c.flushdb(), c.zadd("z", {"a": 1.5, "b": 2.0}), c.zrange("z", 0, -1, withscores=True))[-1],
            tags=("sorted-set",),
        ),
        ParityScenario(
            "zrange-desc",
            lambda c: (c.flushdb(), c.zadd("z", {"a": 1, "b": 2, "c": 3}), c.zrange("z", 0, 1, desc=True))[-1],
            tags=("sorted-set",),
        ),
        ParityScenario(
            "zrange-byscore-withscores",
            lambda c: (c.flushdb(), c.zadd("z", {"a": 1, "b": 2, "c": 3}), c.zrange("z", 1, 3, byscore=True, withscores=True))[-1],
            tags=("sorted-set",),
        ),
        ParityScenario(
            "geoadd-geopos",
            lambda c: (c.flushdb(), c.geoadd("geo", [-122.27652, 37.805186, "station:1"]), c.geopos("geo", "station:1"))[-1],
            tags=("geo",),
        ),
        ParityScenario(
            "pipeline-set-get",
            lambda c: (lambda p: [p.set("p", "1"), p.get("p"), p.execute()][-1])(c.pipeline()),
            tags=("pipeline",),
        ),
        ParityScenario(
            "pipeline-transaction",
            lambda c: (lambda p: [p.set("tx", "1"), p.get("tx"), p.execute()][-1])(c.pipeline(transaction=True)),
            tags=("pipeline", "transaction"),
        ),
        ParityScenario(
            "xrange",
            lambda c: (c.flushdb(), c.xadd("stream", {"field": "value"}), c.xrange("stream"))[-1],
            tags=("stream",),
            normalize=normalize_stream_entries,
        ),
        ParityScenario(
            "xgroup-read",
            lambda c: (
                c.flushdb(),
                c.xadd("stream", {"field": "value"}),
                c.xgroup_create("stream", "g1", id="0", mkstream=True),
                c.xreadgroup("g1", "c1", {"stream": ">"}, count=1),
            )[-1],
            tags=("stream", "group"),
            normalize=normalize_stream_entries,
        ),
    ]


def non_core_parity_scenarios():
    """Volatile or environment-sensitive parity scenarios kept outside the core score."""

    def normalize_client_list(rows):
        if not isinstance(rows, list):
            return rows
        normalized = []
        for row in rows:
            normalized.append(
                {
                    "db": row.get("db", ""),
                    "lib-name": row.get("lib-name", ""),
                    "lib-ver": row.get("lib-ver", ""),
                }
            )
        normalized.sort(key=lambda item: (item["db"], item["lib-name"], item["lib-ver"]))
        return normalized

    return [
        ParityScenario(
            "client-list-normalized",
            lambda c: (c.flushdb(), c.client_list())[-1],
            tags=("server", "non-core"),
            normalize=normalize_client_list,
            metadata={"reason": "volatile connection telemetry"},
        ),
    ]
