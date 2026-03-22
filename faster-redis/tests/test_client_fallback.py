import os
import sys
import unittest

import redis


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from faster_redis._client import Redis


class ClientFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.redis_py = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        cls.faster = Redis()

    @classmethod
    def tearDownClass(cls):
        cls.faster.close()

    def setUp(self):
        self.redis_py.flushdb()
        self.faster.flushdb()

    def test_direct_multiword_command_mapping(self):
        self.assertIsInstance(self.faster.client_id(), int)

    def test_pipeline_multiword_command_mapping(self):
        with self.faster.pipeline() as pipe:
            pipe.client_id()
            results = pipe.execute()
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], int)

    def test_pipeline_object_refcount_mapping(self):
        with self.faster.pipeline() as pipe:
            pipe.set("k", "v")
            pipe.object_refcount("k")
            results = pipe.execute()
        self.assertEqual(results[0], True)
        self.assertIsInstance(results[1], int)

    def test_fallback_rejects_kwargs(self):
        rows = self.faster.client_list(_type="normal")
        self.assertIsInstance(rows, list)
        self.assertIsInstance(rows[0], dict)

        with self.assertRaises(TypeError):
            with self.faster.pipeline() as pipe:
                pipe.client_list(_type="normal")

    def test_execute_command_matches_raw_multiword_command(self):
        actual = self.faster.execute_command("CLIENT", "ID")
        self.assertIsInstance(actual, int)

    def test_set_and_mset_match_redis_py_semantics(self):
        self.assertIs(self.faster.set("set-key", "1"), True)
        self.assertIs(self.faster.mset({"a": "1", "b": "2"}), True)

    def test_pipeline_normalizes_ok_responses(self):
        with self.faster.pipeline() as pipe:
            pipe.set("p", "1")
            pipe.get("p")
            results = pipe.execute()
        self.assertEqual(results, [True, "1"])

    def test_zrange_withscores_matches_redis_py_shape(self):
        self.faster.zadd("z", {"a": 1.5, "b": 2.0})
        self.assertEqual(self.faster.zrange("z", 0, -1, withscores=True), [("a", 1.5), ("b", 2.0)])

    def test_client_list_returns_parsed_rows(self):
        rows = self.faster.client_list()
        self.assertIsInstance(rows, list)
        self.assertIsInstance(rows[0], dict)
        self.assertIn("id", rows[0])

    def test_geoadd_and_geopos_match_expected_shapes(self):
        self.assertEqual(self.faster.geoadd("geo", [-122.27652, 37.805186, "station:1"]), 1)
        pos = self.faster.geopos("geo", "station:1")
        self.assertEqual(len(pos), 1)
        self.assertIsInstance(pos[0], tuple)
        self.assertEqual(len(pos[0]), 2)

    def test_zrange_supports_desc_and_byscore(self):
        self.faster.zadd("z", {"a": 1, "b": 2, "c": 3})
        self.assertEqual(self.faster.zrange("z", 0, 1, desc=True), ["c", "b"])
        self.assertEqual(
            self.faster.zrange("z", 1, 3, byscore=True, withscores=True),
            [("a", 1.0), ("b", 2.0), ("c", 3.0)],
        )

    def test_config_get_returns_dict(self):
        result = self.faster.config_get("timeout")
        self.assertIsInstance(result, dict)
        self.assertIn("timeout", result)

    def test_stream_commands_match_expected_shapes(self):
        entry_id = self.faster.xadd("stream", {"field": "value"})
        self.assertIsInstance(entry_id, str)
        self.assertEqual(self.faster.xrange("stream"), [(entry_id, {"field": "value"})])
        self.assertIs(self.faster.xgroup_create("stream", "g1", id="0", mkstream=True), True)
        self.assertEqual(
            self.faster.xreadgroup("g1", "c1", {"stream": ">"}, count=1),
            [["stream", [(entry_id, {"field": "value"})]]],
        )

    def test_object_explicit_api_covers_more_subcommands(self):
        self.faster.set("obj", "v")
        self.assertEqual(self.faster.object("ENCODING", "obj"), "embstr")
        self.assertEqual(self.faster.object("REFCOUNT", "obj"), 1)
        self.assertIsInstance(self.faster.object("IDLETIME", "obj"), int)

    def test_acl_explicit_api_matches_redis_py_shapes(self):
        self.assertEqual(self.faster.acl_whoami(), "default")
        acl_list = self.faster.acl_list()
        self.assertIsInstance(acl_list, list)
        self.assertTrue(any(item.startswith("user default ") for item in acl_list))
        acl_user = self.faster.acl_getuser("default")
        self.assertIsInstance(acl_user, dict)
        self.assertEqual(acl_user["enabled"], True)
        self.assertIn("flags", acl_user)

    def test_config_set_and_resetstat_match_redis_py_semantics(self):
        timeout = self.faster.config_get("timeout")["timeout"]
        self.assertIs(self.faster.config_set("timeout", timeout), True)
        self.assertIs(self.faster.config_resetstat(), True)


if __name__ == "__main__":
    unittest.main()
