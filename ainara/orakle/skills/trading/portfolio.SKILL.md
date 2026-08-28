---
name: "trading_portfolio"
version: "1.1"
description: "Read-only status, closed-trade review and realized-vs-predicted analytics for the delta-neutral funding-carry book on Hyperliquid and dYdX"
category: "trading"
---

# Trading Portfolio

## Description

Read-only view of the delta-neutral funding-carry book. It answers three
questions and does nothing that moves money:

- **`status`** — the live position: whether it is hedged and balanced, how far each
  leg sits from liquidation, the funding cash-flow it is earning or paying this
  hour, and combined unrealized PnL.
- **`review`** — completed trades: it reconstructs closed round-trips from each
  venue's own PUBLIC history (fills + funding payments), so the strategy can be
  judged on realized results — funding captured, fees paid, hold time, realized
  net — not just what it was predicted to earn.
- **`analytics`** — realized vs PREDICTED: joins the carry ledger's captured
  prediction (the `decide` verdict at entry) against realized outcomes rebuilt
  over each trade's exact window. Headline is `funding_capture_ratio` (realized
  funding rate ÷ predicted spread); fees are reported separately, and rate metrics
  are suppressed for holds too short to annualize honestly. Pass `benchmark=true`
  to additionally ask whether the strategy beat simply **holding** the hedge.

**Key-free and daemon-free.** Every read is a public venue endpoint keyed by the
account address in config, so it still works when the executor daemon is down —
which is exactly when you most want eyes on an unmanaged position. It holds no
keys, places no orders, and carries no jurisdiction gate.

The funding-direction math is the convention validated against real mainnet
payments on both venues: `receive_per_hour = -signed_size * rate * mark`
(positive = the leg is being paid). A `review` classifies each reconstructed
trip as `closed` (both legs, complete hedge), `open` (a leg still live),
`unpaired_closed` (a lone closed leg — e.g. an unwound half of a botched open,
surfaced with its own realized cost), or `incomplete_window` (the window caught
the trade's close but not its open — **both venues are flat**, this is NOT a
live position).

## Trigger Conditions

Use when the user asks how the carry / delta-neutral position is doing, whether
they are still hedged, how close to liquidation, how much funding it is earning,
or wants to review closed trades and reflect on realized performance.

Add `benchmark=true` when the question is whether the strategy is **worth
running** — "is this actually making me money versus just holding?", "does the
entry timing add anything?", "should I keep running this?" — rather than what it
did. It is off otherwise because it costs two public funding reads per coin.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["status","review","analytics"] | no | "status" | Live status, reconstruct closed trades, or realized-vs-predicted |
| coin | str | no | "ALL" | Whole book by default. Pass one symbol (BTC, ETH, SOL, …) only if the user named one |
| lookback_days | float | no | derived | For `review`: how far back to reconstruct. Unset derives it from `expected_hold_days` (≥ 90 days); a shorter window cannot see a completed trade |
| size_tolerance_pct | float | no | 15.0 | For `status`: leg mismatch above this reads as imbalanced |
| benchmark | bool | no | false | For `analytics`: also compare against holding the hedge. Opt-in — it reads two public funding series **per coin** |

`analytics` reads the carry ledger (`carry_trades` table, written by the executor
client on each real open/close). It records from the next live open/close onward,
so it is empty until trades happen with the write path loaded.

## Returns

`status`: `{health, verdict, net_delta, legs, economics, combined_unrealized_pnl_usd,
liquidation, ...}` where `verdict` is a plain sentence (`hedged and balanced`,
`IMBALANCED: ...`, `BROKEN HEDGE: ...`, `flat`).

A null `liq_distance_pct` is never "safe". Each leg carries a `liq_note` saying
which case it is: *not liquidatable by price alone* (benign — there genuinely is
no liquidation price) versus *liquidation unknown* (the leg is **unmonitored**,
usually an unreadable mark or two coins sharing a dYdX subaccount).

`review`: `{summary, round_trips[]}` where `summary` separates the strategy's own
scorecard (`hedge_realized_net_usd`, `winning_hedges`/`losing_hedges` over complete
hedges) from `total_realized_net_usd` (all realized cash, including unpaired legs).
`incomplete_window_round_trips` is counted separately from `still_open` and is
**flat, not open** — say the window was too short and offer a longer
`lookback_days` rather than reporting a live position.

`analytics`: `{summary, trades[], benchmark}`. Check `data_quality_ok` on a trade
and `summary.data_quality` before quoting any figure. A faulted trade is excluded
from `total_realized_net_usd` and from every headline rate — report the fault, not
the number. Realized rates name their own denominator
(`funding_rate_denominator_usd`, `net_rate_denominator_usd`) and `notional_basis`
states what the measurement cannot account for.

`benchmark` answers whether the timing rule beat holding. It is `{"requested":
false, ...}` unless asked for. When computed it carries `held` vs `decision_rule`,
`gap_usd` and a `gap_decomposition` that sums to it — and it **withholds**
`beat_holding` rather than guessing when the inputs are not credible (`error` plus
`data_quality`) or when the rule was positioned for essentially the whole window
(`verdict_withheld`, because it never chose to sit out and so timed nothing).
Do not synthesise a verdict from the remaining fields.

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
# Input: Review my closed trades
# action: "review", coin: "ALL"       (leave lookback_days unset)
# Output: {"summary":{"hedge_round_trips_closed":1,"hedge_realized_net_usd":-0.0202,
#          "total_realized_net_usd":-0.0733,"incomplete_window_round_trips":0, ...},
#          "round_trips":[ ... ]}
```

```
# Input: Is this strategy actually worth running, or would I do as well just holding?
# action: "analytics", coin: "ALL", benchmark: true
# Output: {"summary":{...,"benchmark_verdicts":{"beat_holding":["BTC"],
#          "lost_to_holding":["ETH"],"verdict_withheld":["SOL"], ...}},
#          "by_coin":{"BTC":{"benchmark":{"beat_holding":true,"gap_usd":12.6, ...}}}}
```
