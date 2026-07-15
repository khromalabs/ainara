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
        leverage: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Walk the full aligned history hour by hour: gate on the smoothed spread,
        accrue the REALIZED spread while positioned, and charge fees on every
        entry and exit. This is the honest expected-return estimate — unlike
        evaluate(), it does not assume the current spread persists.
        """
        span = span_hours or self.default_span_hours
        thresh_pct = (
            threshold_annual_pct
            if threshold_annual_pct is not None
            else self.default_threshold_pct
        )
        lev = leverage if leverage is not None else self.default_leverage

        n = min(len(funding_a_hourly), len(funding_b_hourly))
        if n < span + 2:
            return {"error": f"Need at least {span + 2} aligned samples to backtest"}
        a = funding_a_hourly[-n:]
        b = funding_b_hourly[-n:]
        spread = [a[i] - b[i] for i in range(n)]
        sig = self._ema_series(spread, span)
        thresh_hourly = thresh_pct / 100.0 / HOURS_PER_YEAR
        # per-leg-pair cost of one entry OR one exit across both legs
        leg_event_cost = self.fee_per_leg.get(venue_a, 0.0005) + self.fee_per_leg.get(
            venue_b, 0.0005
        )

        pos, gross, fees, entries, held = 0, 0.0, 0.0, 0, 0
        for i in range(n):
            want = 1 if sig[i] > thresh_hourly else (-1 if sig[i] < -thresh_hourly else 0)
            if want != pos:
                if pos != 0:
                    fees += leg_event_cost  # exit
                if want != 0:
                    fees += leg_event_cost  # entry
                    entries += 1
                pos = want
            if pos != 0:
                gross += spread[i] * pos  # realized spread, signed by our side
                held += 1

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
            "gross_annual_pct_notional": round(gross_ann * 100, 3),
            "fees_annual_pct_notional": round(fees_ann * 100, 3),
            "net_annual_pct_notional": round(net_ann * 100, 3),
            "net_annual_pct_on_capital": round(net_ann * lev * 100, 3),
            "leverage": lev,
            "smoothing_span_hours": span,
            "enter_threshold_annual_pct": thresh_pct,
        }

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Self-contained decision (fetches its own history — for orchestration)
    # ------------------------------------------------------------------

    def _hl_funding_history(self, coin, network, hours):
        """HL hourly funding (oldest-first) as {hour_ms: rate}."""
        start = int(time.time() * 1000) - hours * HOUR_MS
        rows = requests.post(_HL_INFO[network], json={
            "type": "fundingHistory", "coin": coin, "startTime": start},
            timeout=30).json()
        return {int(r["time"]) - (int(r["time"]) % HOUR_MS): float(r["fundingRate"])
                for r in rows}

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

    def _current_price(self, coin, network):
        mids = requests.post(_HL_INFO[network], json={"type": "allMids"},
                             timeout=20).json()
        return float(mids[coin])

    def decide(self, coin="BTC", capital_usd=500.0, lookback_days=30,
               funding_network="mainnet") -> Dict[str, Any]:
        """Fetch aligned funding history for both venues and return a flat verdict
        (with a `sit_out` boolean for the plan's avoid_step_if gate)."""
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
            "funding_network": funding_network,
            "action": ev["action"],
            "sit_out": ev["action"] == "sit_out",
            "smoothed_spread_annual_pct": ev.get("smoothed_spread_annual_pct"),
            "reason": ev.get("reason", "smoothed edge clears threshold"),
        }
        if ev["action"] == "open":
            price = self._current_price(coin, funding_network)
            notional = capital_usd * ev["leverage"]
            size = round(notional / price, 4)
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
            Literal["decide", "evaluate", "backtest"],
            "'decide' = self-contained: fetch history for `coin` and return an"
            " actionable open/sit-out verdict (for orchestration); 'evaluate' /"
            " 'backtest' = operate on supplied funding arrays",
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
    ) -> Dict[str, Any]:
        """Decide a delta-neutral carry action (self-contained), or evaluate/backtest
        supplied funding arrays."""
        if action == "decide":
            return self.decide(coin=coin, capital_usd=capital_usd or 500.0)
        if funding_a_hourly is None or funding_b_hourly is None:
            return {"error": f"action '{action}' requires funding_a_hourly and "
                    "funding_b_hourly arrays"}
        if action == "backtest":
            return self.backtest(venue_a, venue_b, funding_a_hourly, funding_b_hourly)
        return self.evaluate(venue_a, venue_b, funding_a_hourly, funding_b_hourly,
                             capital_usd=capital_usd,
                             expected_hold_days=expected_hold_days)
