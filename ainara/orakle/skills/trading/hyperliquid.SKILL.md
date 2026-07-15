---
name: "trading_hyperliquid"
version: "1.0"
description: "Read-only Hyperliquid perpetuals market data: funding rates, prices, open interest and order-book depth"
category: "trading"
---

# Trading Hyperliquid

## Description

Reads live market data from Hyperliquid perpetual-futures markets: current and
predicted funding rates, mark/oracle/mid prices, open interest, and order-book
depth with slippage estimates.

Read-only. Requires no API keys and places no orders. It exists as the market-data
feed for the delta-neutral funding-arbitrage engine, where the funding rate is the
revenue and the order-book slippage is the cost.

## Trigger Conditions

Use when the user asks for Hyperliquid funding rates, perp prices, open interest,
or order-book/slippage information for a cryptocurrency (BTC, ETH, SOL, ...).

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["funding", "markets"] | no | "funding" | Which data to fetch: `funding` (rates) or `markets` (prices/OI/book) |
| coin | str | no | "BTC" | Coin symbol on Hyperliquid, e.g. BTC, ETH, SOL |
| est_notional_usd | Optional[float] | no | None | For `markets`: estimate order-book slippage to fill this USD notional |

## Returns

### action: "funding"

| Field | Type | Description |
|-------|------|-------------|
| venue | string | Always `"hyperliquid"` |
| coin | string | Coin symbol, uppercased |
| funding_hourly | float | Current funding rate as an hourly fraction |
| funding_annualized_pct | float | `funding_hourly` × 24 × 365 × 100 |
| premium | float | Mark-vs-oracle premium |
| mark_px | float | Mark price |
| oracle_px | float | Oracle price |
| predicted_funding_hourly | float | Next funding rate, if HL publishes it |
| next_funding_time | int | Epoch ms of the next funding payment |
| error | string | Error message (present on failure) |

### action: "markets"

| Field | Type | Description |
|-------|------|-------------|
| venue | string | Always `"hyperliquid"` |
| coin | string | Coin symbol, uppercased |
| mark_px | float | Mark price |
| oracle_px | float | Oracle price |
| mid_px | float | Mid derived from this book snapshot: `(best_bid + best_ask) / 2` |
| open_interest | float | Open interest, in base units |
| day_notional_volume | float | 24h notional volume, USD |
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
# Input: What is the funding rate on Hyperliquid for ETH?
# action: "funding", coin: "ETH"
# Output: {"venue": "hyperliquid", "coin": "ETH", "funding_hourly": 1.25e-05,
#          "funding_annualized_pct": 10.95, "mark_px": 1874.4, ...}
```

```
# Input: How much would it cost me to fill $5,000 of BTC on Hyperliquid?
# action: "markets", coin: "BTC", est_notional_usd: 5000
# Output: {"venue": "hyperliquid", "coin": "BTC", "mid_px": 64795.5,
#          "spread_bps": 0.154,
#          "slippage_buy": {"avg_px": 64796.0, "slippage_bps": 0.077,
#                           "filled_usd": 5000.0, "unfilled_usd": 0.0}, ...}
```
