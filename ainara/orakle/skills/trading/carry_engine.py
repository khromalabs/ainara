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

import datetime
import logging
import math
import time
from typing import Annotated, Any, Dict, List, Literal, Optional

import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill

HOURS_PER_YEAR = 24 * 365
HOUR_MS = 3_600_000

# Public funding endpoints. Decisions default to MAINNET data (the real economic
# signal) even when trading on testnet, since testnet funding is thin/artificial.
_HL_INFO = {
    "mainnet": "https://api.hyperliquid.xyz/info",
    "testnet": "https://api.hyperliquid-testnet.xyz/info",
}
_DYDX_INDEXER = {
    "mainnet": "https://indexer.dydx.trade",
    "testnet": "https://indexer.v4testnet.dydx.exchange",
}


class TradingCarryEngine(Skill):
    """Deterministic brain of the delta-neutral funding-differential strategy.

    Given a per-venue funding stream for one asset, it computes the cross-venue
    funding differential, smooths it (an EMA of the spread — trading the raw spread
    churns itself to death on fees), and decides SHORT-the-higher / LONG-the-lower
    or SIT OUT based on whether the smoothed edge clears an annualized threshold.

    It also estimates net APR after fees. It reads market data and does maths; it
    holds no keys and places no orders, so it carries no jurisdiction gate. The
    execution layer that ACTS on its decisions is where that gate lives.

    Two design requirements below are not knobs to be casually changed — a full
    12-month HL/dYdX backtest showed the strategy is unviable without them:
      1. gate on the SMOOTHED spread, never the instantaneous one;
      2. sit out when the smoothed edge does not clear costs.
    """

    matcher_info = (
        "Use this skill to evaluate the cross-venue funding-rate ARBITRAGE"
        " differential for a crypto asset between two perpetual venues (e.g."
        " Hyperliquid vs dYdX): whether to open a delta-neutral carry position"
        " (short the higher-funding venue, long the lower), which side on each"
        " venue, and the estimated net annualized return after fees, or whether"
        " to sit out. Keywords: funding arbitrage, carry, delta neutral, basis,"
        " funding differential, cross-venue."
    )

    def __init__(self):
        super().__init__()
        self.name = "carry_engine"
        self.logger = logging.getLogger(__name__)
        c = config.get("trading.carry_engine", {}) or {}
        # Defaults grounded in the 12-month HL/dYdX study (best net was ~2wk span,
        # low single-digit % gate). Leverage/fees overridable per deployment.
        self.default_span_hours = int(c.get("smoothing_span_hours", 336))  # ~14d EMA
        self.default_threshold_pct = float(c.get("enter_threshold_annual_pct", 4.0))
        self.default_leverage = float(c.get("leverage", 3.0))
        # One-way taker fee per leg, as a fraction of notional.
        self.fee_per_leg = {
            "hyperliquid": float(c.get("fee_hyperliquid", 0.00035)),
            "dydx": float(c.get("fee_dydx", 0.00050)),
        }

    # ------------------------------------------------------------------
    # Core maths (pure, testable)
    # ------------------------------------------------------------------

    @staticmethod
    def _ema(values: List[float], span: int) -> float:
        """Return the final EMA value for *values* with the given span."""
        if not values:
            return 0.0
        alpha = 2.0 / (span + 1)
        ema = values[0]
        for v in values[1:]:
            ema = alpha * v + (1 - alpha) * ema
        return ema

    @staticmethod
    def _ema_series(values: List[float], span: int) -> List[float]:
        """Return the full EMA series for *values* (same length), for backtesting."""
        out: List[float] = []
        if not values:
            return out
        alpha = 2.0 / (span + 1)
        ema = values[0]
        for v in values:
            ema = alpha * v + (1 - alpha) * ema
            out.append(ema)
        return out

    def _round_trip_cost_fraction(self, venue_a: str, venue_b: str) -> float:
        """Fee to open AND close both legs, as a fraction of one-leg notional."""
        fa = self.fee_per_leg.get(venue_a, 0.0005)
        fb = self.fee_per_leg.get(venue_b, 0.0005)
        return 2 * (fa + fb)  # entry + exit, both legs

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        venue_a: str,
        venue_b: str,
        funding_a_hourly: List[float],
        funding_b_hourly: List[float],
        span_hours: Optional[int] = None,
        threshold_annual_pct: Optional[float] = None,
        capital_usd: Optional[float] = None,
        leverage: Optional[float] = None,
        expected_hold_days: float = 14.0,
    ) -> Dict[str, Any]:
        span = span_hours or self.default_span_hours
        thresh_pct = (
            threshold_annual_pct
            if threshold_annual_pct is not None
            else self.default_threshold_pct
        )
        lev = leverage if leverage is not None else self.default_leverage

        n = min(len(funding_a_hourly), len(funding_b_hourly))
        if n < 2:
            return {"error": "Need at least 2 aligned funding samples per venue"}
        a = funding_a_hourly[-n:]
        b = funding_b_hourly[-n:]

        # Spread series: positive => venue_a funds higher than venue_b.
        spread = [a[i] - b[i] for i in range(n)]
        raw = spread[-1]
        smoothed = self._ema(spread, span)

        thresh_hourly = thresh_pct / 100.0 / HOURS_PER_YEAR

        if smoothed > thresh_hourly:
            action = "open"
            short_venue, long_venue = venue_a, venue_b  # short the higher funder
            edge_hourly = smoothed
        elif smoothed < -thresh_hourly:
            action = "open"
            short_venue, long_venue = venue_b, venue_a
            edge_hourly = -smoothed
        else:
            # Below threshold: the smoothed edge does not clear costs — sit out.
            return {
                "action": "sit_out",
                "reason": "smoothed funding differential below entry threshold",
                "asset_pair": f"{venue_a}/{venue_b}",
                "raw_spread_annual_pct": round(raw * HOURS_PER_YEAR * 100, 3),
                "smoothed_spread_annual_pct": round(smoothed * HOURS_PER_YEAR * 100, 3),
                "enter_threshold_annual_pct": thresh_pct,
                "smoothing_span_hours": span,
                "samples_used": n,
            }

        # Gross carry over the expected hold, minus one round-trip of fees.
        gross_edge_annual = edge_hourly * HOURS_PER_YEAR
        cost_fraction = self._round_trip_cost_fraction(short_venue, long_venue)
        hold_fraction_of_year = expected_hold_days / 365.0
        gross_over_hold = gross_edge_annual * hold_fraction_of_year
        net_over_hold = gross_over_hold - cost_fraction
        # Annualize the net return earned over the hold window (on notional).
        net_annual_notional = (
            net_over_hold / hold_fraction_of_year if hold_fraction_of_year else 0.0
        )

        result = {
            "action": action,
            "short_venue": short_venue,
            "long_venue": long_venue,
            "asset_pair": f"{venue_a}/{venue_b}",
            "raw_spread_annual_pct": round(raw * HOURS_PER_YEAR * 100, 3),
            "smoothed_spread_annual_pct": round(smoothed * HOURS_PER_YEAR * 100, 3),
            "gross_edge_annual_pct": round(gross_edge_annual * 100, 3),
            "round_trip_cost_pct_notional": round(cost_fraction * 100, 4),
            "expected_hold_days": expected_hold_days,
            # NOTE: these two are POINT-IN-TIME projections that assume the CURRENT
            # smoothed spread holds flat across the whole hold and you pay fees only
            # once. They are optimistic — the realized spread compresses and you
            # re-enter repeatedly. For an expected annual return use the `backtest`
            # action, which walks the full history and is ~half these figures.
            "net_annual_pct_if_spread_holds": round(net_annual_notional * 100, 3),
            "net_annual_pct_on_capital_if_spread_holds": round(
                net_annual_notional * lev * 100, 3
            ),
            "estimate_basis": "point_in_time_spread_held_flat (optimistic; see backtest)",
            "leverage": lev,
            "enter_threshold_annual_pct": thresh_pct,
            "smoothing_span_hours": span,
            "samples_used": n,
        }

        # Guard: if fees eat the whole hold, don't pretend it's a trade.
        if net_over_hold <= 0:
            result["action"] = "sit_out"
            result["reason"] = (
                "estimated round-trip fees exceed expected carry over the hold"
            )

        if capital_usd:
            notional = capital_usd * lev
            result["capital_usd"] = capital_usd
            result["notional_per_leg_usd"] = round(notional, 2)
            result["est_net_usd_over_hold_if_spread_holds"] = round(
                net_over_hold * notional, 2
            )

        return result

    # ------------------------------------------------------------------
    # Backtest (walk-forward; reproduces the realized-net study numbers)
    # ------------------------------------------------------------------

    def backtest(
        self,
        venue_a: str,
        venue_b: str,
        funding_a_hourly: List[float],
        funding_b_hourly: List[float],
        span_hours: Optional[int] = None,
        threshold_annual_pct: Optional[float] = None,
        exit_threshold_annual_pct: Optional[float] = None,
        min_hold_hours: float = 0.0,
        leverage: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Walk the full aligned history hour by hour: gate on the smoothed spread,
        accrue the REALIZED spread while positioned, and charge fees on every
        entry and exit. This is the honest expected-return estimate — unlike
        evaluate(), it does not assume the current spread persists.

        `exit_threshold_annual_pct` and `min_hold_hours` let this walk-forward
        model the two knobs `decide_exit` already exposes live but that this
        function never tested: a SEPARATE (typically lower) exit threshold for
        hysteresis, and a floor on how long a position must be held before an
        exit signal is honored. Both default to reproducing the OLD single-
        threshold, no-floor behavior exactly (exit_threshold defaults to the
        entry threshold; min_hold_hours defaults to 0), so every existing caller
        gets byte-identical results unless it opts in.

        The economic case for testing this: across 5 real round trips, fees
        ($0.38) nearly wiped out funding collected ($0.14), and none of them
        held past the ~5.6-day fee-breakeven point. Whether hysteresis or a
        hold floor would have cut that churn is exactly what this answers.
        """
        span = span_hours or self.default_span_hours
        thresh_pct = (
            threshold_annual_pct
            if threshold_annual_pct is not None
            else self.default_threshold_pct
        )
        exit_thresh_pct = (
            exit_threshold_annual_pct
            if exit_threshold_annual_pct is not None
            else thresh_pct
        )
        lev = leverage if leverage is not None else self.default_leverage

        n = min(len(funding_a_hourly), len(funding_b_hourly))
        if n < span + 2:
            return {"error": f"Need at least {span + 2} aligned samples to backtest"}
        a = funding_a_hourly[-n:]
        b = funding_b_hourly[-n:]
        spread = [a[i] - b[i] for i in range(n)]
        sig = self._ema_series(spread, span)
        enter_thresh_hourly = thresh_pct / 100.0 / HOURS_PER_YEAR
        exit_thresh_hourly = exit_thresh_pct / 100.0 / HOURS_PER_YEAR
        # per-leg-pair cost of one entry OR one exit across both legs
        leg_event_cost = self.fee_per_leg.get(venue_a, 0.0005) + self.fee_per_leg.get(
            venue_b, 0.0005
        )

        pos, gross, fees, entries, held = 0, 0.0, 0.0, 0, 0
        hours_in_position = 0
        for i in range(n):
            # Which threshold gates this hour's decision depends on whether a
            # position is already open — mirrors decide() (flat, gates on the
            # ENTER threshold) and decide_exit() (positioned, gates on the EXIT
            # threshold) as the two separate deterministic checks they are live.
            # With exit_thresh == enter_thresh (the default) this is the same
            # single threshold either way, so nothing changes for old callers.
            gate_hourly = exit_thresh_hourly if pos != 0 else enter_thresh_hourly
            want = 1 if sig[i] > gate_hourly else (-1 if sig[i] < -gate_hourly else 0)

            # Minimum hold suppresses an EXIT only (decay to flat OR a sign
            # flip) until the position has been held long enough — it never
            # blocks a fresh entry. This models a floor decide_exit does not
            # have today, to test whether adding one would help: a position
            # can currently close inside hours of opening on a single noisy
            # sample (dYdX funding hits ~2.3-sigma single-hour outliers), which
            # is pure fee churn if the spread was only ever going to bounce
            # back. The tradeoff is real and deliberate: this also holds
            # through a genuine adverse reversal for the same window.
            if pos != 0 and want != pos and hours_in_position < min_hold_hours:
                want = pos

            if want != pos:
                if pos != 0:
                    fees += leg_event_cost  # exit
                if want != 0:
                    fees += leg_event_cost  # entry
                    entries += 1
                pos = want
                hours_in_position = 0
            if pos != 0:
                gross += spread[i] * pos  # realized spread, signed by our side
                held += 1
                hours_in_position += 1

        scale = HOURS_PER_YEAR / n  # annualize the per-window totals
        gross_ann = gross * scale
        fees_ann = fees * scale
        net_ann = gross_ann - fees_ann
        return {
            "mode": "backtest_walk_forward",
            "asset_pair": f"{venue_a}/{venue_b}",
            "samples_used": n,
            "uptime_pct": round(held / n * 100, 1),
            "entries_per_year": round(entries * scale, 1),
            "avg_hold_hours": round(held / entries, 1) if entries else 0.0,
            "gross_annual_pct_notional": round(gross_ann * 100, 3),
            "fees_annual_pct_notional": round(fees_ann * 100, 3),
            "net_annual_pct_notional": round(net_ann * 100, 3),
            "net_annual_pct_on_capital": round(net_ann * lev * 100, 3),
            "leverage": lev,
            "smoothing_span_hours": span,
            "enter_threshold_annual_pct": thresh_pct,
            "exit_threshold_annual_pct": exit_thresh_pct,
            "min_hold_hours": min_hold_hours,
        }

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Self-contained decision (fetches its own history — for orchestration)
    # ------------------------------------------------------------------

    def _hl_funding_history(self, coin, network, hours):
        """HL hourly funding (oldest-first) as {hour_ms: rate}.

        Paginates FORWARD past HL's 500-row response cap. A single fundingHistory
        call returns at most 500 rows from startTime, oldest-first, so a request
        wider than 500h silently yields the OLDEST 500 hours and a window that can
        END days in the past — not 'now'. On a 30d (720h) request that left the
        EMA signal reading a window ending ~9 days stale, on BOTH the entry and
        exit sides. Advancing startTime past the last row and looping accumulates
        a window that actually reaches the present, which is what the smoothed
        signal must be computed on.
        """
        start = int(time.time() * 1000) - hours * HOUR_MS
        now = int(time.time() * 1000)
        out = {}
        # Bound the loop: enough pages to cover `hours` at 500/page, plus slack.
        for _ in range(hours // 500 + 3):
            rows = requests.post(_HL_INFO[network], json={
                "type": "fundingHistory", "coin": coin, "startTime": start},
                timeout=30).json()
            if not rows:
                break
            for r in rows:
                out[int(r["time"]) - (int(r["time"]) % HOUR_MS)] = float(
                    r["fundingRate"])
            last = max(int(r["time"]) for r in rows)
            # Stop on a short (final) page, or once we've reached the latest hour.
            if len(rows) < 500 or last >= now - HOUR_MS:
                break
            start = last + 1
        return out

    def _dydx_funding_history(self, coin, network, hours):
        """dYdX hourly funding (oldest-first) as {hour_ms: rate}, paginated back."""
        idx = _DYDX_INDEXER[network]
        out, before = {}, datetime.datetime.now(datetime.UTC).isoformat().replace(
            "+00:00", "Z")
        for _ in range(hours // 100 + 2):
            rows = requests.get(
                f"{idx}/v4/historicalFunding/{coin}-USD",
                params={"limit": 100, "effectiveBeforeOrAt": before},
                timeout=30).json().get("historicalFunding", [])
            if not rows:
                break
            for r in rows:
                t = datetime.datetime.fromisoformat(r["effectiveAt"].replace("Z", "+00:00"))
                out[int(t.timestamp() * 1000) // HOUR_MS * HOUR_MS] = float(r["rate"])
            oldest = min(r["effectiveAt"] for r in rows)
            if len(out) >= hours:
                break
            t = datetime.datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            before = (t - datetime.timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        return out

    @staticmethod
    def _dydx_subaccount_for(coin):
        """Subaccount holding `coin` on dYdX, per trading.dydx.subaccounts.

        Mirrors DydxExecutor.subaccount_for. Unmapped coins use 0, so an unset map
        behaves exactly as before isolation.
        """
        m = config.get("trading.dydx.subaccounts", {}) or {}
        return int({str(k).upper(): v for k, v in m.items()}.get(
            (coin or "").split("-")[0].upper(), 0))

    def _current_side(self, coin):
        """Which way we are positioned RIGHT NOW, read-only from public APIs.

        Positions are public per account address, so this needs no keys and keeps
        the engine key-free like the rest of it.

        Returns (side, detail):
          +1  short hyperliquid / long dydx  (what a positive smoothed spread wants)
          -1  short dydx / long hyperliquid
           0  flat
        side is None when the read failed or the legs are not a clean hedge — the
        caller must never guess a position it could not confirm.
        """
        try:
            hl_net = config.get("apis.hyperliquid.network", "testnet")
            hl_addr = config.get(f"apis.hyperliquid.{hl_net}.account_address")
            st = requests.post(_HL_INFO[hl_net], json={
                "type": "clearinghouseState", "user": hl_addr}, timeout=20).json()
            hl_szi = 0.0
            for p in st.get("assetPositions", []):
                pos = p.get("position", {})
                if pos.get("coin") == coin:
                    hl_szi = float(pos.get("szi", 0) or 0)
                    break

            dy_net = config.get("apis.dydx.network", "testnet")
            dy_addr = config.get(f"apis.dydx.{dy_net}.account_address")
            d = requests.get(
                f"{_DYDX_INDEXER[dy_net]}/v4/addresses/{dy_addr}", timeout=20).json()
            subs = d.get("subaccounts") or []
            dy_size = 0.0
            # EVERY subaccount, not subs[0]: under position isolation the coin lives
            # in its own subaccount, and reading only the first reports a funded ETH
            # or SOL position as FLAT — decide_exit would then answer "no open
            # position to close" and strand it open forever.
            for sub in subs:
                for mkt, p in (sub.get("openPerpetualPositions") or {}).items():
                    if mkt.split("-")[0] == coin:
                        sz = abs(float(p.get("size", 0) or 0))
                        dy_size = sz if p.get("side") == "LONG" else -sz
                        break
                if dy_size:
                    break
        except Exception as e:
            self.logger.warning(f"position read failed: {e}")
            return None, {"error": f"position read failed: {e}"}

        detail = {"hyperliquid_szi": hl_szi, "dydx_size": dy_size}
        hl_open, dy_open = abs(hl_szi) > 0, abs(dy_size) > 0
        if not hl_open and not dy_open:
            return 0, {**detail, "state": "flat"}
        if hl_open != dy_open:
            # Half a hedge. Closing is the watchdog's job, not the exit rule's.
            return None, {**detail, "state": "broken_hedge",
                          "note": "only one leg open — the position watchdog owns"
                                  " this, not the exit rule"}
        if hl_szi < 0 < dy_size:
            return 1, {**detail, "state": "short_hyperliquid_long_dydx"}
        if dy_size < 0 < hl_szi:
            return -1, {**detail, "state": "short_dydx_long_hyperliquid"}
        return None, {**detail, "state": "not_delta_neutral",
                      "note": "both legs same direction — not a hedge"}

    def _book_state(self, exclude_coin=None):
        """(open_position_count, total_notional_usd) across all OTHER currently
        open HL positions — the book-wide exposure gate's read.

        HL is always one of the two legs of every hedge (only two venues exist:
        hyperliquid, dydx), so its position list IS the whole book's aggregate
        view; dYdX's per-coin subaccounts are already isolated and don't need
        summing. Public endpoint, same one _current_side/_free_collateral use —
        no keys, key-free like the rest of the engine.

        Returns (None, None) on a failed read — the caller must treat that as
        "cannot verify the book is within budget", never as "book is empty".
        """
        try:
            hl_net = config.get("apis.hyperliquid.network", "testnet")
            hl_addr = config.get(f"apis.hyperliquid.{hl_net}.account_address")
            st = requests.post(_HL_INFO[hl_net], json={
                "type": "clearinghouseState", "user": hl_addr}, timeout=20).json()
            count, notional = 0, 0.0
            for p in st.get("assetPositions", []):
                pos = p.get("position", {})
                if exclude_coin and pos.get("coin") == exclude_coin:
                    continue
                szi = float(pos.get("szi", 0) or 0)
                if not abs(szi) > 0:
                    continue
                count += 1
                notional += abs(float(pos.get("positionValue", 0) or 0))
            return count, notional
        except Exception as e:
            self.logger.warning(f"book state read failed: {e}")
            return None, None

    @staticmethod
    def _venue_network(venue):
        """The network a venue actually TRADES on (apis.<venue>.network).

        Deliberately NOT funding_network. The two answer different questions:

          funding_network -> where the SIGNAL is read. Mainnet, always: testnet
                             funding is thin and artificial.
          venue network   -> where the ORDER lands. Whatever the venue is
                             configured for, and the only book that can fill you.

        Conflating them is how run e8868482 opened: the dilution guard priced
        mainnet's deep book at 0.0031% slippage while the order went to a testnet
        book with no bids at all, leaving a position that could never be closed.
        Read prices and depth from the venue you are actually going to hit.
        """
        return config.get(f"apis.{venue}.network", "testnet")

    def _current_price(self, coin, network):
        mids = requests.post(_HL_INFO[network], json={"type": "allMids"},
                             timeout=20).json()
        return float(mids[coin])

    def _free_collateral(self, coin=None):
        """Live free collateral (USD) from BOTH trading accounts, on the network
        each venue is configured to trade on. Read-only (public, needs only the
        account address). Returns (hl_free, dydx_free), or (None, None) on failure.

        `coin` selects the dYdX SUBACCOUNT. Under position isolation each coin has
        its own, separately funded — so sizing an ETH leg against subaccount 0's
        collateral would size against money the ETH order cannot touch, and the
        venue would reject the leg (or fill a smaller one than the hedge needs).
        """
        try:
            hl_net = config.get("apis.hyperliquid.network", "testnet")
            hl_addr = config.get(f"apis.hyperliquid.{hl_net}.account_address")
            st = requests.post(_HL_INFO[hl_net], json={
                "type": "clearinghouseState", "user": hl_addr}, timeout=20).json()
            ms = st.get("marginSummary", {})
            hl_free = float(ms.get("accountValue", 0)) - float(
                ms.get("totalMarginUsed", 0))

            dy_net = config.get("apis.dydx.network", "testnet")
            dy_addr = config.get(f"apis.dydx.{dy_net}.account_address")
            d = requests.get(
                f"{_DYDX_INDEXER[dy_net]}/v4/addresses/{dy_addr}", timeout=20).json()
            subs = d.get("subaccounts") or []
            want = self._dydx_subaccount_for(coin) if coin is not None else None
            if want is not None:
                target = next((s for s in subs
                               if s.get("subaccountNumber") == want), None)
                if target is None:
                    # Mapped but not funded yet: report 0 rather than another
                    # subaccount's money, so sizing refuses instead of over-sizing.
                    self.logger.warning(
                        f"dydx subaccount {want} for {coin} has no collateral yet"
                        " — fund it before opening this coin")
                    return hl_free, 0.0
            else:
                target = subs[0] if subs else None
            dydx_free = float(target.get("freeCollateral", 0)) if target else 0.0
            return hl_free, dydx_free
        except Exception as e:
            self.logger.warning(f"free-collateral read failed: {e}")
            return None, None

    def decide_exit(self, coin="BTC", funding_network="mainnet", lookback_days=30):
        """Should an OPEN carry position be closed? The other half of `decide`.

        Implements the exit the backtest has always modelled (see `backtest`:
        ``want = sign(sig) if |sig| > thresh else 0``, closing whenever
        ``want != pos``). `decide` is stateless and can only ever say open/sit_out,
        so without this the live system enters and never leaves.

        Verdict is flat, with `skip_close` for the plan's avoid_step_if gate:
          close -> the smoothed edge decayed inside the band, or flipped sign
          hold  -> still being paid on the side we hold
          none  -> nothing to close (flat), or not ours to touch (broken hedge)

        The exit threshold defaults to the ENTRY threshold, matching the backtest
        exactly. `trading.carry_engine.exit_threshold_annual_pct` can lower it to
        add hysteresis (fewer round trips), but that is NOT what was backtested.
        """
        # mainnet by default, exactly like `decide`: testnet funding is thin and
        # artificial, and entry/exit MUST read the same signal or they disagree.
        c = config.get("trading.carry_engine", {}) or {}
        thresh_pct = float(c.get("exit_threshold_annual_pct",
                                 self.default_threshold_pct))
        span = self.default_span_hours

        side, pos_detail = self._current_side(coin)
        base = {"coin": coin, "funding_network": funding_network,
                "position": pos_detail,
                "exit_threshold_annual_pct": thresh_pct}
        if side is None:
            return {**base, "action": "none", "skip_close": True,
                    "reason": pos_detail.get("note")
                              or pos_detail.get("error")
                              or "position could not be confirmed — not closing"}
        if side == 0:
            return {**base, "action": "none", "skip_close": True,
                    "reason": "no open position to close"}

        try:
            hl = self._hl_funding_history(coin, funding_network, int(lookback_days * 24))
            dy = self._dydx_funding_history(coin, funding_network, int(lookback_days * 24))
        except Exception as e:
            # Never close on a failed read: an unreadable signal is not a reason to
            # abandon a position that is still being paid.
            return {**base, "action": "hold", "skip_close": True,
                    "reason": f"funding history fetch failed, holding: {e}"}
        common = sorted(set(hl) & set(dy))
        if len(common) < span + 2:
            return {**base, "action": "hold", "skip_close": True,
                    "samples": len(common),
                    "reason": f"insufficient aligned history ({len(common)}h), holding"}

        spread = [hl[t] - dy[t] for t in common]  # +ve => HL funds higher
        smoothed = self._ema(spread, span)
        thresh_hourly = thresh_pct / 100.0 / HOURS_PER_YEAR
        want = 1 if smoothed > thresh_hourly else (-1 if smoothed < -thresh_hourly else 0)

        verdict = {
            **base,
            "samples": len(common),
            "current_side": side,
            "wanted_side": want,
            "smoothed_spread_annual_pct": round(smoothed * HOURS_PER_YEAR * 100, 3),
            "smoothing_span_hours": span,
        }
        if want == side:
            return {**verdict, "action": "hold", "skip_close": True,
                    "reason": "smoothed edge still clears the threshold on the side"
                              " we hold"}
        if want == 0:
            return {**verdict, "action": "close", "skip_close": False,
                    "reason": "smoothed edge decayed inside the threshold band —"
                              " no longer paid for the risk"}
        return {**verdict, "action": "close", "skip_close": False,
                "reason": "smoothed spread flipped sign — close now; the entry plan"
                          " re-opens on the other side"}

    def _size_position(self, price, leverage, capital_usd, coin=None):
        """Return (size, sizing_detail). Primary rule: each leg's margin is capped
        at max_account_margin_pct% of the SMALLER account's free collateral, so
        both matched legs stay within that budget with a liquidation buffer. Also
        clamped by the hard notional cap. Falls back to capital_usd if balances
        can't be read (so nothing silently mis-sizes)."""
        hard_cap = config.get("trading.executor.max_order_notional_usd")
        hard_cap = float(hard_cap) if hard_cap is not None else None
        hl_free, dydx_free = self._free_collateral(coin)

        if hl_free is not None and dydx_free is not None:
            pct = float(config.get("trading.max_account_margin_pct", 50))
            binding = min(hl_free, dydx_free)
            margin_per_leg = pct / 100.0 * binding
            margin_notional = margin_per_leg * leverage
            notional = margin_notional
            capped_by = "margin_rule"
            if hard_cap is not None and hard_cap < notional:
                notional, capped_by = hard_cap, "hard_notional_cap"
            detail = {
                "method": "margin_rule",
                "binding_account": "hyperliquid" if hl_free <= dydx_free else "dydx",
                "hl_free_collateral": round(hl_free, 2),
                "dydx_free_collateral": round(dydx_free, 2),
                "margin_pct": pct, "margin_per_leg": round(margin_per_leg, 2),
                "margin_notional_per_leg": round(margin_notional, 2),
                "hard_notional_cap": hard_cap,
                "effective_notional_per_leg": round(notional, 2),
                "capped_by": capped_by,
            }
        else:
            notional = (capital_usd or 500.0) * leverage
            if hard_cap is not None and hard_cap < notional:
                notional = hard_cap
            detail = {"method": "capital_fallback",
                      "reason": "could not read account balances",
                      "effective_notional_per_leg": round(notional, 2),
                      "hard_notional_cap": hard_cap}
        # FLOOR, never round: the notional above is a hard ceiling, so rounding the
        # size up breaches it. round(300/64106.5, 6) = 0.00468 is $300.02 — enough
        # for the daemon's cap to refuse the leg, which is exactly what happened on
        # 2026-07-16 (run 331efb33). Flooring can only ever size under the cap.
        size = math.floor(notional / price * 1e6) / 1e6
        detail["notional_at_ref"] = round(size * price, 2)
        return size, detail

    @staticmethod
    def _walk_book(levels, mid, notional, side):
        """Avg-fill slippage vs mid (fraction) to fill *notional* USD. side 'buy'
        walks asks, 'sell' walks bids. None if the book can't absorb the size."""
        remaining, filled_usd, base = notional, 0.0, 0.0
        for px, sz in levels:
            take = min(remaining, px * sz)
            if take <= 0:
                continue
            base += take / px
            filled_usd += take
            remaining -= take
            if remaining <= 0:
                break
        if base <= 0 or remaining > 0:  # empty or book too thin for the size
            return None
        return abs(filled_usd / base - mid) / mid

    def _venue_book(self, coin, venue, network):
        if venue == "hyperliquid":
            b = requests.post(_HL_INFO[network], json={
                "type": "l2Book", "coin": coin}, timeout=20).json()["levels"]
            bids = [(float(x["px"]), float(x["sz"])) for x in b[0]]
            asks = [(float(x["px"]), float(x["sz"])) for x in b[1]]
        else:
            b = requests.get(
                f"{_DYDX_INDEXER[network]}/v4/orderbooks/perpetualMarket/{coin}-USD",
                timeout=20).json()
            bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
            asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
        mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else None
        return bids, asks, mid

    def _round_trip_slippage(self, coin, short_venue, long_venue, notional):
        """Full round-trip slippage as a fraction of notional. (fraction|None, detail).

        FOUR book walks, not two doubled:
            entry: sell into short venue's BIDS, buy into long venue's ASKS
            exit:  buy back into short venue's ASKS, sell out into long venue's BIDS

        The old version walked only the ENTRY sides and returned 2*that, assuming
        the exit side is as deep as the entry. That assumption is exactly what
        failed on 2026-07-16: dYdX testnet had asks (we bought in fine) and no bids
        (we could never sell out). Doubling the entry cost cannot tell you whether
        you can GET OUT — and being unable to exit is the whole risk.

        Each venue's book comes from the network THAT venue trades on; see
        _venue_network. `book_too_thin` now fires on an unfillable EXIT too, which
        is the case worth refusing.
        """
        try:
            s_net = self._venue_network(short_venue)
            l_net = self._venue_network(long_venue)
            s_bids, s_asks, smid = self._venue_book(coin, short_venue, s_net)
            l_bids, l_asks, lmid = self._venue_book(coin, long_venue, l_net)
            nets = {short_venue: s_net, long_venue: l_net}
            if not smid or not lmid:
                return None, {"note": "order book unavailable",
                              "book_networks": nets}

            # (levels, mid, side) — _walk_book's `side` is documentation; the levels
            # passed are what decide the walk.
            walks = {
                f"entry_sell_{short_venue}": (s_bids, smid, "sell"),
                f"entry_buy_{long_venue}": (l_asks, lmid, "buy"),
                f"exit_buy_{short_venue}": (s_asks, smid, "buy"),
                f"exit_sell_{long_venue}": (l_bids, lmid, "sell"),
            }
            slips = {name: self._walk_book(lv, mid, notional, side)
                     for name, (lv, mid, side) in walks.items()}

            unfillable = [n for n, v in slips.items() if v is None]
            if unfillable:
                return None, {
                    "note": "book too thin to fill this size: "
                            + ", ".join(unfillable),
                    "book_too_thin": True,
                    "unfillable": unfillable,
                    "book_networks": nets,
                }
            total = sum(slips.values())
            detail = {n: round(v * 1e4, 3) for n, v in slips.items()}
            detail.update({
                "round_trip_slip_pct_notional": round(total * 100, 4),
                "measured": "all four legs (entry + exit), not entry doubled",
                "book_networks": nets,
            })
            return total, detail
        except Exception as e:
            return None, {"note": f"slippage estimate failed: {e}"}

    def decide(self, coin="BTC", capital_usd=500.0, lookback_days=30,
               funding_network="mainnet") -> Dict[str, Any]:
        """Fetch aligned funding history for both venues and return a flat verdict
        (with a `sit_out` boolean for the plan's avoid_step_if gate).

        `funding_network` is the SIGNAL source only (mainnet — testnet funding is
        artificial). Price and book depth come from each venue's own trading
        network via _venue_network(); do not pass funding_network to either.
        """
        hours = int(lookback_days * 24)
        try:
            hl = self._hl_funding_history(coin, funding_network, hours)
            dy = self._dydx_funding_history(coin, funding_network, hours)
        except Exception as e:
            return {"action": "sit_out", "sit_out": True, "coin": coin,
                    "reason": f"funding history fetch failed: {e}"}
        common = sorted(set(hl) & set(dy))
        if len(common) < self.default_span_hours + 2:
            return {"action": "sit_out", "sit_out": True, "coin": coin,
                    "reason": f"insufficient aligned history ({len(common)}h)",
                    "samples": len(common)}
        fa = [hl[t] for t in common]
        fb = [dy[t] for t in common]
        ev = self.evaluate("hyperliquid", "dydx", fa, fb, capital_usd=capital_usd)

        verdict = {
            "coin": coin, "capital_usd": capital_usd, "samples": len(common),
            # Two DIFFERENT networks, reported separately so they can never be
            # silently conflated again: the signal's, and the ones we trade on.
            "funding_network": funding_network,
            "trading_networks": {v: self._venue_network(v)
                                 for v in ("hyperliquid", "dydx")},
            "action": ev["action"],
            "sit_out": ev["action"] == "sit_out",
            "smoothed_spread_annual_pct": ev.get("smoothed_spread_annual_pct"),
            "reason": ev.get("reason", "smoothed edge clears threshold"),
        }
        if ev["action"] == "open":
            # Price from the network we TRADE on, not the one we read funding from.
            # This is the reference the executor prices both legs against, so it
            # must come from a book that can actually fill us.
            trade_net = self._venue_network("hyperliquid")
            price = self._current_price(coin, trade_net)
            size, sizing = self._size_position(price, ev["leverage"],
                                               capital_usd, coin=coin)
            notional = size * price

            # Book-wide exposure gate: bounds the WHOLE book (every other coin
            # currently open), which nothing else here does — the margin rule
            # and hard cap above only ever bound THIS one position. Checked
            # before the dilution guard since it's the cheaper, more decisive
            # question: no point pricing slippage for a coin the book has no
            # room left for. The executor daemon independently re-checks this
            # at open time (server._book_cap_check) — same "engine sizes, daemon
            # backstops" split as every other cap.
            max_positions = config.get("trading.max_concurrent_positions", 5)
            max_book_notional = config.get("trading.max_book_notional_usd")
            if max_positions is not None or max_book_notional is not None:
                book_count, book_notional = self._book_state(exclude_coin=coin)
                if book_count is None:
                    verdict["action"] = "sit_out"
                    verdict["sit_out"] = True
                    verdict["reason"] = (
                        "could not read the book-wide position count — sitting"
                        " out rather than risking an uncapped book (book-wide"
                        " exposure gate)")
                    return verdict
                verdict["book"] = {"open_positions": book_count,
                                   "book_notional_usd": round(book_notional, 2)}
                if max_positions is not None and book_count + 1 > int(max_positions):
                    verdict["action"] = "sit_out"
                    verdict["sit_out"] = True
                    verdict["reason"] = (
                        f"opening {coin} would bring concurrent positions to"
                        f" {book_count + 1}, exceeding"
                        f" trading.max_concurrent_positions"
                        f" ({int(max_positions)}) — sitting out (book-wide"
                        f" exposure gate)")
                    return verdict
                if (max_book_notional is not None
                        and (book_notional + notional) > float(max_book_notional)):
                    verdict["action"] = "sit_out"
                    verdict["sit_out"] = True
                    verdict["reason"] = (
                        f"opening {coin} would bring total book notional to"
                        f" ${book_notional + notional:,.2f}, exceeding"
                        f" trading.max_book_notional_usd"
                        f" (${float(max_book_notional):,.2f}) — sitting out"
                        f" (book-wide exposure gate)")
                    return verdict

            # Dilution guard: does the edge survive fees AND slippage at THIS size?
            hold_days = 14.0
            slip_frac, slip_detail = self._round_trip_slippage(
                coin, ev["short_venue"], ev["long_venue"], notional)
            verdict["sizing"] = sizing
            verdict["slippage"] = slip_detail

            if slip_detail.get("book_too_thin"):
                # size exceeds what the book can absorb — never trade into that
                verdict["action"] = "sit_out"
                verdict["sit_out"] = True
                verdict["reason"] = (
                    "order size exceeds available order-book depth — sitting out"
                    " (dilution guard)")
                return verdict

            if slip_frac is None:
                # Slippage could not be measured at all — an empty or unreadable
                # book. This used to default to 0.0, i.e. the most OPTIMISTIC
                # assumption available, which is how run e8868482 opened against a
                # dYdX testnet book with no bids: unmeasurable cost read as free.
                # A guard that cannot see must refuse, not wave you through.
                verdict["action"] = "sit_out"
                verdict["sit_out"] = True
                verdict["reason"] = (
                    "could not measure order-book slippage"
                    f" ({slip_detail.get('note')}) — sitting out rather than"
                    " assuming it is free (dilution guard)")
                return verdict

            slip = slip_frac
            gross_over_hold = (ev["gross_edge_annual_pct"] / 100.0) * (
                hold_days / 365.0)
            fees_frac = ev["round_trip_cost_pct_notional"] / 100.0
            net_over_hold = gross_over_hold - fees_frac - slip
            verdict["net_after_costs_pct_notional_over_hold"] = round(
                net_over_hold * 100, 4)

            if net_over_hold <= 0:
                verdict["action"] = "sit_out"
                verdict["sit_out"] = True
                verdict["reason"] = (
                    "net edge non-positive after fees + slippage at this size —"
                    " sitting out (dilution guard)")
            else:
                verdict.update({
                    "short_venue": ev["short_venue"], "long_venue": ev["long_venue"],
                    "short_symbol": (coin if ev["short_venue"] == "hyperliquid"
                                     else f"{coin}-USD"),
                    "long_symbol": (coin if ev["long_venue"] == "hyperliquid"
                                    else f"{coin}-USD"),
                    "size": size, "ref_price": price, "leverage": ev["leverage"],
                    "net_annual_pct_on_capital_if_spread_holds":
                        ev.get("net_annual_pct_on_capital_if_spread_holds"),
                })
        return verdict

    async def run(
        self,
        action: Annotated[
            Literal["decide", "decide_exit", "evaluate", "backtest"],
            "'decide' = self-contained: fetch history for `coin` and return an"
            " actionable open/sit-out verdict (for orchestration); 'decide_exit' ="
            " the mirror: should an OPEN position be closed now (close/hold/none);"
            " 'evaluate' / 'backtest' = operate on supplied funding arrays",
        ] = "decide",
        coin: Annotated[str, "Coin for 'decide', e.g. BTC, ETH, SOL"] = "BTC",
        capital_usd: Annotated[
            Optional[float], "Capital to size the position against, USD"
        ] = 500.0,
        funding_a_hourly: Annotated[
            Optional[List[float]],
            "For evaluate/backtest: hourly funding for venue A, oldest-first",
        ] = None,
        funding_b_hourly: Annotated[
            Optional[List[float]], "For evaluate/backtest: venue B, aligned"
        ] = None,
        venue_a: Annotated[str, "Name of venue A"] = "hyperliquid",
        venue_b: Annotated[str, "Name of venue B"] = "dydx",
        expected_hold_days: Annotated[
            float, "Expected holding period in days, to amortize entry/exit fees"
        ] = 14.0,
        exit_threshold_annual_pct: Annotated[
            Optional[float],
            "For 'backtest': separate (typically LOWER) exit threshold to test"
            " hysteresis. None = same as the entry threshold (old behavior).",
        ] = None,
        min_hold_hours: Annotated[
            float,
            "For 'backtest': hold a position at least this many hours before an"
            " exit signal is honored, to test whether a floor cuts fee churn"
            " from short noisy round trips. 0 = no floor (old behavior).",
        ] = 0.0,
    ) -> Dict[str, Any]:
        """Decide a delta-neutral carry action (self-contained), or evaluate/backtest
        supplied funding arrays."""
        if action == "decide":
            return self.decide(coin=coin, capital_usd=capital_usd or 500.0)
        if action == "decide_exit":
            return self.decide_exit(coin=coin)
        if funding_a_hourly is None or funding_b_hourly is None:
            return {"error": f"action '{action}' requires funding_a_hourly and "
                    "funding_b_hourly arrays"}
        if action == "backtest":
            return self.backtest(venue_a, venue_b, funding_a_hourly, funding_b_hourly,
                                 exit_threshold_annual_pct=exit_threshold_annual_pct,
                                 min_hold_hours=min_hold_hours)
        return self.evaluate(venue_a, venue_b, funding_a_hourly, funding_b_hourly,
                             capital_usd=capital_usd,
                             expected_hold_days=expected_hold_days)
