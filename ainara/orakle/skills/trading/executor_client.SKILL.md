---
name: "trading_executor"
version: "1.0"
description: "Thin client that drives the standalone trading executor daemon: account state and order placement/cancel on Hyperliquid and dYdX"
category: "trading"
---

# Trading Executor

## Description

Drives the delta-neutral trading **executor daemon** over local HTTP. The daemon
is a separate process (its own virtualenv) that owns the venue signing SDKs and
places the actual orders; this skill keeps Orakle dependency-light by proxying to
it. It can check daemon health, validate venue credentials, read account state,
list open orders, and place or cancel perpetual orders on Hyperliquid or dYdX.

**Safety:** order placement defaults to `dry_run` — the order is constructed and
validated but NOT submitted unless `dry_run` is explicitly `false`. All
enforcement of the dry-run / testnet / mainnet-jurisdiction gate lives in the
daemon (which is network-aware); this skill's own safety measure is the safe
default. The daemon must be running (`python -m executor.server`); if it is not,
the skill returns a clear "not reachable" error rather than doing anything.

## Trigger Conditions

Use when the user wants to check trading account state, list orders, or place or
cancel a perpetual order via the executor, on Hyperliquid or dYdX.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | Literal["validate","state","orders","place","cancel","health"] | no | "state" | What to do |
| venue | Literal["hyperliquid","dydx"] | no | "hyperliquid" | Which venue |
| symbol | Optional[str] | for place/cancel | None | 'BTC' on hyperliquid, 'BTC-USD' on dydx |
| is_buy | bool | no | True | True = buy/long, False = sell/short |
| size | Optional[float] | for place | None | Order size in base units |
| price | Optional[float] | for place | None | Limit price |
| oid | Optional[int] | for cancel | None | Order id to cancel |
| reduce_only | bool | no | False | Order may only reduce a position |
| dry_run | bool | no | True | Must be explicitly False to place a live order |

## Returns

The daemon's JSON response for the action. Order placement returns either a
`gate` (when refused: `dry_run`, or mainnet `jurisdiction_not_acknowledged`) or a
`submitted: true` result with the venue response. A daemon that is not running
returns `{"error": "...not reachable...", "reachable": false}`.

## Configuration

`apis.executor.url` (default `http://127.0.0.1:8130`) and `apis.executor.timeout`
(default 30s) in ainara.yaml.

## Examples

```
# Input: What's my Hyperliquid account state?
# action: "state", venue: "hyperliquid"
# Output: {"venue":"hyperliquid","perp_account_value":999.0,"positions":[], ...}
```

```
# Input: Place a live buy of 0.001 BTC at 60000 on Hyperliquid
# action: "place", venue: "hyperliquid", symbol: "BTC", is_buy: true,
# size: 0.001, price: 60000, dry_run: false
# Output: {"submitted": true, "response": {... resting oid ...}}
```
