# FORENSIC NOTE — Nexus Apps decoupling, Stages 3a + 3b (session of 2026-10-01)

Companion to `note_stage3.md` (forward-looking resume note). This document is
the historical/audit record of one working session: what was found, decided,
changed, verified, and what went wrong along the way. Written for later
review — every claim below was observed in-session, and every gate result is
reproducible via §12.

---

## 1. Scope

Resuming from `note_stage3.md` @ ainara `698cdc37` (Stage 3 handoff, GREEN):

- **Stage 3a** — replace the nested `ainara/nexus/khromalabs/ataria/`
  payload layout inside the ataria repo with a flat `payload/` bundle
  directory; derive bundle identity/namespace from the manifest; rewire
  runtime discovery, config, pybridge docs, build tooling and dev scripts.
- **Stage 3b** — implement `_scripts/pack.py`: payload → linted, augmented,
  zipped, minisign-signed, exactly-verified distributable artifact.

End state: ainara `dev012` @ `91a43f1b`, ataria `master` @ `64bd5a3`, state
check **19 pass / 0 fail / 1 warn** (the warn is the intentional creatorId
placeholder), signed artifact in `dist/`.

## 2. Starting state (verified at session open)

- ainara `dev012` @ `698cdc37`, clean tree. The handoff commit had actually
  landed (the note still listed it as "pending" — first correction of the
  session, made in the note during Phase 4).
- ataria submodule @ `46d459b`, clean, in-sync, absorbed gitdir, remote
  `ruben@online:git/ataria.git` reachable.
- Separate dev checkout existed at `/home/ruben/lab/src/ataria`
  (`ATARIA_DEV`, the `nexus.dev_apps` target) — or so it seemed (§6.1).
- State check: 19 pass / 0 fail / 1 warn (creatorId placeholder).
- Layout: nested payload `ainara/nexus/khromalabs/ataria/` inside the ataria
  repo; discovery reached it only via `dev_apps` (mount found 0 skills +
  `_scripts/*.py` import noise — the documented footgun).

## 3. Design evolution (three proposals, two pivots)

1. **Assistant proposal — manifest allowlist** (`manifest.bundle.roots`):
   withdrawn by the assistant itself after user challenge ("why care about
   what's outside the payload?"). Reason: with a structural boundary the
   allowlist is redundant; a tripwire assertion suffices (this became P5).
2. **Flat repo + reserved `_dev/` dir**: viable, but boundary-by-exclusion
   is fail-open (new top-level clutter ships silently).
3. **`payload/` dir (user proposal, ADOPTED)**: boundary-by-inclusion,
   fail-closed; requires zero naming conventions; `_components/` keeps its
   name (it had broken both underscore-convention variants); matches the
   project's existing vocabulary ("payload" everywhere in tooling/notes).

Consequence chain: identity (`provider` + `name`) already in `nexus.json`
drives the namespace and install paths; physical nesting exists nowhere
except at install time.

## 4. Locked decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | 2 runtime plans → `payload/plans/`; `plans/store/` (3 yamls) stays repo-root dev material | plans ship in the zip; store variants excluded *structurally*, replacing the pack rule "store/ excluded" |
| D2 | Installed apps = bundle at top (`.apps/<id>/nexus.json`); dev repos = `payload/nexus.json` | installer unzips + atomic-swaps with zero renaming; resolver supports both shapes for near-free |
| D3 | Submodule mount stays INERT (pinned reference only); vendor-mode scan skips dirs without `nexus.json`/`__init__.py` | keeps harness B cheap (0 skills, no keyring side effects); kills the `_scripts` import-noise footgun mechanically |
| Q1 | Placeholder creatorId stays; `pack.py --allow-placeholder` downgrades lint to a loud warning (dev/test only) | real pubkey pending; default remains hard-fail so no real release can ship a placeholder |
| Q2 | P1 docs generation needs the host ainara checkout → `--ainara-root` (required, no silent default) | `docs_hook.py` imports `ainara.framework.*` through skill modules; stale hardcodes had already bitten twice |
| Q4 | Throwaway unencrypted test keypair now (`.pack-keys/`, gitignored); encrypted release keypair only at first real signed pack, never in any repo | key hygiene; P4/P5 still exercised end-to-end |

## 5. Commit ledger (chronological, both repos)

### ainara `dev012` (base `698cdc37`)
| # | Commit | Subject / content |
|---|--------|-------------------|
| 1 | `88f24144` | state-check `ATARIA_DEV` → submodule mount (single-copy layout); `-e` for gitfile; [two S6 path edits were applied then reverted within this working step — see §6.2] |
| 2 | `a1a859c5` | new `framework/nexus_apps.py`; `config.py` app-root contracts; `nexus.py` app-mode discovery + `_load_bundle` + vendor guard + namespace aliasing (sys.path injection removed); `pybridge.py` docs endpoints app-shape aware |
| 3 | `0ef54636` | `_obfuscate.py`: resolution via `resolve_app_payload`; `plans/` excluded from compiled trees; messages updated |
| 4 | `312fa96d` | Stage 3a close-out: gitlink `46d459b`→`7c6358a`; note update; state-check EXPECTs + payload markers |
| 5 | `02edb008` | Stage 3b complete — note §6/§8 updated |
| 6 | `91a43f1b` | Stage 3b ledger close — gitlink → `64bd5a3` |

### ataria `master` (base `46d459b`)
| # | Commit | Subject / content |
|---|--------|-------------------|
| 1 | `a92687d` | flat `payload/` layout: `git mv` nested payload → `payload/`; 2 plans → `payload/plans/`; `plans/store/` stays at root |
| 2 | `7c6358a` | dev tooling for payload layout: `generate_registries.py` (`--ainara-root`, manifest identity, alias, dead identity-recovery removed), `docs_hook.py` (payload scan + alias), `.gitignore` (force-added — §6.5) |
| 3 | `64bd5a3` | `_scripts/pack.py` + `.gitignore` (`dist/`, `.pack-keys/`) |

All commits pushed. Author identity: `Ruben Gomez <ruben@khromalabs.org>`
(configured repo-locally in the submodule — §6.3).

## 6. Incidents & deviations register

1. **Dev checkout missing** (`/home/ruben/lab/src/ataria` gone; FS-wide
   search found no copy). Session's state-check had passed 8/8 hours earlier
   — mechanically impossible without that dir. Faithful S3-A re-run yielded
   0 skills, proving the directory vanished mid-session (externally; nothing
   in-session touched it). User confirmed intentional deletion ("the
   submodule is a full copy"). Resolution: single-copy layout — `dev_apps`
   now targets the mount (probed 8/8 with first-wins dedup BEFORE any
   config change). Forensic note: this invalidated the note's P1 role split
   ("mount = reference, dev_apps = truth") — collapsed by design into D3.
2. **Premature edits (caught, reverted)**: while repointing `ATARIA_DEV`,
   two S6 path edits (`payload/nexus.json`, `payload/plans/`) were applied
   although the restructure hadn't happened — would have turned S6 red.
   Reverted in the same working step; re-applied for real in Phase 4. No
   run depended on the wrong state at any point.
3. **Submodule had no git identity** — first Phase-1 commit aborted
   ("Author identity unknown"). Fixed repo-locally to match the host repo's
   identity; commit authorship consistent.
4. **Global gitignore has `*.gitignore`** (`~/.gitignore_global:6`) —
   `git add .gitignore` refused in ataria. Host repo tracks its own
   `.gitignore`, so `git add -f` was used for consistency. Same global rule
   explains the pre-existing mystery of ignored-by-exclude files in the
   mount (`__pycache__` ignored with no visible `.gitignore`).
5. **mkdocs docs SOURCE lost**: `docs/` was never tracked in ataria and
   lived only in the (deleted) dev checkout. `mkdocs build` fails
   (`docs_dir` missing). User recalls no hand-written pages. Mitigation:
   last generated `site/` (119-file build from the previous supporters run)
   bridged into `payload/site`. docs_hook regenerates skill pages when a
   `docs/` exists again. OPEN: restore source or accept bridged site.
6. **`_obfuscate` S4 marker break (by design, caught)**: Phase 1 made
   `plans/` part of the payload while the state-check's payload marker was
   "plans absent". Detected by reasoning before any red run; markers updated
   to `charts+plans+nexus.json` in Phase 4.
7. **Test-side error, not code**: first alias-import check used
   `crypto.candles` — a module that doesn't exist (candles lives under
   `charts/`). Re-test with `crypto.analysis` passed. No code change.
8. **`pack.py` bug 1**: `main()` passed `stage=None` into `verify()` after
   the staging tempdir had closed — caught by inspection immediately after
   writing, fixed before first run (zip/sign/verify moved inside the staging
   context).
9. **`pack.py` bug 2**: first full run crashed in P5 —
   `endsfirst`… `endswith(IGNORE_SUFFIXES)` with a `set`; fixed to tuple.
   Re-run fully green.
10. **`dist/pp` transient**: after the final ledger runs, a 119-file
    extraction of the zip appeared at `dist/pp` (4.5 MB), origin
    undetermined (pack.py demonstrably doesn't create it — controlled
    experiment: re-pack into `dist2` produced exactly 3 files and no `pp`).
    Removed. If it reappears, suspect an external tool touching `dist/`
    (minisign 0.12 temp behavior unverified). LOW priority.
11. **Note drift**: `note_stage3.md` listed the handoff commit as pending
    and carried nested-layout facts; both corrected during Phase 4 (§3/§4
    rewritten for the payload contract; superseded gotchas pruned).

## 7. File-by-file change inventory

**ainara framework**
- `framework/nexus_apps.py` (NEW, ~180 lines, stdlib-only):
  `read_manifest`, `resolve_app_payload` (dev-repo / installed / None),
  `register_bundle_namespace` (idempotent, first-wins importlib alias
  `payload/` → `ainara.nexus.<vendor>.<bundle>`; executes the bundle's
  `__init__.py`; creates the `ainara.nexus[.<vendor>]` namespace chain in
  memory; raises on failure). Stdlib-only so out-of-process tooling
  (docs_hook, generate_registries) can import it without Flask.
- `framework/config.py`: `get_nexus_base_paths()` — dev roots validated by
  `resolve_app_payload` (was: `<root>/ainara/nexus` dir check); installed
  roots likewise (was: `entry/ainara/nexus`); docstring rewritten (app
  roots; manifest-derived identity).
- `framework/capabilities/nexus.py`: `__init__` sys.path site-root
  injection DELETED (imports `sys`/`importlib` dropped with it);
  `discover()` probes app-shape per root first, then legacy vendor scan
  with the physical-bundle guard; per-bundle work extracted to
  `_load_bundle()` (first-wins dedup → `register_nexus_root` branch →
  namespace alias → `super().discover()` → vendor/UI tagging →
  `_collect_bundle_config_params`).
- `framework/pybridge.py`: `_iter_docs_sites` / `_resolve_docs_site`
  handle app-shaped roots (manifest identity; site under `payload/` or at
  top) in addition to the legacy vendor layout; traversal guard intact.

**ainara build**
- `scripts/_obfuscate.py`: `_resolve_ataria_source()` candidates via
  `resolve_app_payload` (`dev_apps` root, host mount root → `<root>/payload`);
  `plans` added to both copytree ignore patterns; error text updated.

**ainara ops**
- `scripts/nexus_state_check.sh`: `ATARIA_DEV` = mount; `-e` gitfile check;
  EXPECT anchors (ainara `0ef54636`, ataria/gitlink `64bd5a3`); payload
  markers; S6 paths.

**ataria**
- Layout: `payload/` (60 files: charts, crypto, dashboards, `_components`,
  `__init__.py`, nexus.json, plans ×2); root = dev material.
- `generate_registries.py`: argparse (`--ainara-root`/`--vendor`/`--bundle`,
  PROJECT_ROOT fallback); identity from manifest via `read_manifest`;
  `register_bundle_namespace` so full-path intra-bundle imports resolve;
  obsolete cwd-parent/`ainara-testing` identity recovery removed.
- `docs_hook.py`: `get_skills_files` now scans the resolved payload (was
  repo root — stale since `46d459b`); alias registered; PROJECT_ROOT block
  unchanged and ordered before the helper import.
- `_scripts/pack.py` (NEW, ~330 lines, stdlib-only): pipeline P0–P5 per §6
  of the resume note (see §8 for verification).
- `.gitignore` (NEW): bytecode, generated artifacts, `dist/`, `.pack-keys/`,
  mkdocs outputs.

## 8. Verification evidence (all runs, in order)

| Gate | Checks | Result |
|------|--------|--------|
| Single-copy probe (pre-adaptation) | `dev_apps` → mount: 8/8 + first-wins dedup line | PASS |
| State check (post-repoint) | 18 pass / 0 fail / 2 warn (artifact-missing warn expected on pristine mount) | GREEN |
| Gate 1 (restructure) | 0 files under `ainara/`; payload top-level exact; `plans/store/` intact; 100% rename detection; clean status | PASS |
| Gate 2 — resolve units | dev repo / installed bundle-at-top / non-app → identities / None | PASS |
| Gate 2 — alias | register idempotent (True/False); `crypto.analysis.__file__` under `payload/` | PASS |
| Gate 2 — discovery A | 8/8 exact frozen baseline, modules via alias | PASS |
| Gate 2 — discovery B | 0 skills, **0 "Importing module" lines**, guard message confirmed | PASS |
| Gate 2 — pybridge docs | no-crash + empty on fresh mount; fixture installed bundle discovered+resolved; `..` traversal rejected | PASS |
| Gate 3 — resolution | `_resolve_ataria_source` with and without dev_apps → `<mount>/payload` | PASS |
| Gate 3 — registries | 8 skills / 3 providers (frozen baseline); artifacts written into payload | PASS |
| Gate 3 — supporters run | `Artifacts ready`; leak-free (0 plans/_scripts/docs; 1 pre-existing fixtures README); PyArmor 9.2.7 header in shipped tree | PASS |
| State check (Phase 4) | 19 pass / 0 fail / 1 warn | GREEN |
| Stage 3b — pack run | P0 warning-with-flag; P2 143 entries; P3 1,032,002 bytes; P4 signature; P5 sha256+roundtrip+exact-set+re-lint+signature; exit 0 | PASS |
| Stage 3b — negative | no `--allow-placeholder` → ERROR + exit 1 | PASS |
| Stage 3b — re-run into `dist2` | 3 files exactly; `dist/pp` not reproduced | PASS |
| Final state check | 19 pass / 0 fail / 1 warn (creatorId only) | GREEN |

## 9. Artifact register

- `ataria/dist/ataria-0.1.0.zip` — 1,032,002 bytes,
  sha256 `4493a3d148972358263c488cad218cb0bbd811989e3df0a3e871b467046d2d80`,
  119 files, top-level: `__init__.py _components charts crypto dashboards
  nexus.json plans providers_registry.json site skills_metadata.json`.
  Augmented manifest: `requiresPolaris: ">=0.11.0"`, `plans:
  ["plans/sentinel_guardian.yaml", "plans/sentinel_trading.yaml"]`.
- `ataria/dist/ataria-0.1.0.zip.minisig` + `.sha256` — signed with the
  THROWAWAY test keypair `.pack-keys/ataria-test.{key,pub}` (unencrypted;
  gitignored). **Test public key** (safe to record):
  `RWTad3jP4FCQu2ggpaxmWVR+VtipBIcS+/fy3/MWPMt+DDCQZ3/OfJuM`. The secret
  key is deliberately NOT recorded here. Artifacts signed with this key are
  dev/test only and must never be distributed.
- NOTE: the zip is not yet byte-reproducible (zipfile preserves mtimes) —
  re-packing yields a different sha256. If reproducible builds matter later,
  set fixed timestamps (SOURCE_DATE_EPOCH-style) in `make_zip`. Deferred.

## 10. Residual risks & open items

1. **Frozen-mode namespace aliasing is the one path not exercised** (dev
   harnesses only). Frozen output placement is unchanged, but the aliasing
   replaces physical resolution — verify with the optional
   `POLARIS_TARGET=pybridge` frozen build before Stage 4 wiring.
2. **creatorId placeholder** — real Solana pubkey pending; pack with
   `--allow-placeholder` until then.
3. **Docs source** (`docs/`) lost; site bridged. Restore or accept.
4. **`dist/pp` transient** — one-time, unreproduced (§6.10). Monitor.
5. `pack.py` P1 untested end-to-end (blocked by item 3); `generate_registries`
   inside P1 is the same code path proven in Gate 3.
6. Deferred hygiene (unchanged from note §7): skills.py `load_errors`
   instantiation-failure gap; dead `register_nexus_root` branch; 6 crypto
   skills without UI components; vendor-layout primary root retirement in
   Stage 4.

## 11. Process assessment

- The "never commit on a failed gate" rule held: every commit followed a
  green gate; two intra-edit slips (§6.2, §4-of-note premature S6 paths)
  were caught before any run consumed them, and both were reverted rather
  than pushed through.
- INSPECT-before-APPLY caught three design-level surprises that would have
  shipped broken: pybridge's docs functions sharing the roots API, the
  stale `docs_hook.py` scan root, and the `_obfuscate` plans-marker
  contradiction.
- The single biggest lesson of the session: when the user challenged the
  allowlist proposal, the resulting `payload/` design eliminated an entire
  class of rules (no allowlist, no underscore convention, no `_components`
  exception). The simplest boundary won because it was structural.

## 12. Re-verification commands

```bash
cd /home/ruben/lab/src/ainara
bash scripts/nexus_state_check.sh            # expect: 19/0/1 GREEN

# Discovery via payload alias (8/8) — side effects: keyring/API-key reads
AINARA_CONFIG=<(cat ~/.config/ainara/ainara.yaml; printf '\nnexus:\n  dev_apps:\n    ataria: %s\n' "$PWD/ainara/nexus/khromalabs/ataria") \
  ./venv/bin/python -c "
from ainara.framework.capabilities.nexus import NexusSkillProvider
from ainara.framework.config import config
p = NexusSkillProvider(nexus_path='', config=config, mcp_client_manager=None)
print(sorted(p.discover()))"

# Obfuscate resolution (payload, never repo root)
./venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts'); import _obfuscate
print(_obfuscate._resolve_ataria_source())"

# Full pack + verify (dev/test; placeholder creatorId)
cd ainara/nexus/khromalabs/ataria
../venv/bin/python _scripts/pack.py --polaris-version 0.11.0 --no-generate \
  --allow-placeholder --sign .pack-keys/ataria-test.key && echo PACK-GREEN

# Signature check against the recorded test pubkey
minisign -Vm dist/ataria-0.1.0.zip \
  -P RWTad3jP4FCQu2ggpaxmWVR+VtipBIcS+/fy3/MWPMt+DDCQZ3/OfJuM
```

## USER APPENDIX

Reorganized a bit the ataria submodule: `plans/store` is now `drafts/plans`,
moved some scripts in root to `scripts/` as well, updated `pack.py` to use the new path,
new `notes/` subdir and moved notes there. New structure (only modified files,
didn't touch `payload/`):
.
./scripts
./scripts/sentinel_entry_analyst_sketch.py
./scripts/pack.py
./scripts/sentinel_analysis.py
./scripts/docs_hook.py
./scripts/generate_registries.py
./scripts/mkdocs.yml
./scripts/generate_docs.sh
./notes
./notes/pyarmor_integration_summary.md
./notes/REFACTORING_NOTES.md
./drafts
./drafts/plans
./drafts/plans/sentinel_trading_restricted.yaml
./drafts/plans/sentinel_trading_template.yaml
./drafts/plans/sentinel_trading_asset.yaml
