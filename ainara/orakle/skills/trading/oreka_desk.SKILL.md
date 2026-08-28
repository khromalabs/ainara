---
name: "trading_oreka_desk"
version: "0.1.0+7e485b3"
oreka_version: "0.1.0"
oreka_commit: "7e485b3"
copied_on: "2026-08-27"
description: "Read the Oreka delta-neutral desk: open hedges across Hyperliquid and dYdX, hedge health, funding earned, closed round trips, predicted vs realized"
category: "trading"
---

# Oreka Desk

## Description

Reports the book of the **Oreka** delta-neutral funding-carry desk — a strategy
that holds equal-and-opposite perpetual positions on Hyperliquid and dYdX v4,
price-neutral by construction, and collects the funding *differential* between
the two venues.

Three views. `status` is what is open right now, per coin, with both legs, hedge
health, net delta, liquidation distance and the funding each leg pays or
receives. `review` reconstructs closed round trips from venue history.
`analytics` compares each recorded trade's predicted edge against what it
realized — the view that answers whether the model is right, as distinct from
whether the plumbing works.

**Read-only.** It uses no signing key and cannot place, cancel or modify an
order. A failed read is reported as an error and never as an empty book, because
"I could not see your positions" and "you have no positions" must not look alike.

## Trigger Conditions

Use when the user asks how their book, positions, hedges or carry desk are doing;
what a position has earned; whether a hedge is balanced; how close a leg is to
liquidation; or whether the strategy earned what it forecast.

Do not use it to open or close anything — it cannot.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["status","review","analytics"] | no | "status" | Open now / closed round trips / predicted vs realized |
| coin | str | no | "ALL" | Whole book by default. Pass one symbol only if the user named one |
| lookback_days | float | no | derived | For `review`: how far back to reconstruct. Unset derives it from `expected_hold_days` (>= 90 days) |

## Returns

The portfolio's JSON report. For `status`: a `summary` (open count, worst health,
net funding per day, combined unrealized PnL) and a `positions` list, each with
both legs, `net_delta`, `health`, liquidation distance and funding economics.

A dYdX leg may report `liquidation_px: null` with the note *"not liquidatable by
price alone (equity exceeds notional)"* — that is benign and means there is
genuinely no liquidation price. A leg reporting liquidation **unknown** is not
benign: it is unmonitored, and usually means two coins share a dYdX subaccount.

For `review`: a round trip with `status: "incomplete_window"` is NOT an open
position. It means the lookback caught the trade's close but not its open, so it
could not be reconstructed; both venues are flat. Say so, and offer a longer
`lookback_days` rather than reporting a live position.

For `analytics`: check `data_quality_ok` on a trade and `summary.data_quality`
before quoting any figure. A trade marked faulted either has numbers a
delta-neutral hedge cannot produce, or was computed from fills that do not
round-trip the position — which can look like a perfectly clean $0.00. Either
way `benchmark` carries an `error` instead of a `verdict`: report the fault,
never the number. `cross_check` says whether the same trades reconstructed
independently from venue history agree.

On failure: `{"error": "..."}`.

## Configuration

Reads Oreka's own config (`OREKA_CONFIG`, else the platform default), not
`ainara.yaml`. Oreka must be importable by Orakle; if it is not, the skill
returns `{"installed": false, "error": "..."}`.
