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

"""Read-only status + review of the delta-neutral funding-carry positions.

Answers two questions, and nothing that moves money:
  - status: what is open RIGHT NOW — is it hedged, how close to liquidation, and
    what is it earning or paying this hour.
  - review: what has already CLOSED — reconstructs completed round-trips from each
    venue's own public history (fills + funding payments) so the model can reflect
    on whether the strategy actually earned out, not just what it was predicted to.

Deliberately key-free and daemon-free: every read is a PUBLIC venue endpoint keyed
by the account address in config, so it still works when the executor daemon is
down — which is exactly the moment you most want to see an unmanaged position. It
holds no keys, places no orders, and carries no jurisdiction gate (like the other
read-only trading data skills).

The funding-direction math here is the convention settled empirically against real
2026-07-22 mainnet payments on BOTH venues (do not "correct" it from first
principles): a position's per-hour funding cash-flow is

    receive_per_hour = -signed_size * rate * mark          # + = you RECEIVE

For a Hyperliquid short (szi<0) at a positive rate this is positive (a short is
paid when funding is positive); for a dYdX long (size>0) at a negative rate it is
positive (a long is paid when funding is negative). Both were reproduced to the
cent against the venues' own settled payments.
"""

import datetime
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional

import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill
from ainara.orakle.skills.trading import _ledger

HOURS_PER_YEAR = 24 * 365
DAYS_PER_YEAR = 365.0
# Below this hold, annualizing a realized rate amplifies noise (a handful of
# funding hours, or the fixed round-trip fee, scaled to a year) — so realized-vs-
# predicted RATE metrics are only trusted past it. Raw dollars are always reported.
MIN_RELIABLE_HOLD_DAYS = 1.0

# Ordering for rolling several coins' hedge health up to one book-wide verdict.
_HEALTH_RANK = {"flat": 0, "ok": 1, "warn": 2, "critical": 3}

_HL_INFO = {
    "mainnet": "https://api.hyperliquid.xyz/info",
    "testnet": "https://api.hyperliquid-testnet.xyz/info",
}
_DYDX_INDEXER = {
    "mainnet": "https://indexer.dydx.trade",
    "testnet": "https://indexer.v4testnet.dydx.exchange",
}


def _dydx_liquidation_price(equity, size_signed, mark_px, mmf):
    """Cross-margin liquidation price for a SINGLE-position dYdX subaccount.

    dYdX does not hand out a liquidationPx (Hyperliquid does), so derive it. dYdX
    v4 is cross-margined per subaccount: liquidation triggers once equity falls to
    the maintenance margin requirement. With one open position,

        P = (equity - size*mark) / (|size|*mmf - size)

    Returns None when price alone can never liquidate the leg (e.g. a long whose
    equity exceeds its notional) — "no reachable liquidation", NOT "unknown". This
    mirrors executor/venues/dydx.liquidation_price, which is validated to reproduce
    Hyperliquid's own reported liq to the dollar; kept in sync by hand because the
    executor lives in a separate venv this skill cannot import.

    SINGLE-POSITION ONLY: with several positions in one subaccount the MMR is the
    sum across them, so _dydx_leg does NOT call this then — it degrades to
    "liquidation unknown", mirroring executor/venues/dydx.state().
    """
    s = float(size_signed)
    mark_px = float(mark_px)
    if not s or mark_px <= 0:
        return None
    denom = abs(s) * float(mmf) - s
    if denom == 0:
        return None
    p = (float(equity) - s * mark_px) / denom
    if p <= 0:
        return None
    if s > 0 and p >= mark_px:
        return None
    if s < 0 and p <= mark_px:
        return None
    return p


class TradingPortfolio(Skill):
    """Read-only status and post-mortem review of the delta-neutral carry book.

    Aggregates the two venue legs into one picture a human can read: whether the
    hedge is intact and balanced, how far each leg sits from liquidation, and the
    live funding cash-flow. Its `review` action reconstructs already-closed
    round-trips from public venue history so the strategy can be judged on realized
    results. No keys, no orders, no daemon dependency.
    """

    matcher_info = (
        "Use this skill to CHECK or REVIEW the delta-neutral funding-carry"
        " (cross-venue perpetual) positions on Hyperliquid and dYdX: whether the"
        " position is open and hedged, how balanced the two legs are, how close"
        " each leg is to liquidation, how much funding it is earning or paying"
        " right now, and its unrealized PnL. Also use it to REVIEW closed trades"
        " and reflect on performance: realized net, funding captured, fees, and"
        " how long positions were held. Read-only; it never opens or closes"
        " anything. Keywords: position status, how is my trade doing, am I hedged,"
        " funding earned, carry PnL, review my trades, closed positions, trading"
        " performance, how did the strategy do. Handles a SINGLE asset (BTC, ETH,"
        " SOL) or the WHOLE BOOK at once (all positions / my portfolio / how is"
        " everything doing) via coin='ALL'."
    )

    def __init__(self):
        super().__init__()
        self.name = "portfolio"
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # config / addresses
    # ------------------------------------------------------------------
    def _target(self, venue):
        """(network, account_address) for a venue, from the SAME config the
        executor trades on — so status reads exactly the account that is live."""
        network = config.get(f"apis.{venue}.network", "mainnet")
        addr = config.get(f"apis.{venue}.{network}.account_address")
        return network, addr

    # ------------------------------------------------------------------
    # live venue reads (public /info and indexer — no keys)
    # ------------------------------------------------------------------
    def _hl_leg(self, coin):
        """Normalize the Hyperliquid position for `coin`, or a flat leg."""
        network, addr = self._target("hyperliquid")
        if not addr:
            return {"venue": "hyperliquid", "error": "no account_address in config"}
        base = _HL_INFO[network]
        st = requests.post(base, json={"type": "clearinghouseState", "user": addr},
                           timeout=20).json()
        acct_value = float(st.get("marginSummary", {}).get("accountValue", 0) or 0)
        leg = {"venue": "hyperliquid", "network": network, "coin": coin,
               "account_value": acct_value, "size": 0.0, "open": False}
        for p in st.get("assetPositions", []):
            pos = p.get("position", {})
            if pos.get("coin") != coin:
                continue
            szi = float(pos.get("szi", 0) or 0)
            pos_val = float(pos.get("positionValue", 0) or 0)
            mark = pos_val / abs(szi) if szi else None
            liq = pos.get("liquidationPx")
            liq = float(liq) if liq is not None else None
            leg.update({
                "open": abs(szi) > 0, "size": szi, "side": "long" if szi > 0 else "short",
                "entry_px": _f(pos.get("entryPx")), "mark_px": mark,
                "liquidation_px": liq,
                "liq_distance_pct": (abs(mark - liq) / mark * 100)
                if (liq and mark) else None,
                "unrealized_pnl": _f(pos.get("unrealizedPnl")),
            })
        return leg

    def _dydx_leg(self, coin):
        """Normalize the dYdX position for `<coin>-USD`, or a flat leg. Liquidation
        is DERIVED (dYdX gives no liq), and reports why when it can't be."""
        network, addr = self._target("dydx")
        if not addr:
            return {"venue": "dydx", "error": "no account_address in config"}
        indexer = _DYDX_INDEXER[network]
        market = f"{coin}-USD"
        r = requests.get(f"{indexer}/v4/addresses/{addr}", timeout=20).json()
        subs = r.get("subaccounts") or []
        leg = {"venue": "dydx", "network": network, "coin": market,
               "size": 0.0, "open": False}
        if not subs:
            leg["note"] = "no subaccount yet (unfunded)"
            return leg
        s = subs[0]
        equity = float(s.get("equity", 0) or 0)
        leg["account_value"] = equity
        open_perps = s.get("openPerpetualPositions") or {}
        pos = open_perps.get(market)
        if not pos:
            return leg
        sz = abs(float(pos.get("size", 0) or 0))
        signed = sz if pos.get("side") == "LONG" else -sz
        mark, mmf = self._dydx_market_risk(indexer, market)
        liq = liq_dist = note = None
        # dYdX is cross-margined per subaccount: with more than one open position
        # the maintenance-margin requirement is the SUM across them, so the
        # single-position formula below reads OPTIMISTICALLY safe. Mirror the
        # executor's dydx.state() and report "unknown" rather than a misleadingly
        # rosy distance. (Proper fix: isolate each coin in its own subaccount.)
        multi = sum(1 for p in open_perps.values()
                    if abs(float(p.get("size", 0) or 0)) > 0) > 1
        if mark is None:
            note = "liquidation unknown: market risk params unavailable"
        elif multi:
            note = ("liquidation unknown: multiple positions share this"
                    " cross-margin subaccount — single-position formula is not"
                    " valid, this leg is unmonitored")
        else:
            liq = _dydx_liquidation_price(equity, signed, mark, mmf)
            if liq is None:
                note = "not liquidatable by price alone (equity exceeds notional)"
            else:
                liq_dist = abs(mark - liq) / mark * 100
        leg.update({
            "open": sz > 0, "size": signed,
            "side": "long" if signed > 0 else "short",
            "entry_px": _f(pos.get("entryPrice")), "mark_px": mark,
            "liquidation_px": liq, "liq_distance_pct": liq_dist,
            "unrealized_pnl": _f(pos.get("unrealizedPnl")), "liq_note": note,
        })
        return leg

    @staticmethod
    def _dydx_market_risk(indexer, market):
        """(oracle_price, maintenance_margin_fraction) for a dYdX market."""
        try:
            md = requests.get(
                f"{indexer}/v4/perpetualMarkets?ticker={market}", timeout=20
            ).json()["markets"][market]
            return float(md["oraclePrice"]), float(md["maintenanceMarginFraction"])
        except Exception as e:
            logging.getLogger(__name__).warning(
                "dydx market risk unavailable for %s: %s", market, e)
            return None, None

    def _latest_funding(self, venue, coin):
        """Most recent HOURLY funding rate for `coin` on `venue` (a fraction),
        used as the live earn/pay rate. None if unreadable."""
        try:
            if venue == "hyperliquid":
                network, _ = self._target("hyperliquid")
                start = int((time.time() - 6 * 3600) * 1000)
                rows = requests.post(_HL_INFO[network], json={
                    "type": "fundingHistory", "coin": coin, "startTime": start,
                }, timeout=20).json()
                return float(rows[-1]["fundingRate"]) if rows else None
            network, _ = self._target("dydx")
            rows = requests.get(
                f"{_DYDX_INDEXER[network]}/v4/historicalFunding/{coin}-USD?limit=1",
                timeout=20).json().get("historicalFunding", [])
            return float(rows[0]["rate"]) if rows else None
        except Exception as e:
            self.logger.warning("latest funding unavailable %s/%s: %s",
                                venue, coin, e)
            return None

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def _status(self, coin, size_tol_pct):
        hl, dy = self._hl_leg(coin), self._dydx_leg(coin)
        legs = {"hyperliquid": hl, "dydx": dy}

        hl_open, dy_open = hl.get("open"), dy.get("open")
        hl_sz, dy_sz = float(hl.get("size", 0) or 0), float(dy.get("size", 0) or 0)

        # Hedge verdict — the one line a human actually wants.
        if not hl_open and not dy_open:
            verdict, health = "flat — no open position", "flat"
        elif hl_open != dy_open:
            naked = "hyperliquid" if hl_open else "dydx"
            verdict = f"BROKEN HEDGE: only {naked} holds a leg — naked directional"
            health = "critical"
        elif (hl_sz > 0) == (dy_sz > 0):
            verdict = "NOT DELTA-NEUTRAL: both legs are the same direction"
            health = "critical"
        else:
            imb = abs(abs(hl_sz) - abs(dy_sz)) / max(abs(hl_sz), abs(dy_sz)) * 100
            if imb > size_tol_pct:
                verdict = (f"IMBALANCED: legs differ by {imb:.1f}% — net "
                           f"{'long' if hl_sz + dy_sz > 0 else 'short'} "
                           f"{abs(hl_sz + dy_sz):.6f} {coin} unhedged")
                health = "warn"
            else:
                verdict = "hedged and balanced"
                health = "ok"

        # Live funding cash-flow. -size*rate*mark; + means the leg is being PAID.
        economics = {"net_funding_per_hour_usd": None}
        per_leg = {}
        net_hr = 0.0
        measurable = True
        for name, leg in legs.items():
            if not leg.get("open"):
                continue
            rate = self._latest_funding(name, coin)
            mark = leg.get("mark_px")
            if rate is None or not mark:
                per_leg[name] = {"funding_rate_hourly": rate, "note":
                                 "funding cash-flow unmeasurable (missing rate/mark)"}
                measurable = False
                continue
            recv_hr = -float(leg["size"]) * rate * float(mark)
            per_leg[name] = {
                "funding_rate_hourly_pct": round(rate * 100, 5),
                "funding_rate_annual_pct": round(rate * HOURS_PER_YEAR * 100, 2),
                "you_receive_per_hour_usd": round(recv_hr, 5),
                "side": leg.get("side"),
            }
            net_hr += recv_hr
        if per_leg:
            economics = {
                "per_leg": per_leg,
                "net_funding_per_hour_usd": round(net_hr, 5) if measurable else None,
                "net_funding_per_day_usd": round(net_hr * 24, 4) if measurable else None,
                "net_funding_annual_usd": round(net_hr * HOURS_PER_YEAR, 2)
                if measurable else None,
                "note": None if measurable else
                "one or more legs' funding could not be read; net is incomplete",
            }

        unrl = _sum_optional(hl.get("unrealized_pnl"), dy.get("unrealized_pnl"))
        return {
            "action": "status", "coin": coin, "health": health, "verdict": verdict,
            "net_delta": round(hl_sz + dy_sz, 8),
            "legs": legs,
            "economics": economics,
            "combined_unrealized_pnl_usd": unrl,
            "liquidation": {
                "hyperliquid_distance_pct": hl.get("liq_distance_pct"),
                "dydx_distance_pct": dy.get("liq_distance_pct"),
                "dydx_note": dy.get("liq_note"),
            },
            "as_of": _now_iso(),
        }

    # ------------------------------------------------------------------
    # review (closed round-trips, reconstructed from public history)
    # ------------------------------------------------------------------
    def _review(self, coin, lookback_days):
        since_ms = int((time.time() - lookback_days * 86400) * 1000)
        hl_eps = self._episodes_hl(coin, since_ms)
        dy_eps = self._episodes_dydx(coin, since_ms)

        # Pair one HL episode with one dYdX episode by time overlap: a hedge is a
        # matched pair opened and closed together. Unpaired episodes are surfaced
        # too — an unmatched leg is exactly the kind of thing worth reflecting on.
        trips, used_dy = [], set()
        for h in hl_eps:
            match, best = None, 0.0
            for i, d in enumerate(dy_eps):
                if i in used_dy:
                    continue
                ov = _overlap(h, d)
                if ov > best:
                    best, match = ov, i
            if match is not None and best > 0:
                used_dy.add(match)
                trips.append(self._round_trip(coin, h, dy_eps[match]))
            else:
                trips.append(self._round_trip(coin, h, None))
        for i, d in enumerate(dy_eps):
            if i not in used_dy:
                trips.append(self._round_trip(coin, None, d))

        trips.sort(key=lambda t: t.get("opened_at") or "", reverse=True)
        closed = [t for t in trips if t["status"] == "closed"]
        unpaired = [t for t in trips if t["status"] == "unpaired_closed"]
        r_closed = [t["realized_net_usd"] for t in closed
                    if t.get("realized_net_usd") is not None]
        r_all = [t["realized_net_usd"] for t in (closed + unpaired)
                 if t.get("realized_net_usd") is not None]
        summary = {
            "round_trips": len(trips),
            "hedge_round_trips_closed": len(closed),
            "unpaired_closed_legs": len(unpaired),
            "still_open": sum(1 for t in trips if t["status"] == "open"),
            # The strategy's own scorecard: complete hedges only.
            "hedge_realized_net_usd": round(sum(r_closed), 4) if r_closed else None,
            "winning_hedges": sum(1 for r in r_closed if r > 0),
            "losing_hedges": sum(1 for r in r_closed if r < 0),
            # True realized cash, INCLUDING unpaired legs (anomalies still cost money).
            "total_realized_net_usd": round(sum(r_all), 4) if r_all else None,
        }
        return {"action": "review", "coin": coin, "lookback_days": lookback_days,
                "summary": summary, "round_trips": trips, "as_of": _now_iso()}

    # ------------------------------------------------------------------
    # analytics — realized vs the prediction the engine made at entry
    # ------------------------------------------------------------------
    def _analytics(self, coin):
        """Join the ledger's PREDICTED edge against realized outcomes rebuilt from
        venue history over each trade's exact window.

        The honest comparison is RATE vs RATE, not dollars: a prediction assumes a
        ~14-day hold, so comparing its dollar total to a trade closed in hours is
        meaningless — but 'did we capture the funding EDGE we predicted' holds at
        any duration. So the headline is `funding_capture_ratio` (realized funding
        annualized ÷ predicted smoothed spread). Fees are a fixed round-trip cost
        reported separately, because annualizing them over a short hold produces a
        scary number that says nothing about the strategy — only about holding too
        briefly to clear the toll.
        """
        rows = _ledger.trades(coin=coin, status="closed")
        trades, captures, pred_spreads, real_funding_annuals = [], [], [], []
        net_total = 0.0
        for row in rows:
            lo, hi = _iso_ms(row["opened_at"]), _iso_ms(row["closed_at"])
            hold_days = max((hi - lo) / 86_400_000, 0.0)
            notional = row.get("notional_usd")
            realized = self._realized_in_window(coin, lo, hi)
            net_total += realized["net_usd"]

            # Annualizing a rate over a very short hold amplifies noise: a few lucky
            # (or unlucky) funding hours, or the fixed round-trip fee, blow up when
            # scaled to a year. So the rate metrics are only TRUSTED past a minimum
            # hold; below it we report the raw dollars and flag the rest unreliable,
            # rather than present noise as a 4x "capture".
            reliable = hold_days >= MIN_RELIABLE_HOLD_DAYS
            r_funding_annual = r_net_annual = capture = None
            if notional and hold_days > 0:
                r_funding_annual = (realized["funding_usd"] / notional
                                    / hold_days * DAYS_PER_YEAR * 100)
                r_net_annual = (realized["net_usd"] / notional
                                / hold_days * DAYS_PER_YEAR * 100)
            pred_spread = row.get("pred_smoothed_spread_annual_pct")
            if reliable and pred_spread and r_funding_annual is not None:
                capture = r_funding_annual / pred_spread
                captures.append(capture)
                pred_spreads.append(pred_spread)
                real_funding_annuals.append(r_funding_annual)

            trades.append({
                "opened_at": row["opened_at"], "closed_at": row["closed_at"],
                "hold_days": round(hold_days, 3), "notional_usd": notional,
                "exit_reason": row.get("exit_reason"),
                "annualized_metrics_reliable": reliable,
                "predicted": {
                    "smoothed_spread_annual_pct": pred_spread,
                    "net_annual_pct_on_capital": row.get(
                        "pred_net_annual_pct_on_capital"),
                    "net_over_hold_pct_notional": row.get(
                        "pred_net_over_hold_pct_notional"),
                },
                "realized": {
                    **realized,
                    "funding_annual_pct_notional": _round(r_funding_annual, 2),
                    "net_annual_pct_notional": _round(r_net_annual, 2),
                    "fees_pct_notional": _round(
                        realized["fees_usd"] / notional * 100, 4)
                    if notional else None,
                },
                "funding_capture_ratio": _round(capture, 3),
                "held_past_fee_breakeven": (hold_days >= self._fee_breakeven_days(
                    pred_spread)) if pred_spread else None,
            })

        short_held = sum(1 for t in trades
                         if not t["annualized_metrics_reliable"])
        summary = {
            "closed_trades_on_record": len(rows),
            "trades_scored": len(captures),  # only holds long enough to trust a rate
            "trades_too_short_to_score": short_held,
            "total_realized_net_usd": round(net_total, 4) if rows else None,
            "mean_predicted_spread_annual_pct": _round(_mean(pred_spreads), 2),
            "mean_realized_funding_annual_pct": _round(_mean(real_funding_annuals), 2),
            "mean_funding_capture_ratio": _round(_mean(captures), 3),
            "winners": sum(1 for t in trades
                           if (t["realized"]["net_usd"] or 0) > 0),
            "losers": sum(1 for t in trades
                          if (t["realized"]["net_usd"] or 0) < 0),
        }
        if not rows:
            summary["note"] = ("no closed trades on record yet — the ledger records"
                               " from the next real open/close onward.")
        elif not captures:
            summary["note"] = (
                f"no trade has been held past ~{MIN_RELIABLE_HOLD_DAYS:g} day(s)"
                " yet, so realized-vs-predicted RATES are not meaningful — a short"
                " hold makes both funding and fees annualize to noise. Only the raw"
                " dollars are real: over a short hold, fixed fees dominate.")
        else:
            summary["note"] = (
                "funding_capture_ratio (realized funding rate ÷ predicted) is the"
                " honest gauge, but only over trades held long enough to trust —"
                f" {short_held} short-held trade(s) are excluded from the rates.")
        return {"action": "analytics", "coin": coin, "summary": summary,
                "trades": trades, "as_of": _now_iso()}

    @staticmethod
    def _fee_breakeven_days(pred_spread_annual_pct):
        """Days the predicted funding rate needs to run to cover a round trip's
        ~0.17%-of-notional fees. Below this a close is a loss no matter the edge."""
        if not pred_spread_annual_pct or pred_spread_annual_pct <= 0:
            return float("inf")
        daily = pred_spread_annual_pct / 100.0 / DAYS_PER_YEAR
        return (0.0017 / daily) if daily else float("inf")

    # ---- raw per-venue fills (shared by episode reconstruction and window sums) ----
    def _raw_fills_hl(self, coin, since_ms):
        """Normalized HL fills for `coin` since `since_ms`, oldest→newest."""
        network, addr = self._target("hyperliquid")
        fills = requests.post(_HL_INFO[network], json={
            "type": "userFillsByTime", "user": addr, "startTime": since_ms,
        }, timeout=20).json()
        rows = []
        for f in fills:
            if f.get("coin") != coin:
                continue
            # HL 'dir' is explicit: a BUY is "Open Long" or "Close Short"; a SELL
            # is "Open Short" or "Close Long". That alone gives the signed delta.
            d = str(f.get("dir", "")).lower()
            buy = d in ("open long", "close short")
            sz = float(f["sz"])
            rows.append({"t": int(f["time"]), "sz": sz, "px": float(f["px"]),
                         "buy": buy, "signed": sz if buy else -sz,
                         "fee": float(f.get("fee", 0) or 0)})
        rows.sort(key=lambda r: r["t"])
        return rows

    def _raw_fills_dydx(self, coin, since_ms):
        """Normalized dYdX fills for `<coin>-USD` since `since_ms`, oldest→newest."""
        network, addr = self._target("dydx")
        indexer = _DYDX_INDEXER[network]
        market = f"{coin}-USD"
        fills = requests.get(
            f"{indexer}/v4/fills?address={addr}&subaccountNumber=0&limit=100",
            timeout=20).json().get("fills", [])
        rows = []
        for f in fills:
            t = _iso_ms(f["createdAt"])
            if t < since_ms or f.get("market") != market:
                continue
            sz = float(f["size"])
            buy = f["side"].upper() == "BUY"
            rows.append({"t": t, "sz": sz, "px": float(f["price"]),
                         "buy": buy, "signed": sz if buy else -sz,
                         "fee": float(f.get("fee", 0) or 0)})
        rows.sort(key=lambda r: r["t"])
        return rows

    # ---- per-venue episode reconstruction ----
    def _episodes_hl(self, coin, since_ms):
        """Walk HL fills oldest→newest, tracking signed size; an episode runs from
        the fill that leaves flat to the fill that returns to flat."""
        network, addr = self._target("hyperliquid")
        rows = self._raw_fills_hl(coin, since_ms)
        funding = self._funding_hl(coin, since_ms, addr, network)
        return _episodes_from_rows(rows, funding, "hyperliquid")

    def _episodes_dydx(self, coin, since_ms):
        network, addr = self._target("dydx")
        rows = self._raw_fills_dydx(coin, since_ms)
        funding = self._funding_dydx(coin, since_ms, addr,
                                     _DYDX_INDEXER[network])
        return _episodes_from_rows(rows, funding, "dydx")

    # ---- realized outcome over an EXACT window (for ledger-bounded analytics) ----
    def _realized_in_window(self, coin, lo_ms, hi_ms):
        """Realized funding / fees / price-PnL between two timestamps, summed from
        BOTH venues' public history. The ledger supplies exact [open, close]
        bounds, so this is precise where `review`'s episode pairing was fuzzy.

        Funding is bounded with a small tail so an hourly stamp landing right on
        the close is not dropped; a payment strictly after the close is excluded.
        """
        hi = hi_ms + 1000
        funding = fees = price_pnl = 0.0
        _, addr_hl = self._target("hyperliquid")
        net_hl = self._target("hyperliquid")[0]
        _, addr_dy = self._target("dydx")
        indexer = _DYDX_INDEXER[self._target("dydx")[0]]
        for fetch in (self._raw_fills_hl, self._raw_fills_dydx):
            for r in fetch(coin, lo_ms):
                if lo_ms <= r["t"] <= hi:
                    fees += r["fee"]
                    # sell brings cash in (+), buy pays out (-); sum = price PnL.
                    price_pnl += r["px"] * r["sz"] * (1 if not r["buy"] else -1)
        for t, amt in self._funding_hl(coin, lo_ms, addr_hl, net_hl):
            if lo_ms <= t <= hi:
                funding += amt
        for t, amt in self._funding_dydx(coin, lo_ms, addr_dy, indexer):
            if lo_ms <= t <= hi:
                funding += amt
        return {"funding_usd": round(funding, 4), "fees_usd": round(fees, 4),
                "price_pnl_usd": round(price_pnl, 4),
                "net_usd": round(funding + price_pnl - fees, 4)}

    def _funding_hl(self, coin, since_ms, addr, network):
        rows = requests.post(_HL_INFO[network], json={
            "type": "userFunding", "user": addr, "startTime": since_ms,
        }, timeout=20).json()
        return [(int(r["time"]), float(r["delta"]["usdc"]))
                for r in rows if r.get("delta", {}).get("coin") == coin]

    def _funding_dydx(self, coin, since_ms, addr, indexer):
        rows = requests.get(
            f"{indexer}/v4/fundingPayments?address={addr}&subaccountNumber=0&limit=100",
            timeout=20).json().get("fundingPayments", [])
        out = []
        for r in rows:
            if r.get("ticker") != f"{coin}-USD":
                continue
            t = _iso_ms(r["createdAt"])
            if t < since_ms:
                continue
            # dYdX reports payment as a positive number the account RECEIVED.
            out.append((t, float(r.get("payment", 0) or 0)))
        return out

    def _round_trip(self, coin, hl_ep, dy_ep):
        legs = {}
        funding = 0.0
        fees = 0.0
        price_pnl = 0.0
        opened = closed = None
        for name, ep in (("hyperliquid", hl_ep), ("dydx", dy_ep)):
            if ep is None:
                continue
            legs[name] = ep
            funding += ep.get("funding_usd", 0.0)
            fees += ep.get("fees_usd", 0.0)
            if ep.get("realized_price_pnl_usd") is not None:
                price_pnl += ep["realized_price_pnl_usd"]
            opened = _min_iso(opened, ep.get("opened_at"))
            closed = _max_iso(closed, ep.get("closed_at"))

        # Status by what's actually there. A leg still open -> live position. Both
        # legs present and closed -> a complete hedge round trip. A single closed
        # leg -> "unpaired_closed": a naked leg that opened and resolved on its own
        # (e.g. an unwound half of a botched open) — still has a realized result
        # worth surfacing, which is the whole point of the review.
        present = [ep for ep in (hl_ep, dy_ep) if ep is not None]
        any_open = any(ep.get("open") for ep in present)
        both = hl_ep is not None and dy_ep is not None
        status = "open" if any_open else ("closed" if both else "unpaired_closed")

        realized_net = None
        if status in ("closed", "unpaired_closed"):
            realized_net = round(funding + price_pnl - fees, 4)
        hold_h = None
        if opened and closed and status != "open":
            hold_h = round((_iso_ms(closed) - _iso_ms(opened)) / 3_600_000, 2)
        return {
            "coin": coin, "status": status, "opened_at": opened,
            "closed_at": closed if status != "open" else None,
            "hold_hours": hold_h,
            "funding_received_usd": round(funding, 4),
            "fees_usd": round(fees, 4),
            "price_pnl_usd": round(price_pnl, 4),
            "realized_net_usd": realized_net,
            "legs": legs,
        }

    # ------------------------------------------------------------------
    # all-coins (book-wide) views — the "how's everything?" question. Each per-coin
    # result is unchanged; these just enumerate the coins and roll up a summary, so
    # a request that names no coin no longer silently reports only BTC.
    # ------------------------------------------------------------------
    def _open_coins(self):
        """Base coins with an open leg on EITHER venue (public reads, no keys)."""
        coins = set()
        net, addr = self._target("hyperliquid")
        if addr:
            st = requests.post(_HL_INFO[net], json={
                "type": "clearinghouseState", "user": addr}, timeout=20).json()
            for p in st.get("assetPositions", []):
                pos = p.get("position", {})
                if abs(float(pos.get("szi", 0) or 0)) > 0:
                    coins.add(pos.get("coin"))
        net, addr = self._target("dydx")
        if addr:
            r = requests.get(f"{_DYDX_INDEXER[net]}/v4/addresses/{addr}",
                             timeout=20).json()
            subs = r.get("subaccounts") or []
            if subs:
                for mkt, pos in (subs[0].get("openPerpetualPositions") or {}).items():
                    if abs(float(pos.get("size", 0) or 0)) > 0:
                        coins.add(mkt.split("-")[0])
        return sorted(c for c in coins if c)

    def _status_all(self, size_tol_pct):
        coins = self._open_coins()
        if not coins:
            return {"action": "status", "scope": "all_open", "health": "flat",
                    "verdict": "flat — no open positions on either venue",
                    "open_coins": [], "positions": [], "as_of": _now_iso()}
        positions = [self._status(c, size_tol_pct) for c in coins]
        worst = "flat"
        net_hr, funding_measurable, unrl = 0.0, True, []
        for p in positions:
            if _HEALTH_RANK.get(p["health"], 0) > _HEALTH_RANK.get(worst, 0):
                worst = p["health"]
            f = (p.get("economics") or {}).get("net_funding_per_hour_usd")
            if f is None:
                funding_measurable = False
            else:
                net_hr += f
            if p.get("combined_unrealized_pnl_usd") is not None:
                unrl.append(p["combined_unrealized_pnl_usd"])
        summary = {
            "open_positions": len(positions),
            "worst_health": worst,
            "attention_needed": worst in ("warn", "critical"),
            "net_funding_per_hour_usd": round(net_hr, 5) if funding_measurable else None,
            "net_funding_per_day_usd": round(net_hr * 24, 4) if funding_measurable else None,
            "combined_unrealized_pnl_usd": round(sum(unrl), 4) if unrl else None,
            "note": None if funding_measurable else
            "one or more legs' funding could not be read; net is incomplete",
            "delta_note": "net_delta is per-coin (each in its own units); deltas are"
                          " not summed across assets",
        }
        return {"action": "status", "scope": "all_open", "health": worst,
                "verdict": f"{len(positions)} open position(s); worst health: {worst}",
                "open_coins": coins, "summary": summary, "positions": positions,
                "as_of": _now_iso()}

    def _review_all(self, lookback_days):
        coins = sorted(set(self._open_coins())
                       | {r["coin"] for r in _ledger.trades() if r.get("coin")})
        if not coins:
            return {"action": "review", "scope": "all", "lookback_days": lookback_days,
                    "summary": {"note": "no open positions or recorded trades"},
                    "by_coin": {}, "as_of": _now_iso()}
        by_coin = {c: self._review(c, lookback_days) for c in coins}
        hedge_net, total_net, have_h, have_t, closed = 0.0, 0.0, False, False, 0
        for r in by_coin.values():
            s = r["summary"]
            if s.get("hedge_realized_net_usd") is not None:
                hedge_net += s["hedge_realized_net_usd"]; have_h = True
            if s.get("total_realized_net_usd") is not None:
                total_net += s["total_realized_net_usd"]; have_t = True
            closed += s.get("hedge_round_trips_closed", 0)
        summary = {"coins": coins, "hedge_round_trips_closed": closed,
                   "hedge_realized_net_usd": round(hedge_net, 4) if have_h else None,
                   "total_realized_net_usd": round(total_net, 4) if have_t else None}
        return {"action": "review", "scope": "all", "lookback_days": lookback_days,
                "summary": summary, "by_coin": by_coin, "as_of": _now_iso()}

    def _analytics_all(self):
        coins = sorted({r["coin"] for r in _ledger.trades() if r.get("coin")})
        if not coins:
            return {"action": "analytics", "scope": "all", "by_coin": {},
                    "summary": {"note": "no trades on record yet — the ledger records"
                                " from the next real open/close onward."},
                    "as_of": _now_iso()}
        by_coin = {c: self._analytics(c) for c in coins}
        net_total, have = 0.0, False
        for a in by_coin.values():
            t = a["summary"].get("total_realized_net_usd")
            if t is not None:
                net_total += t; have = True
        summary = {
            "coins": coins,
            "closed_trades_on_record": sum(
                a["summary"].get("closed_trades_on_record", 0)
                for a in by_coin.values()),
            "total_realized_net_usd": round(net_total, 4) if have else None,
        }
        return {"action": "analytics", "scope": "all", "summary": summary,
                "by_coin": by_coin, "as_of": _now_iso()}

    # ------------------------------------------------------------------
    def run(
        self,
        action: Annotated[
            Literal["status", "review", "analytics"],
            "'status' = live open position (hedge health, liquidation, funding"
            " earned now). 'review' = reconstruct CLOSED round-trips from venue"
            " history. 'analytics' = compare each recorded trade's PREDICTED edge"
            " against realized outcomes (did the strategy earn what the model"
            " forecast).",
        ] = "status",
        coin: Annotated[
            str,
            "Which asset(s) to report. Default 'ALL' — a book-wide view across"
            " EVERY open/recorded coin at once; use it whenever the user does not"
            " name one specific coin (e.g. 'how are my positions / my book / my"
            " delta-neutral trades doing?'). Pass a single symbol (BTC, ETH, SOL,"
            " ...) ONLY when the user explicitly asks about that one asset. Do NOT"
            " default to BTC.",
        ] = "ALL",
        lookback_days: Annotated[
            float, "For 'review': how far back to reconstruct trades"] = 7.0,
        size_tolerance_pct: Annotated[
            float, "For 'status': leg-size mismatch above this reads as imbalanced"
        ] = 15.0,
    ) -> Dict[str, Any]:
        """Report live status or reconstruct closed trades. Read-only.

        `coin='ALL'` (the default) aggregates across every open/recorded coin so a
        question that names no asset covers the whole book, not just BTC.
        """
        try:
            c = str(coin).strip().upper()
            allc = c in ("ALL", "*", "")
            if action == "status":
                if allc:
                    return self._status_all(size_tolerance_pct)
                result = self._status(c, size_tolerance_pct)
                # Breadcrumb: even when the caller scopes to one coin (e.g. the LLM
                # passed a specific symbol for a general question), never let the
                # answer hide the rest of the book — name the other open positions
                # so they can be asked about. Deterministic; does not rely on the
                # caller having chosen 'ALL'.
                others = [x for x in self._open_coins() if x != c]
                if others:
                    result["other_open_positions"] = others
                    result["hint"] = (
                        f"You also have open positions in {', '.join(others)}."
                        " Ask about your whole book (or 'all') to include them.")
                return result
            if action == "review":
                return self._review_all(lookback_days) if allc \
                    else self._review(c, lookback_days)
            if action == "analytics":
                return self._analytics_all() if allc else self._analytics(c)
            return {"error": f"unknown action {action!r}; use 'status', 'review'"
                    " or 'analytics'"}
        except requests.RequestException as e:
            return {"error": f"venue read failed: {e}"}


# ----------------------------------------------------------------------
# small pure helpers (module-level so they stay testable)
# ----------------------------------------------------------------------
def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _now_iso():
    return datetime.datetime.now(datetime.UTC).isoformat()


def _iso_ms(s):
    return int(datetime.datetime.fromisoformat(
        s.replace("Z", "+00:00")).timestamp() * 1000)


def _min_iso(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if _iso_ms(a) <= _iso_ms(b) else b


def _max_iso(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if _iso_ms(a) >= _iso_ms(b) else b


def _sum_optional(*vals):
    got = [v for v in vals if v is not None]
    return round(sum(got), 4) if got else None


def _round(v, n):
    return round(v, n) if v is not None else None


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def _overlap(h, d):
    """Seconds of time overlap between two episodes' [open, close] intervals; open
    episodes extend to now. Used to pair the two legs of one hedge."""
    now = time.time() * 1000
    hs, he = _iso_ms(h["opened_at"]), (_iso_ms(h["closed_at"]) if h.get("closed_at") else now)
    ds, de = _iso_ms(d["opened_at"]), (_iso_ms(d["closed_at"]) if d.get("closed_at") else now)
    return max(0.0, min(he, de) - max(hs, ds))


def _episodes_from_rows(rows, funding, venue):
    """Fold signed fills into position episodes (flat → ... → flat), attaching the
    funding payments and fees that fall inside each one.

    An episode is one life of a position: it begins when cumulative size leaves
    zero and ends when it returns to zero. Realized price PnL is the signed cash
    from the fills over the episode (sells bring in, buys pay out); for a fully
    round-tripped hedge leg it is small and mostly offset by the other leg.
    """
    episodes, cur = [], None
    running = 0.0
    for r in rows:
        if cur is None:
            cur = {"opened_at": _iso_from_ms(r["t"]), "open_ms": r["t"],
                   "close_ms": None, "fills": 0, "fees_usd": 0.0,
                   "cash": 0.0, "entry_px": r["px"], "exit_px": None,
                   "size": 0.0, "venue": venue}
        cur["fills"] += 1
        cur["fees_usd"] += r["fee"]
        # Cash convention: a sell (+cash), a buy (-cash). Sum over a closed episode
        # = realized price PnL on that leg.
        cur["cash"] += (r["px"] * r["sz"]) * (1 if not r["buy"] else -1)
        cur["size"] = max(cur["size"], abs(running + r["signed"]))
        running += r["signed"]
        if abs(running) < 1e-12:  # back to flat -> episode closed
            cur["close_ms"] = r["t"]
            cur["closed_at"] = _iso_from_ms(r["t"])
            cur["exit_px"] = r["px"]
            episodes.append(cur)
            cur = None
    if cur is not None:  # still open
        cur["closed_at"] = None
        cur["open"] = True
        cur["size"] = abs(running)  # CURRENT live size, not the peak it reached
        episodes.append(cur)

    for ep in episodes:
        ep.setdefault("open", False)
        lo = ep["open_ms"]
        hi = ep["close_ms"] if ep["close_ms"] is not None else int(time.time() * 1000)
        ep["funding_usd"] = round(
            sum(amt for t, amt in funding if lo <= t <= hi + 1000), 6)
        ep["realized_price_pnl_usd"] = round(ep["cash"], 4) if not ep["open"] else None
        ep["fees_usd"] = round(ep["fees_usd"], 6)
        # tidy internal keys we don't need to surface
        for k in ("open_ms", "close_ms", "cash"):
            ep.pop(k, None)
    return episodes


def _iso_from_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).isoformat()
