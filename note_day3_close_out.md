# RESUME NOTE — Nexus Apps decoupling (Day 3 close-out)

**Supersedes** `note.md`, `note_day2_session2.md` and all scratch `script*.sh`.
This is the single source of truth for resuming. Where older notes conflict with
this one, THIS file wins.

**How to resume:** add the files in §9 to the chat, answer/confirm the open
decisions in §6, then execute §8 top to bottom. Never batch stages —
apply → verify → proceed.

---

## 1. TL;DR — where we are

- **Stages 1, 2.1–2.5 COMPLETE and verified.** All committed in the ainara repo
  (HEAD `3464a841` on branch `dev012`).
- **Ataria repo restructured** to the Nexus app payload layout
  (`ainara/nexus/khromalabs/ataria/`), committed (`46d459b`), payload hygiene done.
- **Full frozen server build succeeded after the restructure** (obfuscate →
  PyInstaller → bundle), and the frozen pybridge smoke test confirmed 2.5:
  `curl /docs/list` → `[{"application":"ataria","publisher":"khromalabs"}]`.
- **Dev symlink is LOCAL-ONLY (untracked)** at `ainara/nexus/khromalabs/ataria`
  → `/home/ruben/lab/src/ataria/ainara/nexus/khromalabs/ataria`. Recreate per
  machine: `ln -sfn <ataria>/ainara/nexus/khromalabs/ataria ainara/nexus/khromalabs/ataria`
  (hidden by `.gitignore`'s `ainara/nexus/*`; alternatively use `nexus.dev_apps`).
- **NEXT: Stage 3 — per-app packaging in the ataria repo.** Design agreed at
  high level; open decisions D-A…D-F in §6 must be answered first.
- The host repo keeps the symlink until "not necessary at all" (user decision Q1).
  WARNING: with the symlink present, host builds work; without any ataria
  materialization, `_obfuscate.py`/`servers.spec` refuse to build (by design
  until Stage 4 removes ataria from host builds).

## 2. Commit ledger

### ainara repo (branch dev012; base master = 4d0d713d)
| Commit | Subject |
|---|---|
| `9ea0e9f3` | Stage 1 — `__version__` → `ainara.framework`, PEP 420 namespaces |
| `fbf68753` | Stage 2.1+2.2 — `get_nexus_base_paths()` (dev > installed > primary) + provider multi-root sys.path prepending |
| `1a2de1ad` | Stage 2.3 — multi-root `discover()`, first-wins `seen_bundles`, `all_caps` accumulation fix |
| `194bb431` | docs: day-2 session-2 handoff note (superseded by THIS file) |
| `41b78c53` | re-point ataria dev symlink at restructured payload |
| `6a549666` | retire ataria dev symlink (kept in history as record; superseded by local-only link) |
| `a6349682` | docs: 2.4 resolution (dev_apps, plans placement, symlink facts) |
| `1beabb7a` | docs: 2.4 final wrap-up (local-only symlink, plans design input, payload hygiene) |
| `3464a841` | Stage 2.5 — pybridge multi-root docs (`_iter_docs_sites`/`_resolve_docs_site`) |

### ataria repo (branch master)
| Commit | Subject |
|---|---|
| `46d459b` | refactor: adopt Nexus app payload layout (`ainara/nexus/khromalabs/ataria/`) |

## 3. Verified facts (observed, not assumed — do not re-derive)

- **Frozen baseline (8 sorted nexus skill IDs) — compare future runs to THIS list:**
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
- **2.3 verified A/B/C** (8 → 9 → 8) with the §5c-style fixture in
  `<data.directory>/nexus/.apps/testapp` — including `execute()` of
  `testlab_demoapp_hello_world`.
- **2.4 verified in both modes:** (A) `nexus.dev_apps: {ataria: /home/ruben/lab/src/ataria}`
  → dev root FIRST in precedence log, first-wins skip line on the primary scan,
  `file_path` from the ataria repo; (B) symlink-only → same 8 IDs via the
  primary root. Sorted-list equality with the frozen baseline in all runs.
- **2.5 verified** (helper-level harness, 3-root coexistence with a testapp
  site fixture: dedupe, dev-root ownership, traversal guard, teardown) **plus
  HTTP smoke on a frozen build** (`/docs/list`, `/docs/khromalabs/ataria/`).
  Ownership semantics: strict first-wins on (publisher, application) DIRECTORY
  presence — owning root without `site/` yields absent/404, no fallback (D1, agreed).
- **Namespace mechanics proven:** `ainara.__path__` is a dynamic `_NamespacePath`;
  provider-constructor `sys.path` insertion retroactively extends already-imported
  namespace levels. Works in dev AND frozen (`_MEIPASS`) modes.
- **Full pipeline works post-restructure:** `_obfuscate.py` dereferences the
  symlink via `realpath` into `build/ataria_compiled`; bundle `__init__.py`
  survives `_strip_namespace_inits()`; frozen import chain intact.

## 4. Key discoveries / gotchas (do not re-derive these)

1. **`Skill` is an ABC with abstract property `matcher_info`** — every nexus
   skill (and any test fixture) MUST implement it or instantiation fails
   (logged, skill silently skipped). This broke the original §5c fixture.
2. **skills.py observability gap (deferred):** skill *instantiation* failures
   are logged but NOT appended to `load_errors` (only import failures are).
3. **Bureau loads Conductor plans ONLY from `<config_dir>/bureau/`**
   (`bureau/server.py`: `get_default_config_paths()[0].parent / "bureau"`) —
   never from nexus bundles. Ataria `plans/*.yaml` = dev source templates →
   stay at the ataria repo ROOT (outside the payload).
4. **`.gitignore` never affects tracked files.** The old dev symlink was TRACKED
   (mode `120000`, likely `git add -f`) — that's why re-point commit 41b78c53
   worked without `-f`. Retirement is in history (6a549666); today's link is
   untracked/local-only (user decision).
5. **PyArmor 9 with a REGULAR package input is the safe path** (bundle-level
   `__init__.py` exists in the payload). The namespace-input uncertainty from
   Day 1 is moot for Stage 3.
6. **Payload hygiene matters for builds:** `_obfuscate.py` copytrees EVERYTHING
   physically present in the payload. `build/`, `dist/`, `__pycache__/` were
   removed; `__pycache__` regenerates on every dev import → run verification
   harnesses with `PYTHONDONTWRITEBYTECODE=1`; Stage 3 packaging allowlist is
   the permanent fix.
7. **`skills_metadata.json`, `providers_registry.json`, `site/` are gitignored
   GENERATED artifacts** (physically present, checked in guards). A fresh
   ataria clone lacks them → Stage 3 pack script must run the generators
   (their output paths still assume the old bundle-at-root layout — follow-up
   needed, non-blocking).
8. **`docs/` = mkdocs SOURCE** (not generated); moved to the ataria repo root.
9. **Verification harness patterns that work:**
   - Config-derived paths: `APPS_ROOT="$(python -c "from ainara.framework.config import config; from pathlib import Path;
print(Path(config.get_exact('data.directory')) / 'nexus' / '.apps')")"`; assert absolute + outside repo.
   - For dev_apps tests, COPY the real config to a temp file, append
     `nexus:\n  dev_apps:\n    ataria: /home/ruben/lab/src/ataria`, run with
     `AINARA_CONFIG=<tmp>` (never edit the real config; saves would strip comments).
   - `create_app()` is far too heavy for harnesses — import module-level
     helpers (`_iter_docs_sites`, `_resolve_docs_site`) directly.
   - Compare SORTED ID lists + counts, never log order.
10. **Strict-count patch guards saved us repeatedly** (abort when expected
    old-block count ≠ 1). Also: verify whether a script already ran before
    re-running (three "already applied" events this session; reflog is your friend).

## 5. Working rules (carried — these prevented repeat crashes)

- Never batch stages; apply → verify → proceed.
- Verification = sorted lists + counts; fixture teardown mandatory (lives
  outside the repo).
- Pre-written note text is not verification — runs must actually execute.
- Ask for file contents before drafting edits — true file state beats summaries
  (re-read files already in chat before writing patches against them).
- Identifier spelling checked line-by-line; grep broadly and cross-tree.
- Confirm deletions/state with `git status --short` + `git ls-files -s`, never assume.
- User-level compiled app: no pip / no interpreter / no CLI assumptions, ever.
- Script re-runs must be idempotent or guarded; check `git reflog` when state
  looks impossible.

## 6. Stage 3 — per-app packaging (NEXT) — design + OPEN DECISIONS

Goal: the ataria repo gains a standalone pack script producing a signed,
user-level-installable app bundle. No host-repo dependency.

Agreed pipeline:
1. **Preflight/generators:** run `generate_registries.py` (regenerates the two
   gitignored JSONs), build docs (`site/`), verify payload contains ONLY the
   shippable set (`ainara/`, manifest, `pyarmor_runtime_*/` if obfuscated).
2. **Optional PyArmor** (pin ONE version; regular-package input — safe).
3. **Assemble** per containment allowlist: top level only `ainara/`,
   `manifest.json`, `pyarmor_runtime_*/`.
4. **manifest.json v1** (flat): `schemaVersion, name, provider, version,
   description, requiresPolaris` range, optional `entryPoint`, `ui.components`,
   soft `permissions`, **`plans: [...]`** (template plans; installer seeds
   `<config_dir>/bureau/` on FIRST install only, never overwrites user edits).
5. **Signing:** artifact + detached minisign signature.
6. Stage 4 (host installer) consumes: verify → extract `<id>.new/` → atomic
   swap → record.

OPEN DECISIONS (answer before drafting the pack script):
- **D-A transport:** wheel as transport (never pip-installed) vs plain signed
  zip. *Recommendation: wheel as transport per note.md §6-2 lean.*
- **D-B signing:** is `minisign` available on the build machine (`which minisign`)?
  Where is the PUBLIC key pinned for Stage 4 verification (Polaris bundle /
  installer / config)?
- **D-C versioning:** where does the app version live (inside `nexus.json`? new
  field?) and what determines `requiresPolaris` (Polaris `package.json` version
  at build time?).
- **D-D obfuscation:** include PyArmor in iteration 1, or ship plain first and
  add once the pipeline is green? *Recommendation: plain first, add second.*
- **D-E integrity:** signature over the whole artifact (recommended) vs
  per-file hashes in the manifest.
- **D-F pack script home:** `_scripts/pack.py` at the ataria repo root, fully
  standalone. *Recommendation: yes.*

## 7. Deferred small items (not Stage 3 blockers)

- skills.py: append skill *instantiation* failures to `load_errors` (one-liner;
  improves future debugging).
- Ataria `generate_docs.sh` / `generate_registries.py` output paths still assume
  bundle-at-root layout (fold into Stage 3 pack preflight — generators must run
  before packaging anyway).
- Host build-time dev_apps story: decide how host builds materialize ataria
  WITHOUT the dev symlink (needed at Stage 4 when edition machinery is dropped;
  options: build-time `nexus.dev_apps` env, temporary link, or pack-first flow
  where the host consumes signed bundles only).
- After Stage 4: remove host `ainara/nexus` dev tree entirely; cleanup items:
  mkdir fallback in `NexusSkillProvider.__init__`;
  `get_nexus_base_paths()` always appending the primary root (harmless when
  missing — `is_dir()` guard proven).
- Old notes cleanup: delete `note.md`, `note_day2_session2.md`, scratch
  `script*.sh` once this file is committed.

## 8. Resume checklist (in order)

1. Add files from §9 to the chat; confirm state:
   `git -C ainara log --oneline -10`, `git -C ataria log --oneline -3`,
   `ls -la ainara/nexus/khromalabs/` (symlink present?), payload `ls`.
2. Answer D-A…D-F (§6).
3. Draft Stage 3 pack script schema → review → implement → verify
   (pack → inspect bundle tree against allowlist → manifest lint →
   signature verify round-trip).
4. Only after Stage 3 is green: Stage 4 (installer + host build cleanup) and
   Stage 5 (Polaris UI install flow; auth/perks UI; Lit protocol — deferred).

## 9. Files to add to the chat at next session

1. THIS note.
2. `ataria/nexus.json`, `ataria/generate_registries.py`, `ataria/generate_docs.sh`, `ataria/mkdocs.yml`
3. Polaris `package.json` (for D-C `requiresPolaris`).
4. `ainara/framework/capabilities/skills.py` (if touching load_errors) and
   `scripts/_obfuscate.py` + `scripts/pyinstaller/servers.spec` (Stage 4 prep;
   read-only initially).
5. Output of `which minisign` (D-B).

## 10. Stage 4/5 locked decisions (from prior notes, still valid)

- One edition end-state: remove `-e`/`POLARIS_EDITION`/`.edition` marker/
  supporters branches/ataria materialization from `_build.py`, `_obfuscate.py`,
  `servers.spec`; host ships no nexus app code.
- Installer: verify → extract `<id>.new/` → atomic swap → record; startup
  re-check of `schemaVersion`/`requiresPolaris`.
- Template plans in Nexus bundles: manifest `plans: [...]`; seed
  `<config_dir>/bureau/` first-install only; host `resources/examples` keeps
  host-native examples only; ataria keeps canonical plan sources (production
  config-dir symlink = stopgap).
- Wheel = at most an internal transport; never pip-installed; no interpreter
  requirements at user level.
- `AuthManager` degrades to public mode without `supporters.auth_core`.

---

## 11. Addendum — ataria materialized as a git submodule (supersedes §1 symlink facts)

- Host pins ataria via `.gitmodules` + gitlink @ `46d459b` (absorbed gitdir,
  URL `khromalabs:ataria.git` verified reachable). Materialization is now
  tracked and reproducible: `git submodule update --init`.
- **P1 role split (harness-verified):** submodule mount = pinned reference +
  chat transport; runtime truth = `nexus.dev_apps`. A (dev_apps set): 8/8
  exact frozen-baseline IDs + first-wins skip on the mount. B (unset): 0
  skills — footgun: mount present without dev_apps silently yields nothing
  (extends §7 observability: warn on 0-skill bundles).
- The mount exposes the repo ROOT, not the payload — depth-2 glob sees only
  `_scripts/*.py`. Builds must never copytree the mount root unfiltered.
- New gotchas: (a) harnesses MUST use the project venv interpreter — bare
  `python` (3.14) lacks bundle deps and fakes import failures; (b) discovery
  INSTANTIATES skills — real side effects (keyring, API keys, caches);
  (c) `check-ignore` consults the index by default — use `--no-index` on
  tracked paths (reconciles §4/#4).
- Q3: `plans/store/` = archived, excluded; only top-level `plans/*.yaml` pack.
- Q5: artifact root == bundle root; manifest stays `nexus.json` (§6.4
  `manifest.json` amended) — `platform_utils` traversal expects that name.
- Next: `_obfuscate.py` bundle-source resolution, then Stage 3 pack script.
