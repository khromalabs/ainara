# RESUME NOTE — Nexus Apps decoupling (Stage 3 in progress)

**Supersedes** `note_day3_close_out.md` (removed in the same commit; content
consolidated here) and all scratch `script*.sh`. Single source of truth.
**How to resume:** run `scripts/nexus_state_check.sh` (§11), add the files in
§9 to the chat, answer §6's four open questions, then follow §8 in order.
Never batch stages — apply → verify → proceed.

---

## 1. TL;DR — where we are

- **Stages 1, 2.1–2.5 COMPLETE** (multi-root discovery, dev_apps precedence,
  pybridge docs). Ainara `dev012` @ `4b800686`; ataria `master` @ `46d459b`.
- **Ataria materialized in the host as a GIT SUBMODULE** (gitlink @ `46d459b`,
  absorbed gitdir, URL `khromalabs:ataria.git` verified reachable) — commit
  `25e31824`. Role split (P1, harness-verified): mount = pinned reference +
  chat transport; **runtime truth = `nexus.dev_apps`** (8/8 frozen baseline).
- **`_obfuscate.py` is submodule-safe** (payload-source resolution `d0e83b04`
  + script-mode sys.path fix `4e4a1bbc`). Full supporters run GREEN: license
  guards 8/8, PyArmor clean, staged tree == allowlist, leak count 0.
- **D-B minisign CLOSED:** real binary `/usr/bin/minisign`, roundtrip OK.
- **NEXT: Stage 3 — `_scripts/pack.py` in the ataria repo.** Schema drafted
  (§6); FOUR answers pending before implementation.

## 2. Commit ledger

### ainara repo (branch dev012)
| Commit | Subject |
|---|---|
| `9ea0e9f3` | Stage 1 — `__version__` → ainara.framework, PEP 420 namespaces |
| `fbf68753` | Stage 2.1+2.2 — `get_nexus_base_paths()` + sys.path prepending |
| `1a2de1ad` | Stage 2.3 — multi-root `discover()`, first-wins `seen_bundles` |
| `3464a841` | Stage 2.5 — pybridge multi-root docs |
| `067918e9` | note_day3_close_out added, old notes removed |
| `25e31824` | ataria as git submodule (transitional, P1) + old note §11 |
| `d0e83b04` | obfuscate: payload-source resolution, submodule-safe staging |
| `dc1474dd` | old note §12 |
| `4e4a1bbc` | fix: repo root on sys.path for script-mode config import |
| `4b800686` | old note §13 |
| *(pending)* | Stage 3 handoff — this note + state-check script |

### ataria repo (branch master) — UNCHANGED all session
| Commit | Subject |
|---|---|
| `46d459b` | refactor: adopt Nexus app payload layout |

## 3. Verified facts (observed — do not re-derive)

- **Frozen baseline (8 sorted nexus skill IDs):**
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
- **Submodule harness:** A (dev_apps set) = 8/8 exact baseline, dev root
  first, first-wins skip line on the primary scan. B (unset) = 0 skills with
  `_scripts/*.py` import noise — the documented footgun.
- **Obfuscate resolution harness:** dev_apps set → dev nested payload,
  artifacts complete; dev_apps None → mount nested payload (fresh clone:
  missing `providers_registry.json`, `skills_metadata.json`, `site/` — the
  artifact guard fires by design). Resolution NEVER returns a repo root.
- **Full supporters run post-fix:** `Artifacts ready`; staged tree is exactly
  `charts/ _components/ crypto/ dashboards/ __init__.py nexus.json
  providers_registry.json site/ skills_metadata.json`; leak count 0.
- **UI components:** only `ChartsCandles` + `DashboardsControlpanel` exist in
  `_components/`; the 6 crypto-skill "component not found" warnings are
  genuine pre-existing absences (deferred question, §7).
- **Discovery instantiates skills** → real side effects observed: keyring
  reads, API-key loads (`CCXTTradingProvider: Using api_key 0x81...`), cache
  sweeps. Harness A is not side-effect-free.
- Earlier verified facts carried: 2.3 A/B/C fixture runs, 2.4 both modes,
  2.5 helper harness + frozen HTTP smoke (`/docs/list`), namespace mechanics
  (retroactive `ainara.__path__` extension works in dev AND frozen).

## 4. Gotchas (consolidated — do not re-derive)

1. `Skill` is an ABC with abstract `matcher_info` — every nexus skill must
   implement it or instantiation silently skips the skill.
2. skills.py: instantiation failures are logged but NOT appended to
   `load_errors` (only import failures are) — deferred fix.
3. Bureau loads plans ONLY from `<config_dir>/bureau/`, never nexus bundles;
   ataria `plans/*.yaml` are templates (pack: manifest `plans:` array).
4. `.gitignore` never affects tracked files.
5. PyArmor 9 with a REGULAR package input is the safe path (bundle-level
   `__init__.py` exists in the payload).
6. `_obfuscate.py` copytrees whatever is physically at the resolved source —
   payload hygiene matters; ignore patterns now cover `__pycache__`,
   `*.pyc`, `.pytest_cache`.
7. `skills_metadata.json`, `providers_registry.json`, `site/` are gitignored
   generated artifacts; a fresh ataria clone lacks them (guards + pack
   preflight handle this).
8. `docs/` = mkdocs SOURCE at the ataria repo root; `site/` is generated.
9. Harness patterns: config-derived paths; temp-config copy for dev_apps
   (never edit the real config); import module-level helpers, not servers.
10. Strict-count patch guards + idempotent re-runs + `git reflog` checks.
11. **Harnesses MUST pin `./venv/bin/python`** — bare `python` (3.14, no
    aiohttp) fakes bundle import failures (6/8 false "broken" once).
12. **Discovery is not side-effect-free** (see §3) — keep out of CI without
    acknowledging keyring/API-key reads.
13. **`git check-ignore` consults the index by default** — tracked paths
    always exit 1; use `--no-index` to test rules.
14. **`python scripts/x.py` → sys.path[0] = scripts/, NOT the CWD**;
    `python -` → CWD. Probes pass where real script runs fail; host scripts
    importing host code must insert project_root explicitly.
15. **A submodule mounts the repo ROOT, never a subdirectory** — the mount
    root's depth-2 glob sees only `_scripts/*.py`; the nested payload is
    invisible to discovery. Builds must never copytree the mount root.
16. **APPLY blocks stay gated:** commits `d0e83b04`/`dc1474dd` landed despite
    a failed gate (process slip); fixed forward via `4e4a1bbc`. Never commit
    on a failed gate again.
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

## 6. Stage 3 — pack script (schema drafted; implementation pending)

`_scripts/pack.py` (ataria repo, standalone, zero ainara imports):

```
--polaris-version X.Y.Z  required → requiresPolaris ">=X.Y.Z"
--out dist/   --sign sk.sec (optional)   --no-generate (trust existing site/registries)
P0 preflight : payload markers; nexus.json lint (required fields, semver,
               creatorId != placeholder — HARD fail)
P1 generate  : generate_registries.py (cwd=payload, new --ainara-root/
               --vendor/--bundle args); mkdocs build --site-dir <payload>/site
P2 assemble  : stage/ = allowlist copy + plans/*.yaml (top-level only,
               store/ excluded) + nexus.json augmented (requiresPolaris,
               plans: [...])
P3 zip       : dist/ataria-<version>.zip — ARTIFACT ROOT == BUNDLE ROOT
P4 sign      : minisign detached .minisig (whole artifact)
P5 verify    : roundtrip; unzip listing == allowlist EXACT set; lint; sha256
```

**FOUR answers needed before implementation:**
1. **Q5 nod** — approve schema + artifact-root==bundle-root tree + manifest
   stays named `nexus.json` (new fields inside its `manifest` object).
2. **`docs_hook.py`** — add to chat: last unknown for P1 (does it need
   PROJECT_ROOT / the host ainara checkout? `generate_docs.sh` hardcodes it).
3. **`creatorId`** — replace `YOUR_SOLANA_PUBLIC_KEY_HERE` with the real
   pubkey in ataria's `nexus.json` (preferred) or a `--creator-id` pack flag?
4. **Keypair** — generate the real minisign keypair now (`pack.py
   --gen-keys`, one-time) or defer until first signed pack?

## 7. Deferred small items

- skills.py: append instantiation failures to `load_errors`; skip
  `_`-prefixed SUBdirectories in the skill glob (today `_scripts/*.py` is
  import-attempted on every scan).
- Warn on 0-skill bundles (submodule-without-dev_apps footgun).
- nexus.py: `register_nexus_root` branch is dead code (`prefix_module`
  always starts with `ainara.`) — cleanup candidate.
- 6 crypto skills have no UI components — confirm intended.
- Residual verifications: `ls build/ataria_compiled/ainara/nexus/khromalabs/ataria`;
  spec `_required_trees` existence check; optional
  `POLARIS_TARGET=pybridge` frozen build (or after Stage 4 wiring).
- Host build-time dev_apps story for Stage 4; post-Stage-4 cleanups (mkdir
  fallback in `NexusSkillProvider.__init__`, drop host `ainara/nexus` tree).
- Scratch `script*.sh` deletion (backups exist elsewhere).

## 8. Resume checklist (in order)

1. Run `scripts/nexus_state_check.sh` → expect GREEN (or update EXPECT_*).
2. Add §9 files to the chat.
3. Answer the four §6 questions.
4. Implement `pack.py` → review → verify (pack → allowlist → lint → sign
   roundtrip → sha256).
5. Then Stage 4 (installer + host build cleanup) and Stage 5 (Polaris UI
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
