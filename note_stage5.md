# NOTE — Stage 5: Nexus subscriptions end-to-end (identity → install → guard)

> Status: **DONE and production-verified** — Ruben completed a real
> subscribe + install + guarded-skill-execution cycle against
> `ataria.nexus` with his real wallet/creatorId. Companion to
> `note_stage4.md` (read §6 of that note first for the earlier
> direction-setting). This note covers five stages (A–E) plus the
> production-debugging tail, across three repos:
> ainara (host), ainara_licensing (closed, formerly `ainara_supporters`),
> ataria (bundle submodule).

---

## 1. What exists now (the one-paragraph version)

Nexus Apps are installed by **typing a name** (`ataria` → TLD `.nexus`
default). The installer fetches `https://<host>/.well-known/nexus-app.json`
(self-signed ed25519 by the bundle's `creatorId` Solana key), verifies
the chain (TLS → doc identity sig → artifact sha256 → inner manifest
identity sig → doc binding), requires an **NFT-ownership subscription**
(on-chain check, per-bundle), then atomically swaps the bundle into
`<data.directory>/nexus/.apps/<vendor>.<app>/`. Subscriptions are
machine-bound tokens issued by a **closed licensing core**
(`nexuslicensing.auth_core.NexusSubscriptionCore`, shipped compiled with
Polaris) and stored in system storage under
`nexus_sub:<vendor>:<app>`; each packed bundle carries **license guards**
(extracted primitives re-emitted by the injector) that verify that token
locally on every skill call. The wizard exposes only Install/Uninstall;
subscription is an implementation detail.

## 2. Stage ledger (ainara commits unless noted)

| Stage | Commit(s) | Content |
|---|---|---|
| A | ainara_licensing `d827886` | `NexusSubscriptionCore` in the closed module: targets-aware Metaplex check (collection/creator, fail-closed), app-bound tokens (`"a"` payload field), per-bundle storage keys, receipt codes (`XXXX-XXXX-XXXX` Crockford), background refresh/revocation |
| B | `a3b015c5` | `framework/nexus_licensing.py` (fail-closed seam, **no public mode**) + `verify_manifest_identity` (open, solders) + pybridge endpoints: `GET /nexus/apps`, portal, `POST /nexus/subscription/verify`, `DELETE /nexus/subscription/<v>/<a>` |
| C | `349ccd68` | `framework/nexus_installer.py` (protocol v0), `/nexus/install/resolve` + `/nexus/install` (409 `subscription_required`), portal target echo for pre-install subscription, wizard "Add a Nexus App" box + status cards + explorer links |
| D | ataria `744cbfb` | pack **P2a: manifest identity signing** (mandatory, no `--allow-placeholder` escape), `--manifest-key`/`--manifest-sig`/`--dump-manifest`, `--emit-doc`, `scripts/nexus_sign.py` (sign-canonical/sign-doc/merge-docs for multi-platform) |
| E | `bdf6d4d3` | Supporters relics removed: `framework/auth.py`, `/auth/*` endpoints, wizard auth block, reauth mode, `.edition`; closed module slimmed (`SupportersAuthCore` retired, `c43825b`); `--supporters-root` → `--licensing-root` (ataria `691649d`), package `supporters` → `nexuslicensing` (licensing `285f2ab`) |

Post-E fixes and the wizard rework (all `GREEN` on
`scripts/nexus_state_check.sh`): route-wipe restore `f60a8d37`,
crash-resilient seam `e1c4f6ed`, portal target echo `1ad4fd7e`,
UX rework `5eba8c9c` (auto-subscribe+install chaining, uninstall,
badge change, Orakle reload), uninstall reload + modified filter
`102ebd44`. Guide: ataria `notes/pack_and_install.md` (rewritten;
§6.1 cold-wallet workflow, §6.2 multi-platform, §6.3 the three keys,
§6.4 deployment to ataria.nexus).

## 3. Contracts that must not break

1. **Canonical identity serialization is byte-identical across three
   implementations**: `pack.py::canonical_manifest_bytes`,
   `nexus_sign.py`, `framework/nexus_licensing.py` — JSON, sorted keys,
   compact separators, `signature` field excluded, verified against
   `creatorId`. Fail-closed on missing/invalid.
2. **Doc protocol v0**: `https://<host>/.well-known/nexus-app.json`
   (`.nexus` default TLD; loopback http allowed for dev only; 404 maps
   to a distinct `not_found` reason). Doc fields: protocol/vendor/app/
   latest/description/creatorId/protection/signature/artifacts[{platform,
   url,sha256}]. Platform tags match pack.py (`linux-x86_64`,
   `win-amd64`, `universal` fallback).
3. **Pack pipeline**: P0 lint → P1 registries + docs site → P2
   stage/augment → **P2a identity signing (unconditional)** → P2b guard
   injection + PyArmor (protected only) → P3 zip → P5 verify. No minisign
   (removed in Stage E; historical note in the guide — protocol v1 would
   reintroduce it as a doc-anchored `release_key`).
4. **Guard contract**: `inject_license_guards.py` extracts
   `_machine_id`, `_derive_key`, `_machine_hash`, `_verify_session_token`
   + `TOKEN_VERSION`, `KDF_INFO`, `TOKEN_MAX_AGE` from `auth_core.py` —
   frozen symbol names. Guards take `--bundle-id vendor/app` and read
   `nexus_sub:<vendor>:<app>` from system storage (`chat_memory.db`
   db_metadata, read-only sqlite), verifying with
   `expect_app=<bundle id>` (cross-bundle transplant denied).
5. **Token lifecycle**: issued by the closed core at subscription time,
   machine-bound (machine-id hash in payload), 7-day validity = offline
   grace, ~1-day background refresh, `False` RPC → token+code+targets
   deleted. Storage keys: `nexus_sub:<v>:<a>` / `:code` / `:targets`.
6. **Build secret pairing**: the issuer (licensing core,
   `<licensing-checkout>/build/build_secret.key`) and the bundle guards
   (pack-time `.pack-keys/build_secret.key`) MUST share the same secret —
   mismatch symptoms: subscription activates but skills deny at runtime.
   Never rotate casually; never commit it.

## 4. Gotchas learned the hard way (all now gated or documented)

- **Stage E route wipe**: deleting the `/auth/*` region also deleted the
  `/nexus/*` endpoints (they lived inside it). Import smokes don't catch
  route loss → `nexus_state_check.sh` S1 now asserts ≥6
  `@app.route("/nexus` routes (fixed `f60a8d37`).
- **Portal handoff**: pre-install verify needs the doc-derived
  collection/creator echoed by the portal page (installed apps read the
  manifest instead). Fixed `1ad4fd7e`.
- **Closed-core NFT check**: three stacked bugs — `Pubkey.to_bytes()`
  doesn't exist in solders (creator path crashed when BOTH targets set),
  None-target parse in creator-only mode, and `_execute_rpc_check` never
  forwarded collection/creator to the wallet scan (rotation always ran
  fail-closed → "No valid subscription NFT found in wallet"). All fixed
  + offline regression gates with crafted Metaplex metadata
  (licensing `1a2c6ad`, `77899c6`). NOTE: "no match" and "check failed"
  are still indistinguishable — distinguishing them is a future
  hardening item.
- **P1 docs**: `mkdocs.yml` lives in `scripts/` — pack ran it from repo
  root (broken since the reorganization); docs_hook regenerates ALL
  pages from the payload, so the "lost docs source" was just a missing
  container; mkdocs must run under the **venv interpreter** (binary deps
  like onnxruntime can't cross interpreter versions — system-mkdocs
  produced the misleading "onnxruntime is not installed"). Fixed ataria
  `48686a6`/`f0a85fe`; 8/8 skill pages documented.
- **`.well-known/` is a dot-directory**: server configs may block
  dot-paths; python-urllib default UA got 403 (installer UA passes).
  Documented in guide §6.4.
- **Pack failures are loud**: missing site/registries abort P1 (run
  without `--no-generate` + `--ainara-root`); invalid creatorId/signature
  abort P2a; guard injection failure aborts P2b. Never commit on a red
  gate (held all session).
- State-check anchors (`EXPECT_GITLINK`) advance with every submodule
  pin — a RED check blocks work (verified with a negative test this
  session).

## 5. Wizard UX (current model)

User only sees Install/Uninstall. Install chains: resolve → (gated &&
unverified) portal + poll → install → `nexus:reload-orakle` IPC →
poll `/capabilities` until properties appear → refresh. Uninstall
(`DELETE /nexus/app/<v>/<a>`, path-guarded) keeps the subscription token
(reinstall never re-subscribes) and mirrors the reload. "Show only
modified properties" toggle restored in the Nexus search container
(composes with text search). Badges: `Subscription active` (NO expiry
date — the offline-grace date was misread as an access expiry; expiry
stays in the API), receipt code, identity-verified. Gated cards state
the NFT requirement explicitly with collection/creator explorer links
(solscan, via `open-external` IPC with scheme validation).

## 6. Dev-run facts

- Source Polaris needs `AINARA_NEXUS_LICENSING_PATH=<licensing checkout>`
  (fail-closed 503s say so); packaged builds ship the compiled
  `nexuslicensing` package and don't need it. Documented in README.
- Licensing checkout: `/home/ruben/lab/src/ainara_licensing` (user
  renamed it from `ainara_supporters`; repo name itself still says
  supporters — cosmetic, user's call).
- Suites: `scripts/test_nexus_licensing.py` (identity + seam +
  crash-resilience + delegation), `scripts/test_nexus_installer.py`
  (protocol v0 e2e, 10 checks),
  `<licensing>/tests/test_auth_core.py` (25 offline checks incl. crafted
  metadata + rotation regression),
  `bash scripts/nexus_state_check.sh` (16 pass / 0 fail expected).
- Deployment: see guide §6.4 (layout, per-release ritual, server
  gotchas). Production verify one-liner:
  `resolve_source('ataria')` from the venv.

## 7. Open items (resume here)

1. **Orakle hot capabilities reload** — post-install/uninstall currently
   restarts the Orakle process via ServiceManager; a reload endpoint
   would make it seamless (also benefits user-skill editing + store).
2. **Vault master key has no UI path** — `/vault/setup` exists but
   nothing calls it since `/auth/verify` removal (pre-existing public-
   edition condition; the vault runs in degraded no-master-key mode).
3. **Windows pack** — never run end-to-end; needs pyarmor on Windows
   + §6.2 merge flow. Probe with the §4 discovery test on a Windows box.
4. **`verifyCreator` batch** — `B268uYgw…` is `verified: 0` in the NFT
   creators vec (mint-flow artifact; the collection itself IS verified,
   which is what our checker uses). Cosmetic/marketplace hygiene;
   creator-signed, works retroactively on distributed mints.
5. **Protocol v1 `release_key`** — doc-anchored minisign-style release
   key + two-tier signing (cold identity signs rarely; hot release key
   signs releases) when the store scenario justifies it.
6. **`dist/` artifacts are test-key signed** — Ruben must re-pack with
   the real identity key and deploy the signed doc for any real
   distribution (the production test bundle was real; keep it in sync).
7. Repo cosmetics: licensing repo dir name, `dist/` reproducibility
   (zipfile mtimes), 6 ataria skills without UI components (old item).
8. **Auto-install** is implemented (chained); consider an "update"
   auto-flow later (same chain, triggered by `latest > installed`).
