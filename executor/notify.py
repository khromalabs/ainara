# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Off-box alerting for the position watchdog — the only signal that survives the box.

Everything else this stack knows about risk is local: a log line, a JSON alarm file
in temp, a field on /health. All three are invisible exactly when it matters most.
If the machine sleeps, drops its network, or the supervisor dies, every local signal
goes quiet — and quiet is indistinguishable from healthy. Two mechanisms fix that,
and they fail in OPPOSITE directions on purpose:

  1. PUSH (`webhook_url`) — the watchdog reports what it found. Needs the box alive
     and connected, so a dead box pushes nothing at all.
  2. DEAD-MAN'S SWITCH (`heartbeat_url`) — the watchdog pings an external monitor on
     an interval, and that monitor alerts when the pings STOP. A local guard can
     never report its own death; only an absent heartbeat can. This is the half that
     covers the failure the rest of the stack structurally cannot see.

Stdlib only (urllib, not requests): executor/watchdog.py imports this, and the
watchdog is deliberately dependency-free so its risk logic runs under any venv.

Every call is best-effort and swallows its own errors. Alerting is observability; a
broken webhook must never be able to stall or kill the guard loop. Sends default to
daemon threads for the same reason — a hung endpoint would otherwise add its full
timeout to every poll of a 5-second loop.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("executor.notify")

DEFAULT_TIMEOUT = 5.0
DEFAULT_HEARTBEAT_INTERVAL = 60.0
DEFAULT_REPEAT_SECONDS = 900.0
DEFAULT_MAX_MESSAGE_CHARS = 1900  # Discord rejects content over 2000


def redact(url):
    """Scheme + host + a stub path. Push URLs ARE the credential — an ntfy topic or
    a healthchecks UUID in a log line is a live alerting endpoint anyone reading the
    log can spam or silence. Never log one whole."""
    if not url:
        return None
    try:
        p = urllib.parse.urlsplit(url)
        return f"{p.scheme}://{p.netloc}/…" if p.netloc else "…"
    except Exception:
        return "…"


def build_body(title, message, severity="critical", data=None,
               json_field=None, fmt="json", max_chars=None):
    """Pure: the HTTP body for one alert. Returns (bytes, content_type).

    Three shapes cover every push service worth wiring, with no per-service code:
      fmt="text"           -> "TITLE\\n\\nmessage"            (ntfy, plain sinks)
      json_field="content" -> {"content": "TITLE\\n\\nmessage"} (Discord; Slack uses
                              "text")
      default              -> the full structured payload      (custom endpoints,
                              Zapier, n8n, your own receiver)

    `max_chars` truncates the composed text (never `data`). Services cap message
    length — Discord rejects content over 2000 chars with a 400 — and the alert most
    likely to blow the cap is the one listing findings for three coins at once, i.e.
    exactly the alert you cannot afford to have silently dropped. Truncated is
    strictly better than refused.
    """
    text = f"{title}\n\n{message}" if message else title
    if max_chars and len(text) > int(max_chars):
        keep = max(0, int(max_chars) - 16)
        text = text[:keep] + "… [truncated]"
    if fmt == "text":
        return text.encode("utf-8"), "text/plain; charset=utf-8"
    if json_field:
        body = {json_field: text}
    else:
        body = {"title": title, "message": message, "severity": severity,
                "source": "ainara-executor-watchdog", "ts": time.time()}
        if data:
            body["data"] = data
    return json.dumps(body).encode("utf-8"), "application/json"


class Notifier:
    """Config-driven push + dead-man heartbeat. Inert unless configured.

    Reads `trading.notify`:
      webhook_url                 where alerts are POSTed (unset = no push)
      webhook_headers             extra headers, e.g. {Authorization: "Bearer …"}
      webhook_json_field          wrap the text in this single JSON field
                                  ("content" Discord, "text" Slack)
      webhook_format              "json" (default) | "text" (ntfy and friends)
      heartbeat_url               dead-man ping target (unset = no dead-man switch)
      heartbeat_method            "GET" (default; works with healthchecks.io and
                                  uptime-kuma) | "POST"
      heartbeat_interval_seconds  60 — how often to ping, independent of poll rate
      timeout_seconds             5 — per request
      repeat_seconds              900 — re-alert interval for a STILL-active event
    """

    def __init__(self, config, background=True):
        n = (config.get("trading.notify", {}) if config else {}) or {}
        self.webhook_url = n.get("webhook_url")
        self.webhook_headers = n.get("webhook_headers") or {}
        self.webhook_json_field = n.get("webhook_json_field")
        self.webhook_format = n.get("webhook_format", "json")
        self.heartbeat_url = n.get("heartbeat_url")
        self.heartbeat_method = (n.get("heartbeat_method") or "GET").upper()
        self.heartbeat_interval = float(
            n.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_INTERVAL))
        self.timeout = float(n.get("timeout_seconds", DEFAULT_TIMEOUT))
        # Default sits under Discord's 2000-char content limit with headroom; raise it
        # for a sink that accepts more.
        self.max_message_chars = int(n.get("max_message_chars",
                                           DEFAULT_MAX_MESSAGE_CHARS))
        self.repeat_seconds = float(n.get("repeat_seconds", DEFAULT_REPEAT_SECONDS))
        # Sends go to a daemon thread so a hung endpoint cannot stretch the guard
        # loop. Tests construct with background=False to assert synchronously.
        self.background = background
        self._last_sent = {}          # event key -> monotonic time of last push
        self._last_heartbeat = 0.0    # monotonic; 0 = never
        self._heartbeat_inflight = False
        self._lock = threading.Lock()

    # ---- capability flags -------------------------------------------------

    @property
    def push_enabled(self):
        return bool(self.webhook_url)

    @property
    def deadman_enabled(self):
        return bool(self.heartbeat_url)

    @property
    def enabled(self):
        return self.push_enabled or self.deadman_enabled

    # ---- transport (single seam; tests substitute this) -------------------

    def _transport(self, url, method, body, content_type, headers, timeout):
        """One HTTP request. Returns True on a 2xx. Raises nothing upward."""
        req = urllib.request.Request(url, data=body, method=method)
        if body is not None and content_type:
            req.add_header("Content-Type", content_type)
        for k, v in (headers or {}).items():
            req.add_header(str(k), str(v))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(status) < 300

    def _request(self, url, method="POST", body=None, content_type=None,
                 headers=None, what="alert"):
        try:
            ok = self._transport(url, method, body, content_type, headers,
                                 self.timeout)
            if not ok:
                logger.warning("notify: %s to %s returned a non-2xx", what,
                               redact(url))
            return bool(ok)
        except urllib.error.HTTPError as e:
            logger.warning("notify: %s to %s failed HTTP %s", what, redact(url),
                           e.code)
        except Exception as e:
            # Includes URLError/socket timeouts — i.e. the offline case, which is
            # precisely when the dead-man switch (not this) is what saves you.
            logger.warning("notify: %s to %s failed: %s: %s", what, redact(url),
                           type(e).__name__, e)
        return False

    # ---- push -------------------------------------------------------------

    def send(self, title, message, severity="critical", data=None,
             background=None):
        """Push one alert now. Returns True if it was dispatched (not delivered —
        a backgrounded send has no answer yet by design)."""
        if not self.push_enabled:
            return False
        body, ctype = build_body(title, message, severity, data,
                                 json_field=self.webhook_json_field,
                                 fmt=self.webhook_format,
                                 max_chars=self.max_message_chars)
        run = (lambda: self._request(self.webhook_url, "POST", body, ctype,
                                     self.webhook_headers, what="alert"))
        use_bg = self.background if background is None else background
        if use_bg:
            threading.Thread(target=run, daemon=True,
                             name="notify-send").start()
            return True
        return run()

    def send_event(self, key, title, message, severity="critical", data=None,
                   background=None):
        """Push, but at most once per `repeat_seconds` for a given `key`.

        The watchdog re-derives every alarm on a 5-second poll, so an unthrottled
        push would send hundreds of identical alerts for one problem and train you
        to ignore the channel. A still-active condition re-alerts on the repeat
        interval instead: persistent enough to nag, sparse enough to read.
        """
        now = time.monotonic()
        with self._lock:
            last = self._last_sent.get(key)
            if last is not None and (now - last) < self.repeat_seconds:
                return False
            self._last_sent[key] = now
        return self.send(title, message, severity, data, background=background)

    def forget_event(self, key):
        """Drop a key's throttle so the NEXT occurrence alerts immediately.

        Called when a condition clears: a problem that comes back an hour later is
        news again, and should not be swallowed by the repeat window of the last
        one."""
        with self._lock:
            self._last_sent.pop(key, None)

    # ---- dead-man's switch ------------------------------------------------

    def heartbeat(self, force=False):
        """Ping the external monitor if one is due. Cheap to call every poll.

        Interval-gated internally so the caller doesn't have to track timing: a 5s
        guard loop must not hammer a monitoring endpoint 720 times a minute. Single
        -flight — if a ping is still in the air (slow or hung endpoint), skip
        rather than pile threads up.
        """
        if not self.deadman_enabled:
            return False
        now = time.monotonic()
        with self._lock:
            if self._heartbeat_inflight:
                return False
            if not force and self._last_heartbeat and (
                    now - self._last_heartbeat) < self.heartbeat_interval:
                return False
            self._last_heartbeat = now
            self._heartbeat_inflight = True

        def run():
            try:
                body = b"" if self.heartbeat_method == "POST" else None
                return self._request(self.heartbeat_url, self.heartbeat_method,
                                     body, None, None, what="heartbeat")
            finally:
                with self._lock:
                    self._heartbeat_inflight = False

        if self.background:
            threading.Thread(target=run, daemon=True,
                             name="notify-heartbeat").start()
            return True
        return run()

    def describe(self):
        """One-line summary for the startup banner (redacted)."""
        if not self.enabled:
            return "off-box alerting: NOT CONFIGURED"
        bits = []
        if self.push_enabled:
            bits.append(f"push -> {redact(self.webhook_url)}")
        if self.deadman_enabled:
            bits.append(
                f"dead-man {self.heartbeat_method} -> "
                f"{redact(self.heartbeat_url)} every {self.heartbeat_interval:.0f}s")
        return "off-box alerting: " + ", ".join(bits)
