---
name: "trading_oreka_signal"
version: "0.1.0+7e485b3"
oreka_version: "0.1.0"
oreka_commit: "7e485b3"
copied_on: "2026-08-27"
description: "Ask the Oreka carry engine whether to open or close a delta-neutral position, and what a cycle would do — evaluates only, never submits"
category: "trading"
---

# Oreka Signal

## Description

The decision half of the **Oreka** delta-neutral desk, without the acting half.

It computes the cross-venue funding differential for an asset, smooths it with an
EMA over roughly fourteen days (the raw spread churns itself to death on fees),
and decides whether the edge clears the threshold. A verdict that clears can
still be refused by the **dilution guard**, which prices fees plus the full
round-trip slippage — entry *and* exit, on both venues — at the size actually
being considered. Being unable to get out is the whole risk, so the exit side is
checked too.

`cycle_farm` and `cycle_exit` run the complete cycle including what the executor
would do, and stop before submission.

**Nothing here submits an order.** `dry_run` is not exposed as a parameter, so
there is no value a caller can pass to change that. Live trading is the CLI's
job — `oreka run farm --live` — where reaching an order takes a word a human
typed deliberately, behind the desk's four gates.

## Trigger Conditions

Use when the user asks whether there is a trade right now, whether to open or
close a carry position, what the funding spread is doing, why the desk is sitting
out, or what would happen if a cycle ran.

If the user wants to actually place a trade, tell them it is a CLI action; this
skill cannot do it.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["open","close","cycle_farm","cycle_exit"] | no | "open" | Entry verdict / exit verdict / full dry cycle either way |
| coin | str | no | "BTC" | Asset to evaluate |
| capital_usd | float | no | None | For `open`: capital to size against. Omit to use the configured default |

## Returns

`{"verdict": {...}, "submitted": false}`, and for the cycle forms additionally
`result` and a plain-language `report`.

The verdict carries `action` (`open` / `sit_out`, or `close` / `hold`), the
`reason`, `smoothed_spread_annual_pct`, the `sizing` breakdown including which
account binds, and the `slippage` measurement.

**Read `reason`, not the spread.** A cycle can sit out with the spread well clear
of its threshold — an exposure cap, a depth guard, an unreadable book count, or
the dilution guard. The reason names which; the spread alone will mislead.

## Configuration

Reads Oreka's own config, not `ainara.yaml`. Requires Oreka importable by Orakle;
otherwise returns `{"installed": false, "submitted": false, "error": "..."}`.
