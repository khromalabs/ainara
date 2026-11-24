#!/usr/bin/env python
"""Offline tests for date-window bounds, the vector recipe gate, and
native date-scoped semantic search (recipe v2 / timestamp_ts).

Covers the regression Dave reported on dev012-greenrevamp: a bare
"YYYY-MM-DD" end date excluded the whole day, and the semantic route
ignored date windows entirely.

Run: python scripts/test_vector_time_bounds.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ainara.framework.storage.sqlite import SQLiteStorage  # noqa: E402
from ainara.framework.storage.time_bounds import (  # noqa: E402
    resolve_date_bound,
    resolve_epoch_bound,
    timestamp_to_epoch,
)
from ainara.framework.storage.chroma import (  # noqa: E402
    ChromaVectorStorage,
)
from ainara.framework.vector_recipe import (  # noqa: E402
    is_current,
    mark_current,
    stale_reason,
)
from ainara.framework.chat_memory import ChatMemory  # noqa: E402


class TestResolveDateBound(unittest.TestCase):
    def test_bare_date_start_is_midnight(self):
        dt = resolve_date_bound("2026-11-23", is_end=False)
        self.assertEqual(
            dt, datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)
        )

    def test_bare_date_end_covers_whole_day(self):
        dt = resolve_date_bound("2026-11-23", is_end=True)
        self.assertEqual(
            dt,
            datetime(
                2026, 11, 23, 23, 59, 59, 999999, tzinfo=timezone.utc
            ),
        )

    def test_full_iso_with_offset(self):
        dt = resolve_date_bound("2026-11-23T09:31:05.123456+00:00")
        self.assertEqual(
            dt,
            datetime(
                2026, 11, 23, 9, 31, 5, 123456, tzinfo=timezone.utc
            ),
        )

    def test_full_iso_z_suffix(self):
        dt = resolve_date_bound("2026-11-23T09:31:05Z")
        self.assertEqual(dt.hour, 9)
        self.assertIsNotNone(dt.tzinfo)

    def test_naive_iso_assumed_utc(self):
        dt = resolve_date_bound("2026-11-23T09:31:05")
        self.assertEqual(dt.utcoffset().total_seconds(), 0)

    def test_unparseable_returns_none(self):
        self.assertIsNone(resolve_date_bound("not a date"))
        self.assertIsNone(resolve_date_bound("2026-13-45"))
        self.assertIsNone(resolve_date_bound(None))
        self.assertIsNone(resolve_date_bound(""))

    def test_epoch_bounds(self):
        start = resolve_epoch_bound("2026-11-23", is_end=False)
        end = resolve_epoch_bound("2026-11-23", is_end=True)
        self.assertLess(start, end)
        self.assertAlmostEqual(end - start, 86399.999999, delta=0.001)

    def test_timestamp_to_epoch(self):
        ts = "2026-11-23T09:31:05.123456+00:00"
        epoch = timestamp_to_epoch(ts)
        self.assertAlmostEqual(
            epoch,
            datetime(2026, 11, 23, 9, 31, 5, 123456, tzinfo=timezone.utc)
            .timestamp(),
            places=6,
        )
        self.assertIsNone(timestamp_to_epoch("unknown"))


class TestSqliteBareDateWindow(unittest.TestCase):
    """A one-day window (bare dates) must include the day's messages."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(
            db_path=os.path.join(self.tmpdir, "test.db"),
            context_id="persona-test",
        )
        for ts in [
            "2026-11-22T10:00:00.000000+00:00",
            "2026-11-23T00:00:01.000000+00:00",
            "2026-11-23T09:31:05.123456+00:00",
            "2026-11-23T23:59:59.000000+00:00",
            "2026-11-24T00:00:01.000000+00:00",
        ]:
            self.storage.add_message(
                content=f"msg {ts}", role="user", metadata={"timestamp": ts}
            )

    def tearDown(self):
        self.storage.close()

    def test_one_day_window_bare_dates(self):
        results = self.storage.search_text(
            include_terms=[],
            start_date="2026-11-23",
            end_date="2026-11-23",
        )
        contents = [r["content"] for r in results]
        self.assertEqual(len(results), 3, contents)
        self.assertTrue(all("2026-11-23T" in c for c in contents))

    def test_full_iso_window_still_works(self):
        results = self.storage.search_text(
            include_terms=[],
            start_date="2026-11-23T00:00:00+00:00",
            end_date="2026-11-23T23:59:59.999999+00:00",
        )
        self.assertEqual(len(results), 3)


class TestChromaWhereBuilder(unittest.TestCase):
    def _storage(self):
        return ChromaVectorStorage.__new__(ChromaVectorStorage)

    def test_no_bounds(self):
        s = self._storage()
        self.assertIsNone(s._combine_where(None, None, None))
        self.assertEqual(s._combine_where({"role": "user"}, None, None),
                         {"role": "user"})

    def test_single_bound(self):
        s = self._storage()
        self.assertEqual(
            s._combine_where(None, 100.0, None),
            {"timestamp_ts": {"$gte": 100.0}},
        )
        self.assertEqual(
            s._combine_where(None, None, 200.0),
            {"timestamp_ts": {"$lte": 200.0}},
        )

    def test_both_bounds_use_and(self):
        s = self._storage()
        self.assertEqual(
            s._combine_where(None, 100.0, 200.0),
            {"$and": [
                {"timestamp_ts": {"$gte": 100.0}},
                {"timestamp_ts": {"$lte": 200.0}},
            ]},
        )

    def test_filter_dict_combined_with_bounds(self):
        s = self._storage()
        self.assertEqual(
            s._combine_where({"role": "user"}, 100.0, 200.0),
            {"$and": [
                {"role": "user"},
                {"timestamp_ts": {"$gte": 100.0}},
                {"timestamp_ts": {"$lte": 200.0}},
            ]},
        )


class TestVectorRecipe(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_missing_marker_is_stale(self):
        self.assertFalse(is_current(self.tmpdir, "chat", "model-a"))
        self.assertIsNotNone(stale_reason(self.tmpdir, "chat", "model-a"))

    def test_mark_and_check_roundtrip(self):
        mark_current(self.tmpdir, "chat", "model-a")
        self.assertTrue(is_current(self.tmpdir, "chat", "model-a"))
        self.assertFalse(is_current(self.tmpdir, "profile", "model-a"))

    def test_model_change_is_stale(self):
        mark_current(self.tmpdir, "chat", "model-a")
        self.assertFalse(is_current(self.tmpdir, "chat", "model-b"))

    def test_families_independent(self):
        mark_current(self.tmpdir, "chat", "model-a")
        mark_current(self.tmpdir, "profile", "model-b")
        self.assertTrue(is_current(self.tmpdir, "chat", "model-a"))
        self.assertTrue(is_current(self.tmpdir, "profile", "model-b"))

    def test_marker_contents(self):
        mark_current(self.tmpdir, "chat", "model-a")
        with open(os.path.join(self.tmpdir, ".vector_recipe")) as f:
            data = json.load(f)
        self.assertEqual(data["recipe_version"], 2)
        self.assertEqual(data["models"]["chat"], "model-a")


class _FakeVector:
    """Records search kwargs; returns canned hits."""

    def __init__(self):
        self.calls = []

    def search(self, query, limit=5, filter_dict=None, start_ts=None,
               end_ts=None):
        self.calls.append(
            {"query": query, "limit": limit, "start_ts": start_ts,
             "end_ts": end_ts}
        )
        return [{"id": "1", "timestamp": "unknown", "role": "user",
                 "content": "hit", "metadata": {}}]


class _FakeTextStorage:
    """Records search_text calls (the non-semantic fallback route)."""

    def __init__(self):
        self.calls = []

    def search_text(self, **kwargs):
        self.calls.append(kwargs)
        return [{"id": "2", "timestamp": "2026-11-23T09:00:00+00:00",
                 "role": "user", "content": "row"}]


def _bare_chat_memory(vector, storage):
    """ChatMemory without __init__ (no config/backend wiring needed)."""
    cm = ChatMemory.__new__(ChatMemory)
    cm.vector_storage = vector
    cm.storage = storage
    return cm


class TestSearchEntriesSemanticRoute(unittest.TestCase):
    def test_semantic_route_passes_epoch_bounds(self):
        vec, txt = _FakeVector(), _FakeTextStorage()
        cm = _bare_chat_memory(vec, txt)
        results = cm.search_entries(
            "~test query",
            limit=5,
            start_date="2026-11-23",
            end_date="2026-11-23",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(txt.calls, [])  # text route untouched
        self.assertEqual(len(vec.calls), 1)
        call = vec.calls[0]
        self.assertEqual(call["query"], "test query")
        self.assertIsNotNone(call["start_ts"])
        self.assertIsNotNone(call["end_ts"])
        self.assertLess(call["start_ts"], call["end_ts"])

    def test_semantic_route_no_window(self):
        vec, txt = _FakeVector(), _FakeTextStorage()
        cm = _bare_chat_memory(vec, txt)
        cm.search_entries("~test query", limit=5)
        self.assertIsNone(vec.calls[0]["start_ts"])
        self.assertIsNone(vec.calls[0]["end_ts"])

    def test_unparseable_bound_falls_back_to_text_route(self):
        vec, txt = _FakeVector(), _FakeTextStorage()
        cm = _bare_chat_memory(vec, txt)
        results = cm.search_entries(
            "~test query", limit=5, end_date="not a date"
        )
        self.assertEqual(vec.calls, [])
        self.assertEqual(len(txt.calls), 1)
        self.assertEqual(len(results), 1)

    def test_semantic_route_query_prefix_stripped(self):
        vec, txt = _FakeVector(), _FakeTextStorage()
        cm = _bare_chat_memory(vec, txt)
        cm.search_entries("~what did we talk about", limit=5)
        self.assertEqual(
            vec.calls[0]["query"], "what did we talk about"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
