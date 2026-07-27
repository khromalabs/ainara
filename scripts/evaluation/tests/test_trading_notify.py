# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the watchdog's off-box alerting (executor/notify.py).

Stdlib-only like the module under test, so this runs under ANY venv. No network:
every test substitutes the single `_transport` seam.

What matters here is the failure posture, not the happy path:
  - unconfigured is INERT (never raises, never blocks a guard loop),
  - a dead endpoint is swallowed, not propagated,
  - repeat alerts for one ongoing condition are throttled,
  - the dead-man heartbeat is interval-gated and single-flight,
  - push URLs (which ARE credentials) are redacted in anything loggable.

Run:  python scripts/evaluation/tests/test_trading_notify.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from executor import notify as N  # noqa: E402

WEBHOOK = "https://ntfy.sh/ainara-secret-topic"
HEARTBEAT = "https://hc-ping.com/0000-uuid-1111"


class _Cfg:
    def __init__(self, **notify):
        self._n = notify

    def get(self, key, default=None):
        return self._n if key == "trading.notify" else default


def recorder(ok=True, raises=None):
    """A fake _transport that records calls. Returns (fn, calls)."""
    calls = []

    def fn(url, method, body, content_type, headers, timeout):
        calls.append({"url": url, "method": method, "body": body,
                      "content_type": content_type, "headers": headers,
                      "timeout": timeout})
        if raises:
            raise raises
        return ok

    return fn, calls


def notifier(**cfg):
    """Synchronous notifier (background=False) so assertions are not racy."""
    return N.Notifier(_Cfg(**cfg), background=False)


class BuildBody(unittest.TestCase):
    def test_structured_json_is_the_default(self):
        body, ctype = N.build_body("T", "m", "critical", data={"coin": "BTC"})
        self.assertEqual(ctype, "application/json")
        self.assertIn(b'"severity": "critical"', body)
        self.assertIn(b'"coin": "BTC"', body)

    def test_single_field_wrap_for_discord_and_slack(self):
        body, _ = N.build_body("T", "m", json_field="content")
        self.assertEqual(body, b'{"content": "T\\n\\nm"}')

    def test_text_format_for_ntfy(self):
        body, ctype = N.build_body("T", "m", fmt="text")
        self.assertEqual(body, b"T\n\nm")
        self.assertTrue(ctype.startswith("text/plain"))

    def test_title_only_when_there_is_no_message(self):
        body, _ = N.build_body("T", "", fmt="text")
        self.assertEqual(body, b"T")


class Redaction(unittest.TestCase):
    def test_the_secret_path_never_survives(self):
        # An ntfy topic or a healthchecks UUID in a log line is a live endpoint.
        red = N.redact(WEBHOOK)
        self.assertNotIn("ainara-secret-topic", red)
        self.assertIn("ntfy.sh", red)

    def test_garbage_and_none_do_not_raise(self):
        self.assertIsNone(N.redact(None))
        self.assertIsInstance(N.redact("not a url"), str)


class Unconfigured(unittest.TestCase):
    """The default state for anyone who never sets trading.notify."""

    def setUp(self):
        self.n = notifier()

    def test_flags_are_all_false(self):
        self.assertFalse(self.n.enabled)
        self.assertFalse(self.n.push_enabled)
        self.assertFalse(self.n.deadman_enabled)

    def test_calls_are_inert_and_silent(self):
        fn, calls = recorder()
        self.n._transport = fn
        self.assertFalse(self.n.send("T", "m"))
        self.assertFalse(self.n.send_event("k", "T", "m"))
        self.assertFalse(self.n.heartbeat(force=True))
        self.assertEqual(calls, [])

    def test_describe_says_so_plainly(self):
        self.assertIn("NOT CONFIGURED", self.n.describe())


class Push(unittest.TestCase):
    def test_send_posts_to_the_webhook(self):
        n = notifier(webhook_url=WEBHOOK)
        fn, calls = recorder()
        n._transport = fn
        self.assertTrue(n.send("Title", "body"))
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["url"], calls[0]["method"]), (WEBHOOK, "POST"))

    def test_extra_headers_are_passed_through(self):
        n = notifier(webhook_url=WEBHOOK,
                     webhook_headers={"Authorization": "Bearer tok"})
        fn, calls = recorder()
        n._transport = fn
        n.send("T", "m")
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer tok"})

    def test_a_dead_endpoint_is_swallowed_not_raised(self):
        # The whole point: alerting must never be able to kill the guard loop.
        n = notifier(webhook_url=WEBHOOK)
        n._transport, _ = recorder(raises=OSError("connection refused"))
        self.assertFalse(n.send("T", "m"))

    def test_non_2xx_is_reported_as_failure(self):
        n = notifier(webhook_url=WEBHOOK)
        n._transport, _ = recorder(ok=False)
        self.assertFalse(n.send("T", "m"))


class EventThrottle(unittest.TestCase):
    def setUp(self):
        self.n = notifier(webhook_url=WEBHOOK, repeat_seconds=3600)
        self.fn, self.calls = recorder()
        self.n._transport = self.fn

    def test_one_condition_alerts_once_per_repeat_window(self):
        # A 5s guard loop re-derives every alarm; unthrottled this would be ~720
        # identical pushes an hour and you would mute the channel.
        for _ in range(50):
            self.n.send_event("near_liquidation:BTC", "T", "m")
        self.assertEqual(len(self.calls), 1)

    def test_distinct_keys_alert_independently(self):
        self.n.send_event("near_liquidation:BTC", "T", "m")
        self.n.send_event("near_liquidation:ETH", "T", "m")
        self.assertEqual(len(self.calls), 2)

    def test_forget_lets_a_recurrence_alert_immediately(self):
        self.n.send_event("k", "T", "m")
        self.n.forget_event("k")          # condition cleared…
        self.n.send_event("k", "T", "m")  # …and came back: that is news again
        self.assertEqual(len(self.calls), 2)


class DeadMansSwitch(unittest.TestCase):
    def setUp(self):
        self.n = notifier(heartbeat_url=HEARTBEAT,
                          heartbeat_interval_seconds=600)
        self.fn, self.calls = recorder()
        self.n._transport = self.fn

    def test_interval_gated_so_a_5s_loop_does_not_hammer_it(self):
        for _ in range(100):
            self.n.heartbeat()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["method"], "GET")

    def test_force_bypasses_the_interval_for_startup(self):
        self.n.heartbeat()
        self.n.heartbeat(force=True)
        self.assertEqual(len(self.calls), 2)

    def test_post_method_sends_an_empty_body(self):
        n = notifier(heartbeat_url=HEARTBEAT, heartbeat_method="post")
        fn, calls = recorder()
        n._transport = fn
        n.heartbeat(force=True)
        self.assertEqual((calls[0]["method"], calls[0]["body"]), ("POST", b""))

    def test_a_failed_ping_clears_inflight_so_the_next_one_still_goes(self):
        # If a raise left _heartbeat_inflight stuck True, pings would stop forever —
        # the external monitor would alert on a perfectly healthy watchdog.
        self.n._transport, _ = recorder(raises=OSError("timeout"))
        self.n.heartbeat(force=True)
        self.assertFalse(self.n._heartbeat_inflight)
        self.n._transport = self.fn
        self.n.heartbeat(force=True)
        self.assertEqual(len(self.calls), 1)

    def test_describe_redacts_the_ping_url(self):
        self.assertNotIn("0000-uuid-1111", self.n.describe())


if __name__ == "__main__":
    unittest.main()
