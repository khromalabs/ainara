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

import logging
from typing import Annotated, Any, Dict, List, Literal, Optional

import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill

HOURS_PER_YEAR = 24 * 365


class TradingDydx(Skill):
    """Read-only dYdX v4 perpetuals market data.

    Exposes funding rates, oracle price, open interest and order-book depth for
    dYdX v4 perp markets via the public indexer. No keys, no order placement.

    dYdX funds HOURLY, same cadence as Hyperliquid, so rates from the two are
    directly comparable without interval normalization.
    """

    matcher_info = (
        "Use this skill to read REAL-TIME dYdX (dYdX v4) perpetual-futures market"
        " data: current and next funding rates, oracle price, open interest,"
        " 24h volume, and order-book depth / slippage estimates for a"
        " cryptocurrency on dYdX (e.g. BTC, ETH, SOL). Read-only market data"
        " only; it does NOT place trades. Keywords: dydx, funding rate, perp,"
        " perpetual, oracle price, open interest, order book."
    )

    def __init__(self):
        super().__init__()
        self.name = "dydx"
        self.logger = logging.getLogger(__name__)
        base = config.get("apis.dydx.indexer_url", "https://indexer.dydx.trade")
        self.base_url = base.rstrip("/")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **params) -> Any:
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _ticker(coin: str) -> str:
        return f"{coin.upper()}-USD"

    def _market(self, coin: str) -> Optional[dict]:
        """Return the market dict for *coin*, or None if the ticker is unknown.

        The indexer answers an unknown ticker with a 400 rather than an empty
        result, so map that onto None and let callers report it uniformly.
        """
        ticker = self._ticker(coin)
        try:
            data = self._get("/v4/perpetualMarkets", ticker=ticker)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                return None
            raise
        return (data.get("markets") or {}).get(ticker)

    @staticmethod
    def _walk_book(levels: List[dict], mid: float, notional_usd: float, side: str):
        """Estimate average fill price walking the book for *notional_usd*.

        side 'buy' walks asks, 'sell' walks bids. Returns slippage vs mid in bps,
        signed so that positive always means cost. *mid* must come from the same
        book snapshot as *levels*, otherwise the two are from different instants
        and slippage can come out nonsensically negative.
        """
        remaining, filled_usd, base = notional_usd, 0.0, 0.0
        for lvl in levels:
            px, sz = float(lvl["price"]), float(lvl["size"])
            take = min(remaining, px * sz)
            if take <= 0:
                continue
            base += take / px
            filled_usd += take
            remaining -= take
            if remaining <= 0:
                break
        if base <= 0 or filled_usd <= 0:
            return None
        avg = filled_usd / base
        slip = (avg - mid) / mid * 1e4 * (1 if side == "buy" else -1)
        return {
            "avg_px": avg,
            "slippage_bps": round(slip, 3),
            "filled_usd": round(filled_usd, 2),
            "unfilled_usd": round(max(0.0, remaining), 2),
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def funding(self, coin: str) -> Dict[str, Any]:
        """Next + recent realized funding for *coin* (hourly fraction & annualized %)."""
        try:
            m = self._market(coin)
            if m is None:
                return {"error": f"Unknown dYdX market '{coin}'"}

            nxt = float(m["nextFundingRate"])
            result = {
                "venue": "dydx",
                "coin": coin.upper(),
                "status": m.get("status"),
                "next_funding_hourly": nxt,
                "next_funding_annualized_pct": round(nxt * HOURS_PER_YEAR * 100, 4),
                "oracle_px": float(m["oraclePrice"]),
            }

            # Most recent realized funding, if the indexer has it
            try:
                hist = self._get(
                    f"/v4/historicalFunding/{self._ticker(coin)}", limit=1
                ).get("historicalFunding") or []
                if hist:
                    last = hist[0]
                    rate = float(last["rate"])
                    result["last_funding_hourly"] = rate
                    result["last_funding_annualized_pct"] = round(
                        rate * HOURS_PER_YEAR * 100, 4
                    )
                    result["last_funding_at"] = last.get("effectiveAt")
            except Exception as e:
                self.logger.debug(f"historicalFunding unavailable: {e}")

            return result
        except Exception as e:
            self.logger.error(f"dYdX funding error for {coin}: {e}")
            return {"error": f"Failed to fetch dYdX funding: {e}"}

    async def markets(
        self, coin: str, est_notional_usd: Optional[float] = None
    ) -> Dict[str, Any]:
        """Oracle price, open interest, top-of-book and optional slippage."""
        try:
            m = self._market(coin)
            if m is None:
                return {"error": f"Unknown dYdX market '{coin}'"}

            result = {
                "venue": "dydx",
                "coin": coin.upper(),
                "status": m.get("status"),
                "oracle_px": float(m["oraclePrice"]),
                "open_interest": float(m["openInterest"]),
                "day_notional_volume": float(m.get("volume24H", 0)),
                "trades_24h": m.get("trades24H"),
            }

            book = self._get(f"/v4/orderbooks/perpetualMarket/{self._ticker(coin)}")
            bids, asks = book.get("bids") or [], book.get("asks") or []
            if bids and asks:
                best_bid, best_ask = float(bids[0]["price"]), float(asks[0]["price"])
                # Mid derived from this same book snapshot — never from a separately
                # fetched price, which would be a different instant.
                mid = (best_bid + best_ask) / 2
                result["best_bid"] = best_bid
                result["best_ask"] = best_ask
                result["mid_px"] = mid
                result["spread_bps"] = round((best_ask - best_bid) / mid * 1e4, 3)
                if est_notional_usd:
                    result["slippage_buy"] = self._walk_book(
                        asks, mid, est_notional_usd, "buy"
                    )
                    result["slippage_sell"] = self._walk_book(
                        bids, mid, est_notional_usd, "sell"
                    )
            return result
        except Exception as e:
            self.logger.error(f"dYdX markets error for {coin}: {e}")
            return {"error": f"Failed to fetch dYdX market data: {e}"}

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def run(
        self,
        action: Annotated[
            Literal["funding", "markets"],
            "Which data to fetch: 'funding' (rates) or 'markets' (prices/OI/book)",
        ] = "funding",
        coin: Annotated[
            str, "Coin symbol on dYdX, e.g. BTC, ETH, SOL"
        ] = "BTC",
        est_notional_usd: Annotated[
            Optional[float],
            "For 'markets': estimate order-book slippage to fill this USD notional",
        ] = None,
    ) -> Dict[str, Any]:
        """Read-only dYdX v4 perp market data (funding, prices, book)."""
        if action == "funding":
            return await self.funding(coin)
        elif action == "markets":
            return await self.markets(coin, est_notional_usd)
        return {"error": f"Unknown action '{action}'. Use 'funding' or 'markets'."}
