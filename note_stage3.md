# RESUME NOTE — Nexus Apps decoupling (Stage 3a COMPLETE; next: Stage 3b pack.py)

Single source of truth. Stage 3a adopted the `payload/` bundle layout
(D1–D3 decisions below). **How to resume:** run
`scripts/nexus_state_check.sh` (§11), then follow §8 in order. Never batch
stages — apply → verify → proceed.

---

## 1. TL;DR — where we are

- **Stages 1, 2.1–2.5 and 3a COMPLETE.** Stage 3a replaced the nested
  `ainara/nexus/khromalabs/ataria/` payload with a **flat `payload/`
  bundle dir** (byte-for-byte what ships); repo root = dev material.
- Bundle identity/namespace is **manifest-derived**: `provider` + `name`
  → `ainara.nexus.<vendor>.<bundle>`, registered at runtime via
  `framework/nexus_apps.register_bundle_namespace()` (stdlib-only,
  importlib alias — no physical nesting anywhere).
- App-root contract: dev repo = `payload/nexus.json`; installed app =
  `nexus.json` at top (bundle-at-top, D2). Primary root keeps legacy
  vendor layout with a physical-bundle guard (D3: submodule mount stays
  inert; `_scripts` import-noise footgun dead twice over).
- The separate dev checkout was deleted (single-copy layout): the
  submodule mount IS the dev_apps target (probed 8/8, first-wins).
- Frozen baseline unchanged: 8 skill IDs; runtime import paths unchanged;
  config keys unchanged.
- Full supporters run GREEN post-3a (`Artifacts ready`, leak-free,
  PyArmor confirmed). mkdocs docs SOURCE (`docs/`) was lost with the old
  dev checkout (never tracked); last generated `site/` bridged into
  `payload/site` — skill pages regenerate via docs_hook when needed.
- **NEXT: Stage 3b — `_scripts/pack.py` in the ataria repo** (§6; schema
  approved with payload/ layout; Q3 creatorId still pending).

## 2. Commit ledger

### ainara repo (branch dev012)
| Commit | Subject |
|---|---|
| *(Stage 1–2 rows as before: `9ea0e9f3`, `fbf68753`, `1a2de1ad`, `3464a841`, `067918e9`, `25e31824`, `d0e83b04`, `dc1474dd`, `4e4a1bbc`, `4b800686`)* | |
| `698cdc37` | Stage 3 handoff — consolidated note + state-check script |
| `88f24144` | state-check ATARIA_DEV → submodule mount (single-copy layout) |
| `a1a859c5` | payload-based app resolution + namespace aliasing (3a) |
| `0ef54636` | _obfuscate payload resolution for 3a layout |
| *(pending)* | Stage 3a close-out — gitlink bump + note update |

### ataria repo (branch master)
| Commit | Subject |
|---|---|
| `46d459b` | refactor: adopt Nexus app payload layout |
| `a92687d` | refactor: adopt flat payload/ bundle layout (3a Phase 1) |
| `7c6358a` | fix(tools): payload-layout dev tooling + .gitignore (3a Phase 3) |

## 3. Verified facts (observed post-3a — do not re-derive)

- **Frozen baseline (8 sorted nexus skill IDs) UNCHANGED:**
  ```
  khromalabs_ataria_charts_candles
  khromalabs_ataria_crypto_analysis
  khromalabs_ataria_crypto_screener
  khromalabs_ataria_crypto_solanasecurity
  khromalabs_ataria_crypto_tradingaccount
  khromalabs_ataria_crypto_tradingorders
  khromalabs_ataria_crypto_tradingworkbook
  khromalabs_ataria_dashboards_controlpanel
  ```
- **Post-3a harness results (Gate 2/3, all GREEN):** discovery A 8/8 via
  payload alias; discovery B 0 skills with ZERO import noise (vendor-mode
  physical-bundle guard fires on the mount); `resolve_app_payload` unit
  checks (dev repo / installed bundle-at-top / non-app); alias import spot
  checks land under `payload/`; pybridge docs endpoints handle app roots +
  fixture installed bundle; `_resolve_ataria_source` both configs →
  `<mount>/payload`; registries regenerate 8 skills / 3 providers; full
  supporters run `Artifacts ready`, leak-free, PyArmor 9.2.7 header
  confirmed in shipped tree.
- **Payload tree (tracked):** `charts/ crypto/ dashboards/ _components/
  __init__.py nexus.json plans/` (2 runtime plans). Repo root = dev
  material: `plans/store/` (3 yamls, structurally excluded), docs_hook.py,
  generate_registries.py, mkdocs.yml, generate_docs.sh, _scripts/, *.md.
- **Compiled-host trees exclude `plans/` by ignore pattern** (zip
  distributes plans, not the host build). Data files (nexus.json, site/,
  registries) ship from the plain `ataria_compiled` datas; obfuscated code
  from `supporters_compiled/ainara/nexus` — pre-existing spec design.
- Earlier verified facts carried: 2.3 A/B/C fixture runs, 2.4 both modes,
  2.5 helper harness + frozen HTTP smoke (`/docs/list`), namespace mechanics
  (now via aliasing; retroactive extension no longer used).

## 4. Gotchas (consolidated — do not re-derive)

1. `Skill` is an ABC with abstract `matcher_info` — every nexus skill must
   implement it or instantiation silently skips the skill.
2. skills.py: instantiation failures are logged but NOT appended to
   `load_errors` (only import failures are) — deferred fix.
3. Bureau loads plans ONLY from `<config_dir>/bureau/`, never nexus bundles;
   payload `plans/` are templates seeded on first install (manifest
   `plans: [...]`); `plans/store/` stays repo-root dev material.
4. `.gitignore` never affects tracked files; **this machine's global
   gitignore has `*.gitignore`** — ataria's `.gitignore` needed `git add -f`
   (host repo tracks its own the same way).
5. PyArmor 9 with a REGULAR package input is the safe path (bundle-level
   `__init__.py` exists in the payload; exec'd by the alias registration).
6. `_obfuscate.py` copytrees whatever is physically at the resolved source —
   ignore patterns cover `__pycache__`, `*.pyc`, `.pytest_cache`, `plans`.
7. `skills_metadata.json`, `providers_registry.json`, `site/` are generated
   artifacts (now gitignored in ataria); fresh ataria clones lack them
   (guards + pack preflight handle this).
8. mkdocs docs SOURCE (`docs/`) was LOST with the deleted dev checkout
   (never tracked); `payload/site` is the last generated build, bridged.
   Skill doc pages regenerate via docs_hook; hand-written pages would need
   rebuilding from scratch if the source isn't backed up elsewhere.
9. Harness patterns: config-derived paths; temp-config copy for dev_apps
   (never edit the real config); import module-level helpers, not servers.
10. Strict-count patch guards + idempotent re-runs + `git reflog` checks.
11. **Harnesses MUST pin `./venv/bin/python`** — bare `python` (3.14, no
    aiohttp) fakes bundle import failures (6/8 false "broken" once).
12. **Discovery is not side-effect-free** (keyring reads, API-key loads,
    cache sweeps) — keep out of CI without acknowledging this.
13. **`git check-ignore` consults the index by default** — tracked paths
    always exit 1; use `--no-index` to test rules.
14. **`python scripts/x.py` → sys.path[0] = scripts/, NOT the CWD**;
    `python -` → CWD. Probes pass where real script runs fail; host scripts
    importing host code must insert project_root explicitly.
15. RESOLVED (3a): the submodule-mount/root-scan footguns — vendor-mode
    physical-bundle guard + payload/ boundary killed them structurally and
    mechanically. Submodule mount stays INERT (pinned reference only).
16. **APPLY blocks stay gated:** never commit on a failed gate.
17. Cosmetic: subprocess stdout appears before the parent's own prints under
    capture (block buffering) — not an ordering bug.

## 5. Working rules (carried)

- Never batch stages; apply → verify → proceed. Pre-written note text is not
  verification — runs must actually execute.
- Verification = sorted ID lists + exact counts; fixture teardown mandatory.
- Ask for file contents before drafting edits; true file state beats memory.
- Identifier spelling line-by-line; grep broadly; confirm state with
  `git status --short` + `git ls-files -s`, never assume.
- User-level compiled app: no pip / no interpreter / no CLI assumptions.
- Every turn that needs terminal work gets ONE "Commands to run" block,
  INSPECT read-only first, APPLY gated on green output.

## 6. Stage 3b — pack script (COMPLETE: `64bd5a3`)

`_scripts/pack.py` (ataria repo, standalone, zero ainara imports) —
implemented and verified:

```
--polaris-version X.Y.Z  required → requiresPolaris ">=X.Y.Z"
--ainara-root <path>     P1 only ($PROJECT_ROOT fallback); --no-generate skips P1
--out dist/   --sign sk.sec (optional; pubkey expected as <name>.pub)
--gen-keys [--no-password]  keypair into .pack-keys/ (no-password = TEST ONLY)
--allow-placeholder          creatorId lint downgrade (dev/test only)
P0 preflight : payload markers (charts+crypto+dashboards+nexus.json); manifest
               lint (fields, semver, creatorId base58-32 — HARD fail unless
               --allow-placeholder; exit 1 verified)
P1 generate : generate_registries.py (cwd=payload); mkdocs --site-dir
               payload/site (BLOCKED until docs source restored or bridged)
P2 assemble : copytree payload (artifact root == bundle root); nexus.json
               augmented (requiresPolaris, plans [...]); payload never modified
P3 zip       : dist/ataria-<version>.zip (deterministic sorted walk)
P4 sign      : minisign detached .minisig over the whole artifact
P5 verify    : sha256 (+ .sha256 file); extract roundtrip; zip listing ==
               payload-derived expected set EXACTLY + staging agreement;
               re-lint extracted manifest (requiresPolaris, plans array);
               minisign -V
```

**Verification results (Gate, GREEN):** full run with test keypair
(`.pack-keys/ataria-test.*`, unencrypted — throwaway): dist/ataria-0.1.0.zip
(119 files, ~1.03 MB, top-level == 10 expected entries), requiresPolaris
`>=0.11.0`, plans array == extracted plans/, signature roundtrip OK, exit 0;
negative test exit 1 without --allow-placeholder.

**Q3 creatorId**: real pubkey still pending; until then pack with
`--allow-placeholder` for dev/test ONLY — the artifact carries the
placeholder and says so loudly. When the pubkey arrives: edit
`payload/nexus.json`, pack WITHOUT the flag.

(Resolved: Q1 placeholder-in-the-meantime via --allow-placeholder; Q2
--ainara-root; Q4 test keypair now at `.pack-keys/`, release keypair at
first real signed pack — encrypted, NEVER in any repo.)

## 7. Deferred small items

- skills.py: append instantiation failures to `load_errors`; (the
  `_`-prefixed-dir scan issue is RESOLVED structurally by 3a — dev material
  is outside the payload and the vendor-mode guard skips non-bundles).
- Warn on 0-skill bundles (submodule-without-dev_apps footgun now inert; the
  mount is a pinned reference by design — 0 skills without dev_apps is
  EXPECTED, so this item may be droppable).
- nexus.py: `register_nexus_root` branch is dead code (`prefix_module`
  always starts with `ainara.`) — cleanup candidate.
- 6 crypto skills have no UI components — confirm intended.
- **Restore ataria mkdocs docs source** (`docs/`) or accept the bridged
  generated `site/` (§4-8).
- Residual verifications: optional `POLARIS_TARGET=pybridge` frozen build
  (namespace aliasing in frozen mode is the one path not exercised — build
  output placement is unchanged, but verify before Stage 4 wiring).
- Host build-time dev_apps story for Stage 4; post-Stage-4 cleanups (mkdir
  fallback in `NexusSkillProvider.__init__`, drop host `ainara/nexus` tree,
  vendor-layout primary root retirement).
- Scratch `script*.sh` deletion (backups exist elsewhere).

## 8. Resume checklist (in order)

1. Run `scripts/nexus_state_check.sh` → expect GREEN (post-3a EXPECTs).
2. Obtain the real Solana pubkey → set `payload/nexus.json` creatorId (Q3);
   re-pack WITHOUT `--allow-placeholder`; generate the ENCRYPTED release
   keypair (never in any repo) and re-sign.
3. Optionally restore ataria mkdocs `docs/` source to unblock P1.
4. Then Stage 4 (installer + host build cleanup) and Stage 5 (Polaris UI
   install flow; auth/perks UI; Lit protocol) per §10.

## 9. Files to add to the chat at next session

1. ataria: `nexus.json`, `generate_registries.py`, `generate_docs.sh`,
   `mkdocs.yml`, **`docs_hook.py`**.
2. Polaris `package.json`.
3. If fresh session / touching code: ainara `capabilities/skills.py`,
   `capabilities/nexus.py`, `scripts/_obfuscate.py`,
   `scripts/pyinstaller/servers.spec`.
4. (This note + the script are committed — no need to re-add.)

## 10. Stage 4/5 locked decisions (carried)

- One edition end-state: drop `-e`/`POLARIS_EDITION`/`.edition`/supporters
  branches/ataria materialization from host build; host ships no nexus code.
- Installer: verify → extract `<id>.new/` → atomic swap → record; startup
  re-check of `schemaVersion`/`requiresPolaris`.
- Plans: manifest `plans: [...]`; seed `<config_dir>/bureau/` first install
  only; ataria keeps canonical plan sources.
- Wheel = internal transport at most; never pip-installed; no user-level
  interpreter.
- `AuthManager` degrades to public mode without `supporters.auth_core`.

## 11. State-check script

`scripts/nexus_state_check.sh` (committed, idempotent, read-only vs both
repos; modifies only a TEMP config copy). Sections: S1 repos/submodule,
S2 interpreter, S3 discovery A/B (A has keyring/API-key side effects by
design), S4 obfuscate resolution, S5 build outputs, S6 pack prerequisites.
Final line: `RESULT: N pass / M fail / K warn` + `STATE: GREEN|RED`.
When the ledger advances, update the `EXPECT_*` variables at the top.
