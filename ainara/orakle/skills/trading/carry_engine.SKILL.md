---
name: "trading_carry_engine"
version: "1.0"
description: "Deterministic brain for delta-neutral cross-venue funding-rate carry: decide open/sit-out and backtest net APR"
category: "trading"
---

# Trading Carry Engine

## Description

The deterministic decision core of the delta-neutral funding-differential
strategy. Given aligned hourly funding streams for one asset on two perpetual
venues, it computes the cross-venue funding differential, smooths it with an EMA
(trading the raw spread churns itself to death on fees), and decides whether to
open a delta-neutral position — short the higher-funding venue, long the lower —
or sit out when the smoothed edge does not clear costs.

It reads market data and does maths. It holds no keys and places no orders, so it
carries **no jurisdiction gate** — that lives in the execution layer that acts on
its decisions.

Two behaviours are design requirements proven by a full 12-month Hyperliquid/dYdX
backtest, not casual knobs: (1) gate on the **smoothed** spread, never the
instantaneous one; (2) **sit out** when the smoothed edge is below the entry
threshold.

## Trigger Conditions

Use when the user asks whether to open a cross-venue funding-carry / basis /
delta-neutral position, which side to take on each venue, the estimated net return
after fees, or to backtest the strategy over a funding history.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| funding_a_hourly | List[float] | yes | – | Hourly funding fractions for venue A, oldest-first |
| funding_b_hourly | List[float] | yes | – | Hourly funding fractions for venue B, aligned to the same hours |
| action | Literal["evaluate", "backtest"] | no | "evaluate" | `evaluate` = decide on the latest point; `backtest` = walk the full history |
| venue_a | str | no | "hyperliquid" | Name of venue A |
| venue_b | str | no | "dydx" | Name of venue B |
| capital_usd | Optional[float] | no | None | Capital to size the position against (evaluate only) |
| expected_hold_days | float | no | 14.0 | Expected hold, used to amortize entry/exit fees (evaluate only) |

## Returns

### action: "evaluate" (point-in-time decision)

Key fields: `action` (`open` / `sit_out`), `short_venue`, `long_venue`,
`smoothed_spread_annual_pct`, and the projected net.

**Important:** `net_annual_pct_if_spread_holds` and
`net_annual_pct_on_capital_if_spread_holds` assume the current smoothed spread
persists across the whole hold and that you pay fees only once. They are
**optimistic** — roughly double the realized figure — because in reality the
spread compresses and you re-enter repeatedly. `estimate_basis` says so in the
payload. For an expected annual return, use `backtest`.

### action: "backtest" (walk-forward, realized)

Walks the full aligned history hour by hour, gating on the smoothed spread,
accruing the realized spread while positioned, and charging fees on every entry
and exit. This reproduces the strategy's study numbers exactly. Fields:
`uptime_pct`, `entries_per_year`, `gross_annual_pct_notional`,
`fees_annual_pct_notional`, `net_annual_pct_notional`,
`net_annual_pct_on_capital`.

## Examples

```
# Input: Should I open an HL/dYdX carry on ETH right now, and how does it backtest?
# action: "backtest", venue_a: "hyperliquid", venue_b: "dydx",
# funding_a_hourly: [...12 months of HL ETH hourly funding...],
# funding_b_hourly: [...aligned dYdX ETH hourly funding...]
# Output: {"mode": "backtest_walk_forward", "uptime_pct": 55.3,
#          "net_annual_pct_notional": 3.62, "net_annual_pct_on_capital": 10.86, ...}
```
