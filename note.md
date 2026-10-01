# RESUME NOTE — Nexus Apps decoupling, Day 2

**Supersedes** `nexus_apps_decoupling.md` where the two conflict (especially its
"special editions" framing). That note's §2 design decisions (extraction model,
manifest v1, detached minisign, containment allowlist, PyArmor pinning, data dir)
remain valid and are reused below.

## 1. Corrected end-state (decided end of Day 1 — authoritative)

- **One edition.** The public/supporters edition split is **removed, not adapted**.
  No `-e` flag, no `POLARIS_EDITION`, no `.edition` marker, no `supporters/` build
  branches in `_build.py` / `_obfuscate.py` / `servers.spec`.
- **Host ships zero Nexus App code.** Ataria is an independent package in its own
  git repo (`/home/ruben/lab/src/ataria`, sibling of the ainara repo).
- **Servers:** Orakle serves skills; Pybridge exposes framework REST to the
  Electron UI and contains **no skills**. Bureau = agents orchestration.
- **Dev mode without symlink:** the source repo of a Nexus App should be
  configurable (config key or dev.json), not a symlink inside `ainara/nexus`.
- **Distribution (rough, not fully designed):** signed bundle, user-level install —
  the compiled app must never require pip, a Python interpreter, or CLI knowledge.
  Wheels are at most an internal transport format. Lit protocol: later, out of scope.
- **Per-app packaging:** obfuscation/packing of Nexus Apps moves to each app's own
  repo (its own script). The host repo stops obfuscating `ainara/nexus` entirely.
- **Scope for now: server-side only.** Polaris UI install flow and
  auth/supporters UI: deferred.

## 2. Done (Day 1) — Stage 1 applied, build-validated, commit pending

All verified working; frozen pybridge `/health` returned `"version":"0.11.0"`:

- **1.1** `ainara/framework/__init__.py` created (license header + `__version__ = "0.11.0"`, `__version_info__`).
- **1.2** `pybridge.py:40` → `from ainara.framework import __version__`.
- **1.2b** `ainara/orakle/__init__.py` → `from ..framework import __version__, __version_info__`.
- **1.2c** `scripts/build:91` → `python -c "from ainara.framework import __version__; print(__version__)"`.
- **1.3** `pyproject.toml`: `attr = "ainara.framework.__version__"`; `packages.find` → `include = ["ainara*"]`, `namespaces = true`.
- **1.4/1.5** Deleted `ainara/__init__.py`, `ainara/nexus/__init__.py`,
  `ainara/nexus/khromalabs/__init__.py`. Bundle-level inits kept.
- **1.6** `servers.spec`: dropped `ainara/__init__.py` from `common_datas`.
- **1.7** `_obfuscate.py`: `_strip_namespace_inits()` after staging copytree
  (proven useful: it caught the then-missing 1.5 deletion). Plus two patches:
  PyArmor output-shape normalization (wrapped vs flat) and supporters empty-tree guard.

`git status --short` at pause (interpretation: `RM ainara/nexus/__init__.py ->
ainara/framework/__init__.py` is just git's rename detection pairing a deletion
with the new file — functionally D+A, nothing to fix):

```
D  ainara/__init__.py
RM ainara/nexus/__init__.py -> ainara/framework/__init__.py
 M ainara/framework/pybridge.py
D  ainara/nexus/khromalabs/__init__.py
 M ainara/orakle/__init__.py
A  nexus_apps_decoupling.md
 M pyproject.toml
 M scripts/_obfuscate.py
 M scripts/build
 M scripts/pyinstaller/servers.spec
```

**First action tomorrow: run §3, then `git add -A && git commit -m "refactor: move __version__ to ainara.framework and convert ainara/nexus to PEP 420 namespace packages (Stage 1)"`.**

## 3. Morning validation script (run from repo root before anything else)

```bash
#!/usr/bin/env bash
set -u; fail=0
ok(){ echo "PASS: $1"; }
bad(){ echo "FAIL: $1"; fail=1; }

echo "=== git state ==="; git status --short

# 1.4/1.5 namespace rule
[ ! -e ainara/__init__.py ]                      && ok "ainara/__init__.py gone"       || bad "ainara/__init__.py exists"
[ ! -e ainara/nexus/__init__.py ]                && ok "nexus/__init__.py gone"        || bad "nexus/__init__.py exists"
[ ! -e ainara/nexus/khromalabs/__init__.py ]     && ok "khromalabs/__init__.py gone"   || bad "khromalabs/__init__.py exists"
[ -f ainara/nexus/khromalabs/ataria/__init__.py ]&& ok "bundle init kept"              || bad "bundle init missing"

# 1.1–1.3 version single-sourcing
python -c "from ainara.framework import __version__, __version_info__; assert __version__=='0.11.0'" \
  && ok "framework version" || bad "framework version"
python -c "import ainara; assert not hasattr(ainara,'__version__') and getattr(ainara,'__file__',None) is None" \
  && ok "ainara is a namespace" || bad "ainara not namespace"
grep -rnE "from ainara import|ainara\.__version__" --include="*.py" . | grep -q . \
  && bad "old version consumers remain" || ok "no old version consumers"
grep -q "from ainara.framework import __version__" scripts/build \
  && ok "scripts/build fixed" || bad "scripts/build line 91 not fixed"
grep -q 'attr = "ainara.framework.__version__"' pyproject.toml \
  && ok "pyproject attr" || bad "pyproject attr"
grep -q 'namespaces = true' pyproject.toml && ok "pyproject namespaces" || bad "pyproject namespaces"

# 1.7 patches present
grep -q "Normalize both shapes" scripts/_obfuscate.py && ok "pyarmor shape patch" || bad "shape patch missing"
grep -q "shipped 0 obfuscated scripts" scripts/_obfuscate.py && ok "empty-tree guard" || bad "guard missing"

# Namespace import chain (dev symlink still in tree)
python - <<'EOF' && echo "PASS: ataria chain" || echo "FAIL: ataria chain"
import pkgutil, ainara.nexus.khromalabs.ataria as a
assert a.__file__, a.__file__
print("ataria modules:", sorted(m.name for m in pkgutil.iter_modules(a.__path__)))
EOF

[ $fail -eq 0 ] && echo "ALL PASS — commit Stage 1" || echo "FAILURES — do not commit, report output"
exit $fail
```

Still pending from Day 1 (not blockers for the commit):
- **User-skill load on Orakle** (belongs to Orakle, not Pybridge — Day-1 correction):
  `grep -rn "class Khromalabs" /home/ruben/lab/src/ataria/ainara/nexus/khromalabs/ataria/crypto --include="*.py" | head`,
  then import that class directly.
- Optional PyInstaller rebuild only if `_obfuscate.py`/spec are touched again.

## 4. Key discoveries (do not re-derive these)

1. **Public edition deletes ataria from the staged tree** (`if not supporters:` block
   in `_obfuscate.py`) before PyArmor runs. The Day-1 "PyArmor output not found"
   crash was the old wrapped-layout check meeting an intentionally-empty input —
   not a PyArmor bug. The successful public build ships an *empty* obfuscated nexus
   tree, which was correct old-edition semantics.
2. **PyArmor 9.2.7 with a namespace-package input containing real code: NEVER
   tested.** Regular package input mirrors its basename under `-O`
   (`<O>/nexus/…`); namespace input writes contents at the `-O` root (hypothesis,
   seen only with an empty input). **Likely moot**: in the corrected end-state each
   app obfuscates itself in its own repo, where bundle level **has** `__init__.py`
   → PyArmor always sees a regular package. Test kept only for reference:
   stage any vendor/bundle tree without the nexus-root init, run
   `pyarmor gen --recursive --obf-code 2 --mix-str ... -O build/ns_test_obf build/ns_test_stage/nexus`, inspect.
3. **PEP 420 inside `_MEIPASS` works** — frozen pybridge imports `ainara.framework`
   (namespace `ainara`) and reports version 0.11.0 on `/health`. The risky §7-1(e)
   mechanism is proven.
4. `_strip_namespace_inits()` worked as designed (caught a stale `__init__.py`).
   Its fate depends on `_obfuscate.py`'s final role (Stage 4 cleanup).
5. Build-log confusion lesson: PyArmor INFO goes to unbuffered stderr, `[_obfuscate]`
   prints to buffered stdout → log order lies. Don't infer execution order from it.
6. `AuthManager` (`ainara/framework/auth.py`) degrades gracefully to public mode
   when `supporters.auth_core` is absent — so supporters removal can leave auth.py
   untouched initially; it just goes dormant.
7. `pybridge /docs/list` and `serve_docs` read `config.get_nexus_base_path()` —
   single-root; must become multi-root in Stage 2.

## 5. Revised roadmap (supersedes old §3)

1. **✅ Stage 1 — namespace conversion + version single-sourcing** (this commit).
2. **Stage 2 — multi-root runtime + config-driven dev apps (2.1–2.3 ✅; NEXT: ataria restructure, then 2.4):**
   - 2.1 `config.py`: `get_nexus_base_paths() -> List[Path]` — dev > installed > primary
     (keep `get_nexus_base_path()`), then each installed app's
     `<data_dir>/nexus/.apps/<app_id>/ainara/nexus` portion; skip `.`/`_`-prefixed
     and `cache`; needs `List` import.
   - 2.2 `capabilities/nexus.py` `__init__`: `self.nexus_paths = config.get_nexus_base_paths()`
     (accept old ctor arg but unused); mkdir fallback only for primary root when not
     frozen; **prepend app site-roots to `sys.path`** (guard `path.parent.name == "ainara"`,
     reverse order so primary ends up first, dedupe) — before any `discover()`.
   - 2.3 ✅ `discover()` now scans every root from `get_nexus_base_paths()`
     (dev > installed > primary) instead of only the primary alias, with
     per-root `is_dir()`/`OSError` guards and `sorted()` scan order. Fixes the
     latent accumulation bug: `BasePythonSkillProvider.discover()` resets
     `self.capabilities` on every call, so the old update-into-self pattern
     kept only the last-scanned bundle; skills now accumulate into a local
     `all_caps` dict. `seen_bundles` gives `(vendor, bundle)` first-wins
     semantics across roots (a bundle yielding zero skills in a higher root
     does not fall back). register-nexus-root local `root` renamed to
     `root_name` to avoid shadowing the loop variable. Verified A/B/C: 8 → 9
     → 8 skills with the `testlab/demoapp` fixture (see §5c).
   - 2.4 **Dev mode via config, replacing the symlink**: e.g. config key
     `nexus.dev_apps` mapping app-id → source repo path, surfaced as extra roots
     (mechanism shared with 2.1). **OPEN:** config.yaml entry vs `.apps/dev.json`
     as the original note proposed — decide; lean config.yaml (ConfigManager
     already handles user config). (RESOLVED 2.4: verified with nexus.dev_apps; symlink retired)
   - 2.5 `pybridge /docs/list` + `serve_docs`: iterate all roots.
   - Unchanged: `manager.py`, `serve_component`, `skills.py`.
   - Verify: empty `.apps/` → identical skill counts; test app
     `.apps/testapp/ainara/nexus/testlab/demoapp/` (fresh vendor) → both load;
     Orakle user-skill import still works with dev root from config.
3. **Stage 3 — per-app packaging (ataria repo, new script):** stage → optional
   PyArmor (regular package: bundle has `__init__.py` — pin ONE PyArmor version
   across all builds) → wheel/bundle + `manifest.json` v1 (flat:
   `schemaVersion, name, provider, version, description, requiresPolaris` range,
   optional `entryPoint`, `ui.components`, soft `permissions`) + detached minisign
   signature. Containment allowlist: top level only `ainara/`, `manifest.json`,
   `pyarmor_runtime_*/`.
4. **Stage 4 — host build cleanup:** server-side installer (verify → extract
   `<id>.new/` → atomic swap → record; startup re-check of `schemaVersion`/
   `requiresPolaris`); then drop edition machinery (`-e`, `POLARIS_EDITION`,
   `.edition` marker, supporters branches, ataria materialization, the symlink)
   from `_build.py`, `_obfuscate.py`, `servers.spec`; host ships no nexus app code.
5. **Stage 5 (deferred):** Polaris UI install flow; auth/perks UI; Lit protocol.

## 5b. Day-2 decisions (locked)

- **Precedence is dev > installed > primary everywhere.** This supersedes
  §5-2.2's "reverse order so primary ends up first" wording; the runtime
  prepends site-roots in reverse of `nexus_paths` so the *first* entry
  (dev) ends up at `sys.path[0]`.
- **`nexus.dev_apps` value = repo root containing the `ainara/nexus`
  portion** (not the `ainara/nexus` dir itself). The runtime appends
  `/ainara/nexus` internally.
- **Ataria repo restructure to that layout is required before 2.4.**
  `_scripts/` stays at the repo root, outside the payload (Q3 option 1).
- **§3 validation script had a buggy assert** (`hasattr(ainara,'__file__')`
  is a false negative on Python ≥3.9); fixed in §3 above.

## 5c. Stage 2.3 fixture (re-creatable artifact for 2.5 `/docs/list` work)

Installed-app fixture under the platform data dir; portable to the Windows
`Saved Games` layout via `config.get_exact('data.directory')`:

```bash
APPS_ROOT="$(python -c "from ainara.framework.config import config; from pathlib import Path; print(Path(config.get_exact('data.directory')) / 'nexus' / '.apps')")"
mkdir -p "$APPS_ROOT/testapp/ainara/nexus/testlab/demoapp/hello"
printf '"""testlab demoapp - Stage 2.3 multi-root verification fixture."""\n' \
  > "$APPS_ROOT/testapp/ainara/nexus/testlab/demoapp/__init__.py"
cat > "$APPS_ROOT/testapp/ainara/nexus/testlab/demoapp/hello/world.py" <<'EOF'
"""Demo skill for Stage 2.3: proves skills accumulate across Nexus roots."""

from ainara.framework.skill import Skill


class TestlabDemoappHelloWorld(Skill):
    """Say hello from a second (installed-app) Nexus root."""

    @property
    def matcher_info(self) -> str:
        return "Say hello from the testlab demoapp fixture."

    def run(self) -> dict:
        return {"greeting": "hello from testlab/demoapp"}
EOF
```

Layout: `hello/` needs no `__init__.py` (PEP 420 portion); the bundle-level
`__init__.py` is included because that's the canonical bundle layout (Stage-1
validation asserts it for ataria, and Stage 3's PyArmor story depends on it).
Class name is dictated by discovery: `Testlab` + `Demoapp` + `Hello` + `World`
→ skill id `testlab_demoapp_hello_world`.

Teardown (mandatory — the fixture lives outside the repo and would silently
change every future baseline if left in place):

```bash
rm -rf "$APPS_ROOT/testapp"
```

## 6. Open questions to settle early in Day 2

1. Dev-app mapping location: **RESOLVED — config.yaml (`nexus.dev_apps`)** (2.4 verified).
2. Bundle format: wheel (rich metadata, extraction is stdlib-simple) vs plain
   signed zip — recommend wheel as transport, never pip-installed.
3. Does the host keep an `ainara/nexus` dir at all after Stage 2 (empty namespace
   root for merging, or does `sys.path` prepending make it unnecessary)?
4. Keep or delete the in-tree symlink `ainara/nexus/khromalabs/ataria -> ../../ataria`
   once config-driven dev roots work (retired after 2.4 verification — see §9).

## 7. Files to add to the chat at session start

1. `ainara/framework/config.py` (at least imports + `get_nexus_base_path` region)
2. `ainara/framework/capabilities/nexus.py` (full)
3. `scripts/_obfuscate.py`, `scripts/_build.py`, `scripts/build`, `scripts/pyinstaller/servers.spec`
4. `pyproject.toml`
5. `pybridge/server.py` + `auth.py` (reference for Stage 4; clarify if
   `pybridge/server.py` is distinct from `ainara/framework/pybridge.py`)
6. This note.

## 8. Working rules (carried over — these prevented repeat crashes)

- Never batch stages; apply → verify → proceed.
- Identifier spelling checked line-by-line (`nexus_path`/`nexus_paths` was the
  crash cause); grep **broadly** (`__version`, not just one import pattern), and
  grep cross-tree (scripts/, polaris/, specs), not just `*.py` in the package.
- Confirm deletions with `git status --short`, never assume.
- Ask for file contents before drafting edits (true file state beats summaries).
- User-level compiled app: no pip / no interpreter / no CLI assumptions, ever.

## 9. Day-3 addenda (Stage 2.4 session)

- **plans/ placement RESOLVED:** Bureau loads Conductor plans from
  `<config_dir>/bureau/` (bureau/server.py: `get_default_config_paths()[0].parent / "bureau"`),
  never from nexus bundles → ataria `plans/` are dev source templates; stays at repo root.
- **Dev symlink was TRACKED** (mode 120000); `.gitignore`'s `ainara/nexus/*` only
  affects untracked paths. Retirement = normal tracked deletion (this commit).
- **Payload stray artifacts (deferred):** `build/`, `dist/`, `docs/`, `__pycache__/`
  sit inside `ainara/nexus/khromalabs/ataria` (all gitignored). Pre-existing;
  `_obfuscate` copytree bundles them. Clean before Stage 3 packaging; its
  containment allowlist is the permanent fix. `docs/` nature (generated vs mkdocs
  source) still to classify.
- **skills.py observability gap (deferred):** skill *instantiation* failures are
  logged but not appended to `load_errors` (only import failures are) — hid the
  2.3 fixture bug.
- **2.4 verification:** with `nexus.dev_apps: {ataria: <repo>}` — dev root FIRST in
  precedence log, first-wins skip logged on the primary scan, 8 IDs == frozen
  baseline, file_path served from the ataria repo; after symlink retirement:
  same 8 IDs from the dev root alone.
- **2.4 wrap-up (Day 3, final):** Q1 decision — dev symlink kept LOCAL-ONLY
  (untracked, hidden by `ainara/nexus/*`). Facts recorded: gitignore never
  affects tracked files — the old link WAS tracked (mode 120000, almost
  certainly `git add -f`), which is why re-point commit 41b78c53 worked
  without -f. Retirement commit 6a549666 stands as the shared-history record;
  each dev machine recreates the link locally (`ln -sfn
  <ataria>/ainara/nexus/khromalabs/ataria ainara/nexus/khromalabs/ataria`)
  or uses `nexus.dev_apps`. Both modes re-verified: dev_apps coexistence
  (dev root first, first-wins skip on the primary scan) and symlink-only
  (8 sorted IDs via the primary root) — identical baselines.
- **Stage 3 design input (agreed):** template plans ship in Nexus bundles —
  manifest v1 gains optional `plans: [...]`; the installer seeds
  `<config_dir>/bureau/` on FIRST install only, never overwrites user edits;
  host `resources/examples` keeps host-native examples only; the ataria repo
  keeps canonical plan sources (production config-dir symlink = stopgap).
- **Payload hygiene (done):** `build/`, `dist/` removed; `__pycache__`
  regenerates on every dev import — removed again and verification harnesses
  now run with `PYTHONDONTWRITEBYTECODE=1`; `docs/` identified as mkdocs
  SOURCE and moved to the ataria root (generator output-path follow-up
  non-blocking, see 46d459b).
- **§6-3 answer (Stage 4 input):** the host repo's `ainara/nexus` dev tree
  can be removed once the host ships no nexus app code; cleanup items then:
  the mkdir fallback in NexusSkillProvider.__init__ (recreates it empty in
  dev) and get_nexus_base_paths() always appending the primary (harmless
  when missing — is_dir() guard, proven in today's runs).
