#!/usr/bin/env python
"""Offline tests for date-window bounds, the vector recipe gate, native
date-scoped semantic search (recipe v2/v3), and Deep Recall's windowed
memory tools.

Covers the regressions Dave reported on dev012-greenrevamp (a bare
"YYYY-MM-DD" end date excluded the whole day; the semantic route
ignored date windows) and the period-recall tooling added afterwards.

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
    FAMILY_RECIPES,
    is_current,
    mark_current,
    stale_reason,
)
from ainara.framework.chat_memory import ChatMemory  # noqa: E402
from ainara.framework.deep_recall import (  # noqa: E402
    DeepRecallEngine,
    _memory_top_k,
)


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

    def test_ts_key_selects_metadata_field(self):
        """Memories filter on created_ts, not timestamp_ts."""
        s = self._storage()
        self.assertEqual(
            s._combine_where(None, 100.0, 200.0, ts_key="created_ts"),
            {"$and": [
                {"created_ts": {"$gte": 100.0}},
                {"created_ts": {"$lte": 200.0}},
            ]},
        )
        self.assertEqual(
            s._date_where_clauses(100.0, None, ts_key="updated_ts"),
            [{"updated_ts": {"$gte": 100.0}}],
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
        self.assertEqual(data["recipes"]["chat"], FAMILY_RECIPES["chat"])
        self.assertEqual(data["models"]["chat"], "model-a")

    def test_legacy_v2_marker_compat(self):
        """Pre-v3 markers carried a single global recipe_version=2: the
        chat schema did not change since, so chat stays current, while
        the profile family reads as stale (it needs the v3 epoch
        mirrors) and will rebuild once."""
        with open(os.path.join(self.tmpdir, ".vector_recipe"), "w") as f:
            json.dump({
                "recipe_version": 2,
                "models": {"chat": "model-a", "profile": "model-a"},
            }, f)
        self.assertTrue(is_current(self.tmpdir, "chat", "model-a"))
        self.assertFalse(is_current(self.tmpdir, "profile", "model-a"))

    def test_profile_needs_v3(self):
        """A v2-era chat-only marker must not satisfy the profile
        family even after marking chat current."""
        mark_current(self.tmpdir, "chat", "model-a")
        self.assertFalse(is_current(self.tmpdir, "profile", "model-a"))
        mark_current(self.tmpdir, "profile", "model-a")
        self.assertTrue(is_current(self.tmpdir, "profile", "model-a"))


class TestMemoryTopK(unittest.TestCase):
    """GREEN's context-window tiers with a hard ceiling, clamped to
    the window's density."""

    def test_tiers_follow_context_window(self):
        self.assertEqual(_memory_top_k(2048, 500), 6)
        self.assertEqual(_memory_top_k(8000, 500), 10)
        self.assertEqual(_memory_top_k(32768, 500), 15)
        # Hard ceiling: even a 1M-context model gets 20.
        self.assertEqual(_memory_top_k(1_000_000, 500), 20)

    def test_clamped_to_window_density(self):
        self.assertEqual(_memory_top_k(32768, 5), 5)
        self.assertEqual(_memory_top_k(1_000_000, 0), 0)
        self.assertEqual(_memory_top_k(32768, 12), 12)


class _StubGreen:
    """Records get_relevant_memories kwargs; returns canned hits."""

    def __init__(self, candidates=266, hits=None):
        self.candidates = candidates
        self.calls = []
        self.hits = hits or []

    def count_memories_in_window(self, start_date=None, end_date=None):
        return self.candidates

    def get_relevant_memories(self, query, top_k=None, start_date=None,
                              end_date=None, **kwargs):
        self.calls.append({
            "query": query, "top_k": top_k,
            "start_date": start_date, "end_date": end_date,
        })
        return self.hits


class _StubChatMemory:
    def __init__(self, overview=None, messages=None):
        self.overview = overview or {
            "count": 0, "first": None, "last": None, "weekly": []
        }
        self.messages = messages or []
        self.overview_calls = []
        self.browse_calls = []

    def window_overview(self, start_date, end_date, all_contexts=True):
        self.overview_calls.append((start_date, end_date, all_contexts))
        return self.overview

    def browse_window(self, start_date, end_date, offset=0, limit=25,
                      all_contexts=True):
        self.browse_calls.append({
            "start": start_date, "end": end_date,
            "offset": offset, "limit": limit,
        })
        return self.messages


def _bare_engine(green, chat_memory, context_window=32768):
    engine = DeepRecallEngine.__new__(DeepRecallEngine)
    engine.green_memories = green
    engine.chat_memory = chat_memory
    engine._context_window = context_window
    return engine


class TestDeepRecallWindowedTools(unittest.TestCase):
    def test_search_memories_windowed_passes_dates_and_adaptive_topk(self):
        green = _StubGreen(candidates=266)
        engine = _bare_engine(green, _StubChatMemory())
        obs = engine._tool_search_memories({
            "query": "temas de septiembre",
            "start_date": "2025-09-01",
            "end_date": "2025-09-30",
        })
        self.assertEqual(len(green.calls), 1)
        call = green.calls[0]
        self.assertEqual(call["start_date"], "2025-09-01")
        self.assertEqual(call["end_date"], "2025-09-30")
        # 266 candidates at 32k context -> tier 15
        self.assertEqual(call["top_k"], 15)
        self.assertIn("266 memories exist", obs)
        self.assertIn("showing top 0", obs)  # no hits in stub

    def test_search_memories_unwindowed_keeps_search_limit(self):
        green = _StubGreen(candidates=5000)
        engine = _bare_engine(green, _StubChatMemory())
        engine._tool_search_memories({"query": "madrid accident"})
        self.assertEqual(green.calls[0]["top_k"], 8)
        self.assertIsNone(green.calls[0]["start_date"])

    def test_search_memories_sparse_window_returns_all(self):
        green = _StubGreen(candidates=5)
        engine = _bare_engine(green, _StubChatMemory())
        engine._tool_search_memories({
            "query": "q", "start_date": "2026-11-17",
            "end_date": "2026-11-24",
        })
        self.assertEqual(green.calls[0]["top_k"], 5)

    def test_search_memories_rejects_unparseable_dates(self):
        green = _StubGreen()
        engine = _bare_engine(green, _StubChatMemory())
        obs = engine._tool_search_memories({
            "query": "q", "end_date": "not a date",
        })
        self.assertIn("ERROR", obs)
        self.assertEqual(green.calls, [])

    def test_window_overview_is_mechanical(self):
        chat = _StubChatMemory(overview={
            "count": 2070,
            "first": "2025-09-01T06:07:26+00:00",
            "last": "2025-09-30T23:59:00+00:00",
            "weekly": [("2025-W36", 500), ("2025-W37", 640)],
        })
        green = _StubGreen(candidates=266)
        engine = _bare_engine(green, chat)
        obs = engine._tool_window_overview({
            "start_date": "2025-09-01", "end_date": "2025-09-30",
        })
        self.assertIn("conversation messages: 2070", obs)
        self.assertIn("memories created in the period: 266", obs)
        self.assertIn("2025-W36: 500", obs)
        self.assertNotIn("do NOT cover", obs)

    def test_window_overview_flags_memory_free_periods(self):
        chat = _StubChatMemory(overview={
            "count": 345, "first": None, "last": None, "weekly": [],
        })
        green = _StubGreen(candidates=0)
        engine = _bare_engine(green, chat)
        obs = engine._tool_window_overview({
            "start_date": "2025-06-01", "end_date": "2025-06-30",
        })
        self.assertIn("memories created in the period: 0", obs)
        self.assertIn("do NOT cover", obs)
        self.assertIn("browse_logs", obs)

    def test_window_overview_requires_dates(self):
        engine = _bare_engine(_StubGreen(), _StubChatMemory())
        self.assertIn("ERROR", engine._tool_window_overview({}))

    def test_browse_logs_chronological_and_paged(self):
        chat = _StubChatMemory(
            overview={"count": 345, "first": None, "last": None,
                      "weekly": []},
            messages=[
                {"id": "aaa", "timestamp": "2025-06-01T08:00:00+00:00",
                 "role": "user", "content": "hola " * 50},
                {"id": "bbb", "timestamp": "2025-06-01T09:00:00+00:00",
                 "role": "assistant", "content": "qué tal"},
            ],
        )
        engine = _bare_engine(_StubGreen(), chat)
        obs = engine._tool_browse_logs({
            "start_date": "2025-06-01", "end_date": "2025-06-30",
        })
        self.assertIn("345 messages total", obs)
        self.assertIn("showing 0-2", obs)
        self.assertIn("offset=2", obs)
        self.assertIn("[L:aaa @ 2025-06-01T08:00:00+00:00]", obs)
        self.assertIn("[L:bbb @ 2025-06-01T09:00:00+00:00]", obs)
        self.assertLess(
            obs.index("[L:aaa"), obs.index("[L:bbb @"),
            "browse must be chronological",
        )
        self.assertEqual(chat.browse_calls[0]["offset"], 0)

    def test_browse_logs_empty_period(self):
        chat = _StubChatMemory()
        engine = _bare_engine(_StubGreen(), chat)
        obs = engine._tool_browse_logs({
            "start_date": "2025-06-01", "end_date": "2025-06-30",
        })
        self.assertIn("no conversation messages recorded", obs)
        self.assertEqual(chat.browse_calls, [])

    def test_list_topics_windowed(self):
        class _GreenTopics(_StubGreen):
            def get_all_topics(self, start_date=None, end_date=None):
                self.topic_calls = (start_date, end_date)
                return ["Project", "Family"]

        green = _GreenTopics()
        engine = _bare_engine(green, _StubChatMemory())
        obs = engine._tool_list_topics({
            "start_date": "2025-09-01", "end_date": "2025-09-30",
        })
        self.assertEqual(
            green.topic_calls, ("2025-09-01", "2025-09-30")
        )
        self.assertIn("- Project", obs)
        obs = engine._tool_list_topics({
            "start_date": "2025-09-01", "end_date": "bogus",
        })
        self.assertIn("ERROR", obs)


class TestChatMemoryWindowHelpers(unittest.TestCase):
    """browse_window / window_overview against a real SQLite store."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(
            db_path=os.path.join(self.tmpdir, "test.db"),
            context_id="persona-test",
        )
        for ts in [
            "2026-06-01T08:00:00.000000+00:00",
            "2026-06-15T09:00:00.000000+00:00",
            "2026-07-01T10:00:00.000000+00:00",
        ]:
            self.storage.add_message(
                content=f"msg {ts}", role="user", metadata={"timestamp": ts}
            )
        self.cm = ChatMemory.__new__(ChatMemory)
        self.cm.storage = self.storage

    def tearDown(self):
        self.storage.close()

    def test_browse_window_is_chronological_and_bounded(self):
        msgs = self.cm.browse_window("2026-06-01", "2026-06-30", offset=0,
                                     limit=25)
        self.assertEqual(len(msgs), 2)
        self.assertLess(msgs[0]["timestamp"], msgs[1]["timestamp"])

    def test_browse_window_respects_offset(self):
        msgs = self.cm.browse_window("2026-06-01", "2026-07-31", offset=1,
                                     limit=25)
        self.assertEqual(len(msgs), 2)
        self.assertIn("06-15", msgs[0]["timestamp"])

    def test_browse_window_rejects_unparseable(self):
        self.assertEqual(
            self.cm.browse_window("bogus", "2026-06-30"), []
        )

    def test_window_overview_counts_and_weeks(self):
        ov = self.cm.window_overview("2026-06-01", "2026-06-30")
        self.assertEqual(ov["count"], 2)
        self.assertIsNotNone(ov["first"])
        self.assertTrue(ov["weekly"])
        ov_all = self.cm.window_overview("2026-06-01", "2026-07-31")
        self.assertEqual(ov_all["count"], 3)


class _FakeVectorBackend:
    """Minimal vector backend recording add_documents batches."""

    def __init__(self):
        self.batches = []

    def reset(self):
        pass

    def add_documents(self, documents):
        self.batches.append(len(documents))
        return [d["metadata"].get("id", str(i)) for i, d in enumerate(documents)]

    def search(self, query, limit=5, **kwargs):
        return []


class TestReindexProgress(unittest.TestCase):
    """The recipe-gated rebuild must report progress and, when the
    host provides a callback, gate boot on completion (pybridge streams
    'Rebuilding conversation index...')."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(
            db_path=os.path.join(self.tmpdir, "test.db"),
            context_id="persona-test",
        )
        for i in range(3):
            self.storage.add_message(
                content=f"m{i}", role="user",
                metadata={"timestamp": "2026-06-01T08:0%d:00+00:00" % i},
            )
        self.cm = ChatMemory.__new__(ChatMemory)
        self.cm.storage = self.storage
        self.cm.vector_storage = _FakeVectorBackend()

    def tearDown(self):
        self.storage.close()

    def test_progress_callback_per_batch(self):
        events = []
        self.cm.re_index_vectors(
            batch_size=2,
            progress_callback=lambda done, total: events.append((done, total)),
        )
        self.assertEqual(events, [(2, 3), (3, 3)])
        self.assertEqual(self.cm.vector_storage.batches, [2, 1])

    def test_rebuild_marks_recipe_current(self):
        self.assertFalse(
            is_current(self.tmpdir, "chat", "model-x")
        )
        self.cm._rebuild_vector_recipe(self.tmpdir, "model-x")
        self.assertTrue(is_current(self.tmpdir, "chat", "model-x"))

    def test_callback_exception_never_breaks_rebuild(self):
        def bad_callback(done, total):
            raise RuntimeError("UI exploded")

        self.cm.re_index_vectors(
            batch_size=2, progress_callback=bad_callback
        )
        self.assertEqual(self.cm.vector_storage.batches, [2, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
