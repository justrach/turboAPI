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
        with self.assertRaises(TypeError):
            self.faster.client_list(_type="normal")

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


if __name__ == "__main__":
    unittest.main()
