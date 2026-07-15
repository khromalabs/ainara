---
name: "trading_dydx"
version: "1.0"
description: "Read-only dYdX v4 perpetuals market data: funding rates, oracle price, open interest and order-book depth"
category: "trading"
---

# Trading Dydx

## Description

Reads live market data from dYdX v4 perpetual-futures markets via the public
indexer: next and last-realized funding rates, oracle price, open interest, 24h
volume, and order-book depth with slippage estimates.

Read-only. Requires no API keys and places no orders.

dYdX funds **hourly**, the same cadence as Hyperliquid, so funding rates from the
two venues are directly comparable without interval normalization.

## Trigger Conditions

Use when the user asks for dYdX funding rates, perp prices, open interest, or
order-book/slippage information for a cryptocurrency (BTC, ETH, SOL, ...).

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["funding", "markets"] | no | "funding" | Which data to fetch: `funding` (rates) or `markets` (prices/OI/book) |
| coin | str | no | "BTC" | Coin symbol on dYdX, e.g. BTC, ETH, SOL |
| est_notional_usd | Optional[float] | no | None | For `markets`: estimate order-book slippage to fill this USD notional |

## Returns

### action: "funding"

| Field | Type | Description |
|-------|------|-------------|
| venue | string | Always `"dydx"` |
| coin | string | Coin symbol, uppercased |
| status | string | Market status, e.g. `ACTIVE` |
| next_funding_hourly | float | Upcoming funding rate as an hourly fraction |
| next_funding_annualized_pct | float | `next_funding_hourly` × 24 × 365 × 100 |
| last_funding_hourly | float | Most recent realized hourly funding |
| last_funding_annualized_pct | float | Annualized equivalent |
| last_funding_at | string | ISO timestamp of the last funding |
| oracle_px | float | Oracle price |
| error | string | Error message (present on failure) |

### action: "markets"

| Field | Type | Description |
|-------|------|-------------|
| venue | string | Always `"dydx"` |
| coin | string | Coin symbol, uppercased |
| status | string | Market status, e.g. `ACTIVE` |
| oracle_px | float | Oracle price |
| open_interest | float | Open interest, in base units |
| day_notional_volume | float | 24h notional volume, USD |
| trades_24h | int | Trade count over 24h |
| mid_px | float | Mid derived from this book snapshot: `(best_bid + best_ask) / 2` |
| best_bid / best_ask | float | Top of book |
| spread_bps | float | Bid-ask spread in basis points |
| slippage_buy / slippage_sell | object | Present only when `est_notional_usd` is set |
| error | string | Error message (present on failure) |

Each slippage object holds `avg_px`, `slippage_bps`, `filled_usd`, and
`unfilled_usd`. **`slippage_bps` is signed so that positive always means cost**,
for both sides. A non-zero `unfilled_usd` means the visible book could not absorb
the requested notional, and the reported slippage therefore understates the true
cost — treat that as a do-not-trade signal rather than a cheap fill.

## Examples

```
# Input: What is the funding rate on dYdX for ETH?
# action: "funding", coin: "ETH"
# Output: {"venue": "dydx", "coin": "ETH", "status": "ACTIVE",
#          "next_funding_hourly": -5.02e-05,
#          "next_funding_annualized_pct": -43.98, "oracle_px": 1873.73, ...}
```

```
# Input: How much would it cost me to fill $5,000 of BTC on dYdX?
# action: "markets", coin: "BTC", est_notional_usd: 5000
# Output: {"venue": "dydx", "coin": "BTC", "mid_px": 64554.0,
#          "spread_bps": 1.549,
#          "slippage_buy": {"avg_px": 64559.79, "slippage_bps": 0.896,
#                           "filled_usd": 5000.0, "unfilled_usd": 0.0}, ...}
```
