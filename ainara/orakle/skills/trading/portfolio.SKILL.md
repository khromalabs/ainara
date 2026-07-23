---
name: "trading_portfolio"
version: "1.0"
description: "Read-only status and post-mortem review of the delta-neutral funding-carry positions on Hyperliquid and dYdX"
category: "trading"
---

# Trading Portfolio

## Description

Read-only view of the delta-neutral funding-carry book. It answers two questions
and does nothing that moves money:

- **`status`** — the live position: whether it is hedged and balanced, how far each
  leg sits from liquidation, the funding cash-flow it is earning or paying this
  hour, and combined unrealized PnL.
- **`review`** — completed trades: it reconstructs closed round-trips from each
  venue's own PUBLIC history (fills + funding payments), so the strategy can be
  judged on realized results — funding captured, fees paid, hold time, realized
  net — not just what it was predicted to earn.

**Key-free and daemon-free.** Every read is a public venue endpoint keyed by the
account address in config, so it still works when the executor daemon is down —
which is exactly when you most want eyes on an unmanaged position. It holds no
keys, places no orders, and carries no jurisdiction gate.

The funding-direction math is the convention validated against real mainnet
payments on both venues: `receive_per_hour = -signed_size * rate * mark`
(positive = the leg is being paid). A `review` classifies each reconstructed
trip as `closed` (both legs, complete hedge), `open` (a leg still live), or
`unpaired_closed` (a lone closed leg — e.g. an unwound half of a botched open,
surfaced with its own realized cost).

## Trigger Conditions

Use when the user asks how the carry / delta-neutral position is doing, whether
they are still hedged, how close to liquidation, how much funding it is earning,
or wants to review closed trades and reflect on realized performance.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["status","review"] | no | "status" | Live status, or reconstruct closed trades |
| coin | str | no | "BTC" | Asset symbol (BTC, ETH, SOL, …) |
| lookback_days | float | no | 7.0 | For `review`: how far back to reconstruct |
| size_tolerance_pct | float | no | 15.0 | For `status`: leg mismatch above this reads as imbalanced |

## Returns

`status`: `{health, verdict, net_delta, legs, economics, combined_unrealized_pnl_usd,
liquidation, ...}` where `verdict` is a plain sentence (`hedged and balanced`,
`IMBALANCED: ...`, `BROKEN HEDGE: ...`, `flat`).

`review`: `{summary, round_trips[]}` where `summary` separates the strategy's own
scorecard (`hedge_realized_net_usd`, `winning_hedges`/`losing_hedges` over complete
hedges) from `total_realized_net_usd` (all realized cash, including unpaired legs).

## Configuration

Reads `apis.<venue>.network` and `apis.<venue>.<network>.account_address` from
ainara.yaml — the same account the executor trades. No keys used.

## Examples

```
# Input: How's my carry position doing?
# action: "status", coin: "BTC"
# Output: {"health":"ok","verdict":"hedged and balanced","net_delta":0.0,
#          "economics":{"net_funding_per_day_usd":0.0018, ...}, ...}
```

```
# Input: Review my closed trades from the last couple days
# action: "review", coin: "BTC", lookback_days: 2
# Output: {"summary":{"hedge_round_trips_closed":1,"hedge_realized_net_usd":-0.0202,
#          "total_realized_net_usd":-0.0733, ...}, "round_trips":[ ... ]}
```
