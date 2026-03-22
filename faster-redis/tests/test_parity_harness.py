import os
import sys
import unittest

import redis


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from faster_redis import ParityScenario, compare_scenario, run_parity_matrix


class ParityHarnessTests(unittest.TestCase):
    def setUp(self):
        self.primary_db = 11
        self.shadow_db = 12
        self.primary = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=self.primary_db,
            decode_responses=True,
        )
        self.shadow = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=self.shadow_db,
            decode_responses=True,
        )
        self.primary.flushdb()
        self.shadow.flushdb()

    def tearDown(self):
        self.primary.flushdb()
        self.shadow.flushdb()
        self.primary.close()
        self.shadow.close()

    def test_compare_scenario_attaches_identity(self):
        scenario = ParityScenario(
            name="missing-get",
            run=lambda client: client.get("missing"),
            tags=("read", "string"),
            metadata={"family": "strings"},
        )
        report = compare_scenario(
            scenario,
            db=self.primary_db,
            shadow_db=self.shadow_db,
        )
        self.assertTrue(report["match"])
        self.assertEqual(report["name"], "missing-get")
        self.assertEqual(report["tags"], ["read", "string"])
        self.assertEqual(report["metadata"], {"family": "strings"})

    def test_run_parity_matrix_summarizes_results(self):
        scenarios = [
            ParityScenario(
                name="missing-get",
                run=lambda client: client.get("missing"),
                tags=("read",),
            ),
            ParityScenario(
                name="set-basic",
                run=lambda client: client.set("key", "1"),
                tags=("write",),
            ),
        ]
        report = run_parity_matrix(
            scenarios,
            db=self.primary_db,
            shadow_db=self.shadow_db,
        )
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["matches"], 2)
        self.assertEqual(report["summary"]["mismatches"], 0)
        self.assertEqual(report["summary"]["by_kind"]["match"], 2)
        self.assertEqual(
            [item["name"] for item in report["results"]],
            ["missing-get", "set-basic"],
        )


if __name__ == "__main__":
    unittest.main()
