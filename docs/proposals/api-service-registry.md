# Proposal: Centralized API Service Registry & Credential Broker

**Status:** Draft — discussion and decision tracking in [Issue #38](https://github.com/khromalabs/ainara/issues/38); this document is the versioned record, with major decisions from the thread backported here.
**Author:** Rubén Gómez
**Date:** 2026-11-15
**Related:** Issue #38 (discussion), Issue #17 (tiered skills model), Issue #18 (operation authorization/policy system), Nexus Apps & Subscriptions (README)

---

## 1. Motivation

Two problems that share a root cause: **per-service knowledge has no single
home**.

### 1.1 Fragmentation (engineering)

Adding one configurable API service today touches five files, each encoding the
same service facts in a different format:

| Fact | Current location |
|------|------------------|
| Key path + default value | `resources/ainara.yaml.defaults` |
| Schema | `resources/config.schema.json` |
| Key test logic | `ainara/framework/pybridge.py` (`_validate_skill_key`) |
| Description + signup URL | `polaris/components/setup/core/utils.js` (`getKeyDescription`) |
| Display name | `formatKeyName()` string munging |

This has already produced drift: `utils.js` shipped a duplicated
`coinmarketcap` entry whose text silently overrode the first. Every new service
(CoinMarketCal was the nth instance) repeats the full dance, and the validator
in `pybridge.py` grows as an ever-longer `elif` chain of bespoke implementations.

### 1.2 Platform security & UX (architectural)

As a platform hosting **third-party Nexus Apps**, the current model has two
issues:

1. **Secret exposure.** API keys live in user config. Any skill or Nexus app
   that can read config — or that is handed raw credentials — can exfiltrate
   them. For first-party core skills this is acceptable (local-first,
   user-authoritative), but third-party Nexus bundles are semi-trusted vendor
   code; handing them raw keys is a security hole.
2. **Configuration hassle.** Each new Nexus app that needs an external API
   adds a new configurable key surface. The user ends up configuring the same
   service (or equivalent services) N times, in N places.

## 2. Proposed model

### Part A — Service registry (declarative, fixes fragmentation)

A single YAML file, `resources/api_services.yaml`, declares every configurable
API service. One entry per service:

```yaml
services:
  coinmarketcal:
    display_name: CoinMarketCal
    category: crypto
    signup_url: "https://developers.coinmarketcal.com/"
    description: "Cryptocurrency events calendar (upcoming coins, listings, partnerships)."
    auth: api_key            # api_key | oauth | self_hosted | custom
    credentials:
      api_key:
        config_path: apis.coinmarketcal.api_key
        secret: true
    validate:
      request:
        method: GET
        url: "https://api.coinmarketcal.com/v1/events"
        headers:
          X-API-KEY: "${api_key}"
          Accept: "application/json"
        params:
          max: 1
      success: status_2xx    # optionally: json path checks
```

Everything else becomes generic machinery:

- **PyBridge**: `_validate_skill_key()` becomes an interpreter of `validate`
  blocks (template substitution + HTTP call + success predicate). A new
  `GET /api-services` endpoint serves the registry to the frontend (the
  registry contains no secret material).
- **Wizard**: `getKeyDescription()` and its hardcoded map are replaced by
  rendering from the registry fetched via `/api-services`; config groups still
  drive which cards render (registry ∩ config). Card descriptions, signup
  URLs and display names stop drifting.
- **Defaults/schema**: either generated from the registry at build time, or
  kept thin and validated against the registry (open question, §5).
- **Extension mechanism**: Nexus apps may ship service descriptors for
  services unknown to the core registry, merged at discovery time — an app
  that needs an exotic API can contribute the card, the user still configures
  it in the wizard once.

Oddballs that don't fit the `api_key` shape (`searxng` base_url + optional
key, `email` IMAP accounts, `hyperliquid` multi-field) are handled by the
`auth` field and a `custom` escape hatch that falls back to present-day
per-service code, so the registry is honest about what it standardizes.

### Part B — Credential declarations & broker (fixes security + UX)

Extends the existing `required_data` pattern to credentials:

1. **Declaration.** Skills and Nexus apps declare
   `required_credentials: ["coinmarketcal", ...]` — service IDs, never keys.
   Validated at discovery; unknown IDs fail loudly.
2. **Configure once.** If the user lacks a declared credential, the wizard (or
   the app install flow) surfaces a card *for the missing service* from the
   registry. The user enters each key once, centrally; every app declaring it
   just works. No per-app key management.
3. **Two access tiers at runtime:**
   - **Brokered (default).** The app never sees key material. It calls e.g.
     `skill.request_api("coinmarketcal", params)`; the framework performs the
     HTTP request locally with the credential attached, guided by the
     registry's endpoint contract. Brokered calls are logged and policy-checked.
   - **Raw grant (escape hatch).** For services that can't fit the broker
     contract, the user explicitly consents per app ("this app may use your
     X credential directly"), following the issue #18 policy model:
     user-level authorization, framework-owned UX, revocable.

This aligns with existing framework principles: secrets stay in
user-authoritative config; consent is a framework responsibility, not per-skill
UX; apps stay declarative.

**Caveat:** brokered-by-default constrains app authors to the registry's call
contract. The raw-grant escape hatch is the pragmatic mitigation; the
core registry is expected to grow descriptors for the most common services.

## 3. Phased roadmap

| Phase | Scope | Risk |
|-------|-------|------|
| **1. Registry** | `resources/api_services.yaml`; PyBridge generic validator + `/api-services`; wizard renders from registry; migrate existing services; CoinMarketCal becomes registry-native | Mechanical, low. Behavior-preserving refactor |
| **2. Declarations** | `required_credentials` on `Skill`; wizard renders missing-credential cards on demand | Low-medium; touches discovery + wizard install flow |
| **3. Broker & grants** | `request_api()` brokered calls; per-app raw-grant consent UI tied to issue #18 | Medium; new runtime surface, needs design detail |

Phase 1 is independent and can land before the policy system exists; phases 2–3
compose with issue #18.

## 4. Out of scope (for now)

- OS keychain / encrypted secret storage (config.py masking remains the
  interim mechanism; worth a separate proposal).
- OAuth flows beyond declaring `auth: oauth` (Twitter/Reddit-style flows need
  their own design).

## 5. Open questions

1. Generate `ainara.yaml.defaults` / `config.schema.json` from the registry,
   or keep them hand-maintained and validated against it?
2. Does the brokered-call surface belong on the `Skill` base class, or as a
   framework-injected capability object (mirrors the Orakle Middleware split)?
3. For raw grants: per-app consent, per-bundle, or policy-profile driven
   (issue #18 alignment)?
