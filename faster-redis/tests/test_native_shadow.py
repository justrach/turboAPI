import os
import sys
import unittest

import redis


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from faster_redis import NativeShadowMismatch, native_compare, native_shadow


class NativeShadowTests(unittest.TestCase):
    def setUp(self):
        self.primary_db = 13
        self.shadow_db = 14
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

    def test_requires_isolated_shadow_target_by_default(self):
        with self.assertRaises(ValueError):
            native_shadow(db=self.primary_db, shadow_db=self.primary_db)

    def test_returns_primary_result_and_mirrors_state(self):
        mismatches = []
        client = native_shadow(
            db=self.primary_db,
            shadow_db=self.shadow_db,
            on_mismatch=mismatches.append,
        )
        try:
            result = client.get("missing")
            self.assertIsNone(result)

            client.set("alpha", "1")
            self.assertEqual(self.primary.get("alpha"), "1")
            self.assertEqual(self.shadow.get("alpha"), "1")
        finally:
            client.close()

        self.assertEqual(mismatches, [])

    def test_pipeline_compares_results(self):
        mismatches = []
        client = native_shadow(
            db=self.primary_db,
            shadow_db=self.shadow_db,
            on_mismatch=mismatches.append,
        )
        try:
            with client.pipeline() as pipe:
                pipe.set("a", "1")
                pipe.get("a")
                results = pipe.execute()
        finally:
            client.close()

        self.assertEqual(results, [True, "1"])
        self.assertEqual(mismatches, [])

    def test_strict_mode_raises_on_mismatch(self):
        client = native_shadow(
            db=self.primary_db,
            shadow_db=self.shadow_db,
            strict=True,
        )
        try:
            self.assertIs(client.set("strict-key", "1"), True)
        finally:
            client.close()

    def test_native_compare_matches_missing_get(self):
        report = native_compare(
            lambda client: client.get("missing"),
            db=self.primary_db,
            shadow_db=self.shadow_db,
        )
        self.assertTrue(report["match"])
        self.assertIsNone(report["primary_result"])
        self.assertIsNone(report["native_result"])

    def test_native_compare_matches_set_after_response_normalization(self):
        report = native_compare(
            lambda client: client.set("cmp-key", "1"),
            db=self.primary_db,
            shadow_db=self.shadow_db,
        )
        self.assertTrue(report["match"])
        self.assertIsNone(report["kind"])
        self.assertEqual(report["primary_result"], True)
        self.assertEqual(report["native_result"], True)

    def test_strict_mode_still_raises_on_real_mismatch(self):
        client = native_shadow(
            db=self.primary_db,
            shadow_db=self.shadow_db,
            strict=True,
        )
        try:
            with self.assertRaises(NativeShadowMismatch):
                client.client_list(_type="normal")
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
