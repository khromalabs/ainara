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


class TradingHyperliquid(Skill):
    """Read-only Hyperliquid perpetuals market data.

    Exposes funding rates, mark/oracle prices, open interest and order-book
    depth for HL perp markets. No keys, no order placement — this is a data
    feed for the delta-neutral funding-arbitrage engine.
    """

    matcher_info = (
        "Use this skill to read REAL-TIME Hyperliquid perpetual-futures market"
        " data: current and predicted funding rates, mark price, oracle price,"
        " open interest, and order-book depth / slippage estimates for a"
        " cryptocurrency on Hyperliquid (e.g. BTC, ETH, SOL). Read-only market"
        " data only; it does NOT place trades. Keywords: hyperliquid, funding"
        " rate, perp, perpetual, mark price, open interest, order book."
    )

    def __init__(self):
        super().__init__()
        self.name = "hyperliquid"
        self.logger = logging.getLogger(__name__)
        base = config.get("apis.hyperliquid.base_url", "https://api.hyperliquid.xyz")
        self.info_url = f"{base.rstrip('/')}/info"

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _info(self, body: Dict[str, Any]) -> Any:
        """POST to the HL /info endpoint, returning parsed JSON or raising."""
        resp = requests.post(self.info_url, json=body, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _asset_ctx(self, coin: str):
        """Return (universe_entry, asset_ctx) for *coin*, or (None, None)."""
        meta, ctxs = self._info({"type": "metaAndAssetCtxs"})
        for idx, asset in enumerate(meta["universe"]):
            if asset["name"].upper() == coin.upper():
                return asset, ctxs[idx]
        return None, None

    @staticmethod
    def _walk_book(levels: List[dict], mid: float, notional_usd: float, side: str):
        """Estimate average fill price walking the book for *notional_usd*.

        side 'buy' walks asks, 'sell' walks bids. Returns slippage vs mid in bps,
        signed so that positive always means cost. *mid* must come from the same
        book snapshot as *levels* (see markets()), otherwise the two are from
        different instants and slippage can come out nonsensically negative.
        """
        remaining, filled_usd, base = notional_usd, 0.0, 0.0
        for lvl in levels:
            px, sz = float(lvl["px"]), float(lvl["sz"])
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
        """Current + predicted funding for *coin* (hourly fraction & annualized %)."""
        try:
            _, ctx = self._asset_ctx(coin)
            if ctx is None:
                return {"error": f"Unknown HL market '{coin}'"}

            hourly = float(ctx["funding"])
            result = {
                "venue": "hyperliquid",
                "coin": coin.upper(),
                "funding_hourly": hourly,
                "funding_annualized_pct": round(hourly * HOURS_PER_YEAR * 100, 4),
                "premium": float(ctx.get("premium", 0)),
                "mark_px": float(ctx["markPx"]),
                "oracle_px": float(ctx["oraclePx"]),
            }

            # Predicted next HL funding, if available
            try:
                pf = self._info({"type": "predictedFundings"})
                row = next((x for x in pf if x[0].upper() == coin.upper()), None)
                if row:
                    hl = next((v for name, v in row[1] if name == "HlPerp"), None)
                    if hl:
                        result["predicted_funding_hourly"] = float(hl["fundingRate"])
                        result["next_funding_time"] = hl.get("nextFundingTime")
            except Exception as e:
                self.logger.debug(f"predictedFundings unavailable: {e}")

            return result
        except Exception as e:
            self.logger.error(f"HL funding error for {coin}: {e}")
            return {"error": f"Failed to fetch HL funding: {e}"}

    async def markets(
        self, coin: str, est_notional_usd: Optional[float] = None
    ) -> Dict[str, Any]:
        """Mark/oracle/mid prices, open interest, top-of-book and optional slippage."""
        try:
            _, ctx = self._asset_ctx(coin)
            if ctx is None:
                return {"error": f"Unknown HL market '{coin}'"}

            mark = float(ctx["markPx"])
            result = {
                "venue": "hyperliquid",
                "coin": coin.upper(),
                "mark_px": mark,
                "oracle_px": float(ctx["oraclePx"]),
                "open_interest": float(ctx["openInterest"]),
                "day_notional_volume": float(ctx.get("dayNtlVlm", 0)),
            }

            book = self._info({"type": "l2Book", "coin": coin.upper()})
            bids, asks = book["levels"][0], book["levels"][1]
            if bids and asks:
                best_bid, best_ask = float(bids[0]["px"]), float(asks[0]["px"])
                # Mid must come from this same book snapshot, not from the ctx
                # payload above: they are separate API calls, and a ctx midPx can
                # land outside this book's spread, flipping the sign of slippage.
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
            self.logger.error(f"HL markets error for {coin}: {e}")
            return {"error": f"Failed to fetch HL market data: {e}"}

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
            str, "Coin symbol on Hyperliquid, e.g. BTC, ETH, SOL"
        ] = "BTC",
        est_notional_usd: Annotated[
            Optional[float],
            "For 'markets': estimate order-book slippage to fill this USD notional",
        ] = None,
    ) -> Dict[str, Any]:
        """Read-only Hyperliquid perp market data (funding, prices, book)."""
        if action == "funding":
            return await self.funding(coin)
        elif action == "markets":
            return await self.markets(coin, est_notional_usd)
        return {"error": f"Unknown action '{action}'. Use 'funding' or 'markets'."}
