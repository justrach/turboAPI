#!/usr/bin/env python3
"""Tests for TurboAPI thread-safe Queue."""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

import pytest
from turboapi.queue import Queue, QueueEmpty, QueueFull


class TestQueueBasicOperations:

    def test_put_and_get(self):
        q = Queue()
        q.put("item1")
        q.put("item2")
        assert q.get() == "item1"
        assert q.get() == "item2"

    def test_fifo_order(self):
        q = Queue()
        for i in range(100):
            q.put(i)
        for i in range(100):
            assert q.get() == i

    def test_qsize(self):
        q = Queue()
        assert q.qsize() == 0
        q.put("a")
        assert q.qsize() == 1
        q.put("b")
        assert q.qsize() == 2
        q.get()
        assert q.qsize() == 1

    def test_empty(self):
        q = Queue()
        assert q.empty()
        q.put("a")
        assert not q.empty()

    def test_full_unbounded(self):
        q = Queue()
        for i in range(1000):
            q.put(i)
        assert not q.full()

    def test_full_bounded(self):
        q = Queue(maxsize=2)
        assert not q.full()
        q.put("a")
        assert not q.full()
        q.put("b")
        assert q.full()


class TestQueueNonBlocking:

    def test_get_nowait_empty_raises(self):
        q = Queue()
        with pytest.raises(QueueEmpty):
            q.get_nowait()

    def test_put_nowait_full_raises(self):
        q = Queue(maxsize=1)
        q.put("a")
        with pytest.raises(QueueFull):
            q.put_nowait("b")

    def test_get_nowait_succeeds(self):
        q = Queue()
        q.put("hello")
        assert q.get_nowait() == "hello"

    def test_put_nowait_succeeds(self):
        q = Queue(maxsize=1)
        q.put_nowait("a")
        assert q.get() == "a"


class TestQueueTimeout:

    def test_get_timeout_empty_raises(self):
        q = Queue()
        start = time.monotonic()
        with pytest.raises(QueueEmpty):
            q.get(timeout=0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09

    def test_put_timeout_full_raises(self):
        q = Queue(maxsize=1)
        q.put("a")
        start = time.monotonic()
        with pytest.raises(QueueFull):
            q.put("b", timeout=0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09

    def test_get_timeout_succeeds_when_item_arrives(self):
        q = Queue()

        def delayed_put():
            time.sleep(0.05)
            q.put("hello")

        t = threading.Thread(target=delayed_put)
        t.start()
        item = q.get(timeout=5.0)
        t.join()
        assert item == "hello"


class TestQueueThreadSafety:

    def test_concurrent_put_get(self):
        q = Queue()
        results = []
        lock = threading.Lock()

        def producer(start, end):
            for i in range(start, end):
                q.put(i)

        def consumer(count):
            local_results = []
            for _ in range(count):
                local_results.append(q.get(timeout=5.0))
            with lock:
                results.extend(local_results)

        producers = [threading.Thread(target=producer, args=(i * 250, (i + 1) * 250)) for i in range(4)]
        consumers = [threading.Thread(target=consumer, args=(250,)) for i in range(4)]

        for t in producers + consumers:
            t.start()
        for t in producers + consumers:
            t.join(timeout=10)

        assert sorted(results) == list(range(1000))

    def test_bounded_queue_blocks_producer(self):
        q = Queue(maxsize=1)
        q.put("first")
        put_done = threading.Event()

        def delayed_get():
            time.sleep(0.1)
            q.get()

        def blocked_put():
            q.put("second")
            put_done.set()

        consumer = threading.Thread(target=delayed_get)
        producer = threading.Thread(target=blocked_put)
        consumer.start()
        producer.start()
        producer.join(timeout=5)
        consumer.join(timeout=5)

        assert put_done.is_set()
        assert q.get() == "second"

    def test_consumer_blocks_until_producer(self):
        q = Queue()
        result = []

        def delayed_put():
            time.sleep(0.1)
            q.put("hello")

        def blocking_get():
            item = q.get(timeout=5.0)
            result.append(item)

        consumer = threading.Thread(target=blocking_get)
        producer = threading.Thread(target=delayed_put)
        consumer.start()
        producer.start()
        consumer.join(timeout=5)
        producer.join(timeout=5)

        assert result == ["hello"]


class TestQueueTaskDoneJoin:

    def test_task_done_and_join(self):
        q = Queue()
        q.put("a")
        q.put("b")
        results = []

        def worker():
            while True:
                try:
                    item = q.get(timeout=0.5)
                    results.append(item)
                    q.task_done()
                except QueueEmpty:
                    break

        t = threading.Thread(target=worker)
        t.start()
        q.join(timeout=5.0)
        t.join(timeout=5)

        assert sorted(results) == ["a", "b"]

    def test_task_done_too_many_raises(self):
        q = Queue()
        q.put("a")
        q.get()
        q.task_done()
        with pytest.raises(ValueError):
            q.task_done()


class TestQueueImport:

    def test_import_from_turboapi(self):
        from turboapi import Queue
        q = Queue()
        q.put("test")
        assert q.get() == "test"

    def test_import_exceptions(self):
        from turboapi import QueueEmpty, QueueFull
        assert issubclass(QueueEmpty, Exception)
        assert issubclass(QueueFull, Exception)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
