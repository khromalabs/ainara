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

HOURS_PER_YEAR = 24 * 365

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
        " performance, how did the strategy do."
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
        pos = (s.get("openPerpetualPositions") or {}).get(market)
        if not pos:
            return leg
        sz = abs(float(pos.get("size", 0) or 0))
        signed = sz if pos.get("side") == "LONG" else -sz
        mark, mmf = self._dydx_market_risk(indexer, market)
        liq = liq_dist = note = None
        if mark is None:
            note = "liquidation unknown: market risk params unavailable"
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

    # ---- per-venue episode reconstruction ----
    def _episodes_hl(self, coin, since_ms):
        """Walk HL fills oldest→newest, tracking signed size; an episode runs from
        the fill that leaves flat to the fill that returns to flat."""
        network, addr = self._target("hyperliquid")
        fills = requests.post(_HL_INFO[network], json={
            "type": "userFillsByTime", "user": addr, "startTime": since_ms,
        }, timeout=20).json()
        fills = [f for f in fills if f.get("coin") == coin]
        fills.sort(key=lambda f: f["time"])
        rows = []
        for f in fills:
            # HL 'dir' is explicit: a BUY is "Open Long" or "Close Short"; a SELL
            # is "Open Short" or "Close Long". That alone gives the signed delta.
            d = str(f.get("dir", "")).lower()
            buy = d in ("open long", "close short")
            sz = float(f["sz"])
            rows.append({"t": int(f["time"]), "sz": sz, "px": float(f["px"]),
                         "buy": buy, "signed": sz if buy else -sz,
                         "fee": float(f.get("fee", 0) or 0)})
        funding = self._funding_hl(coin, since_ms, addr, network)
        return _episodes_from_rows(rows, funding, "hyperliquid")

    def _episodes_dydx(self, coin, since_ms):
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
            rows.append({"t": t, "signed": sz if buy else -sz, "px": float(f["price"]),
                         "sz": sz, "buy": buy,
                         "fee": float(f.get("fee", 0) or 0), "funding": 0.0})
        rows.sort(key=lambda r: r["t"])
        funding = self._funding_dydx(coin, since_ms, addr, indexer)
        return _episodes_from_rows(rows, funding, "dydx")

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
    def run(
        self,
        action: Annotated[
            Literal["status", "review"],
            "'status' = live open position (hedge health, liquidation, funding"
            " earned now). 'review' = reconstruct CLOSED round-trips from venue"
            " history for reflection on realized performance.",
        ] = "status",
        coin: Annotated[str, "Asset symbol, e.g. BTC, ETH, SOL"] = "BTC",
        lookback_days: Annotated[
            float, "For 'review': how far back to reconstruct trades"] = 7.0,
        size_tolerance_pct: Annotated[
            float, "For 'status': leg-size mismatch above this reads as imbalanced"
        ] = 15.0,
    ) -> Dict[str, Any]:
        """Report live status or reconstruct closed trades. Read-only."""
        try:
            if action == "status":
                return self._status(coin, size_tolerance_pct)
            if action == "review":
                return self._review(coin, lookback_days)
            return {"error": f"unknown action {action!r}; use 'status' or 'review'"}
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
