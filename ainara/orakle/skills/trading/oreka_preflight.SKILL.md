---
name: "trading_oreka_preflight"
version: "0.1.0+7e485b3"
oreka_version: "0.1.0"
oreka_commit: "7e485b3"
copied_on: "2026-08-27"
description: "Preflight the Oreka desk: config, venue credentials verified at the venue, gates, size caps, daemon and watchdog liveness"
category: "trading"
---

# Oreka Preflight

## Description

Runs the **Oreka** desk's preflight and summarises it: which config file was
actually resolved, whether each venue's credentials are accepted *by that venue*,
which network each one is really on, the state of the dry-run and jurisdiction
gates, whether both size caps are set, whether the dYdX authenticator's scope
covers the coins configured, and whether the daemon and watchdog are alive.

Its guiding rule is worth knowing when reading the result: it prefers what the
**running daemon** reports over what the YAML says. Services read their config
once at startup, so a file edited afterwards is a file the daemon is not using.
"I set it to mainnet" and "it is on mainnet" are different claims.

**Read-only.** Every check is a read; nothing here can place, cancel or modify an
order.

## Trigger Conditions

Use when the user asks whether their desk is healthy, safe to run, or correctly
configured; whether the watchdog is alive; whether an alarm is being raised; or
after they have changed configuration and want to know it took effect.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| verbose | bool | no | false | true returns every check; false returns only failures and warnings plus counts |

## Returns

```jsonc
{
  "healthy": true,            // false on ANY failure; null if preflight could not run
  "failures": 0,
  "warnings": 3,
  "summary": "no failures, 3 warning(s)",
  "needs_attention": [ { "check": "...", "status": "warn", "detail": "..." } ],
  "checks": null              // the full list, when verbose
}
```

**Warnings are frequently intended.** Running on mainnet, a jurisdiction gate the
operator opened on purpose, and `dry_run` set false all warn by design — they are
states to be aware of, not faults. Report what they say rather than counting
them. A failure is different and blocks running.

`healthy` is `null`, never `false`, when the preflight itself could not run — an
unknown and a known-bad must not read alike.

## Configuration

Reads Oreka's own config, not `ainara.yaml`. Requires Oreka importable by Orakle;
otherwise returns `{"installed": false, "healthy": null, "error": "..."}`.
