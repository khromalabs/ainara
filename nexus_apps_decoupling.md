# HANDOVER NOTE — Nexus Apps decoupling (session of the crash)

**Status:** Repo being reset to pre-crash state. No edits from the failed session survive. This note is the single source of truth for the clean restart.

## 1. Problem & goal

Ainara (Python backend) / Polaris (Electron shell) currently ships as "special editions" (public vs. `supporters/`, driven by obfuscated bundles and edition markers in `scripts/_obfuscate.py` + PyInstaller specs). Goal: **one edition** that loads installable **Nexus Apps** — self-contained bundles of Python skills + optional UI web components — under the PEP 420 namespace `ainara.nexus.<vendor>.<bundle>`. Ataria becomes the first installable app instead of a hard-coded bundled tree.

## 2. Agreed design decisions

1. **Extraction model**: apps are wheels **extracted, never pip-installed**, into `<data_dir>/nexus/.apps/<app_id>/`. App root = wheel site-root: `manifest.json`, `ainara/nexus/<vendor>/<bundle>/…`, optional `pyarmor_runtime_*/`. Original wheels kept in `.apps/cache/`.
2. **Namespace rule**: **no `__init__.py`** at `ainara/`, `ainara/nexus/`, or vendor level — on the host bundle **and** inside apps. Bundle level and deeper keep theirs. PEP 420 merging makes existing user-skill imports (`from ainara.nexus.khromalabs.ataria… import …`) work unchanged.
3. **Precedence**: primary (bundled) root wins. App site-roots prepended to `sys.path` in reverse order so the primary root ends up first.
4. **manifest.json v1**: flat (no wrapper). Fields: `schemaVersion, name, provider, version, description, requiresPolaris` (version **range**, not bool), optional `entryPoint` (absent = pure directory-scan bundle), optional `ui.components`, optional soft-declared `permissions` (log/UI only; no enforcement in v1). Minisign signature **detached** (`.minisign` beside the wheel), verified server-side in Python, not in Electron.
5. **Dual validation**: installer validates at install time; provider re-checks `schemaVersion`/`requiresPolaris` each startup (skip + log on mismatch).
6. **Containment allowlist** (install time): wheel top level may only contain `ainara/`, `manifest.json`, `pyarmor_runtime_*/`.
7. **PyArmor**: optional per app; **pin one PyArmor version** across all builds — identical runtime dir names must be identical builds (first import wins in `sys.modules`).
8. **Dev mode**: `.apps/dev.json` maps app-id → local site-root (Phase 3).
9. **Data dir**: reuse `get_default_data_dir()` → Linux `~/.local/state/ainara/nexus/.apps`.
10. **`serve_component` unchanged** — `(vendor, bundle)` uniqueness comes from namespace ownership.

## 3. Roadmap (5 stages)

1. **Namespace conversion (host repo)** ← clean start begins here
2. **Multi-root discovery + soft manifest gate** (validator + `/docs` multi-root pending)
3. **NexusInstaller**: download → minisign verify → manifest validate → containment check → extract `<id>.new/` → atomic swap → record; plus `dev.json`
4. **Per-app build pipeline (CI)**: stage → optional license guards → optional PyArmor → wheel + `.minisig`; platform matrix
5. **Cleanup**: `servers.spec` drops SUPPORTERS branches/edition marker; `_obfuscate.py` reduced to app-build role only

## 4. Stage 1 — edit list (schemas, to be re-applied cleanly)

- **1.1** Version single-source: `__version__` lives in `ainara/framework/__init__.py`. ⚠️ **Gotcha:** in the current chat-truth, `ainara/framework/__init__.py` **already** has `__version__ = "0.11.0"` / `__version_info__`, while `ainara/__init__.py` is a **header-only file with no version** — but pre-crash `pyproject.toml` pointed at `ainara.__version__`. First action after reset: `git show HEAD:ainara/__init__.py` to see the true original, then align.
- **1.2** `pybridge.py`: `from ainara import __version__` → `from ainara.framework import __version__`.
- **1.3** `pyproject.toml`: `version = {attr = "ainara.framework.__version__"}`; `[tool.setuptools.packages.find]` → `include = ["ainara*"]`, `namespaces = true`.
- **1.4** Delete `ainara/__init__.py` (`git rm`).
- **1.5** Delete `ainara/nexus/__init__.py` and `ainara/nexus/khromalabs/__init__.py` (bundle-level `__init__.py` files **stay**).
- **1.6** `scripts/pyinstaller/servers.spec`: drop `ainara/__init__.py` from `common_datas`.
- **1.7** `scripts/_obfuscate.py`: add `_strip_namespace_inits()` — after staging the tree, remove `__init__.py` at `nexus/` and each vendor dir directly under it (no-op once tree is namespace-native).

## 5. Stage 2 — edit list (schemas)

- **2.1** `config.py`: new `get_nexus_base_paths() -> List[Path]` — primary root first (`get_nexus_base_path()`), then each `<data_dir>/nexus/.apps/<app_id>/ainara/nexus` portion; skip `.`/`_`-prefixed dirs, `cache`; debug-log skips. Needs `List` import.
- **2.2** `capabilities/nexus.py` `__init__`: `self.nexus_paths = config.get_nexus_base_paths()` (keep old ctor arg accepted-but-unused); mkdir fallback only for primary root when not frozen; **prepend app site-roots to `sys.path`** (guard: `path.parent.name == "ainara"`; reverse order; dedupe). Must run in `__init__`, before any `discover()`.
- **2.3** `capabilities/nexus.py` `discover()`: wrap the vendor scan in `for root in self.nexus_paths:`; per-root `is_dir()` guard + log; body otherwise unchanged. **Rename the old local `root` in the register-root block (e.g. `root_name`) to avoid shadowing the loop variable.**
- Unchanged: `manager.py`, `serve_component`, `skills.py`.

## 6. Affected files inventory

| File | Stage |
|---|---|
| `ainara/framework/__init__.py` | 1.1 |
| `ainara/framework/pybridge.py` | 1.2 |
| `pyproject.toml` | 1.3 |
| `ainara/__init__.py` (delete) | 1.4 |
| `ainara/nexus/__init__.py`, `ainara/nexus/khromalabs/__init__.py` (delete) | 1.5 |
| `scripts/pyinstaller/servers.spec` | 1.6 |
| `scripts/_obfuscate.py` | 1.7 |
| `ainara/framework/config.py` | 2.1 |
| `ainara/framework/capabilities/nexus.py` | 2.2, 2.3 |

## 7. Post-verification checklist

**Stage 1:** (a) `grep -rnE "from ainara import|ainara\.__version__" --include="*.py" .` → empty; (b) `python -c "from ainara.framework import __version__"`; (c) import a dev-symlinked Ataria module and print `__file__`; (d) a real user skill importing `KhromalabsAtariaCryptoAggregator` still loads; (e) PyInstaller build (`scripts/_build.py -e public -t pybridge`) starts, `/health` OK — validates PEP 420 inside `_MEIPASS` (the risky one).

**Stage 2:** (a) `grep -rn "nexus_path" --include="*.py" ainara/` → only `nexus.py` + manager construction line; (b) empty `.apps/` → one root scanned, identical skill counts; (c) test app `.apps/testapp/ainara/nexus/testlab/demoapp/` (fresh vendor name) → both roots load, `/capabilities` lists both; (d) Ataria-importing user skill still works.

## 8. What happened in the crashed session — lessons

- All Stage 1+2 edits were applied mechanically in one go; the session then crashed mid-audit.
- The applied diff **looked plausible but was internally inconsistent** (mixed singular/plural attribute names such as `nexus_path`/`nexus_paths`, and similar near-duplicate identifiers in the discovery/UI and `.apps` scanning hunks) — exactly the kind of error that only surfaces at import/scan time. My audit of it was interrupted before completion.
- **Decision: reset and re-apply from this note, in small steps, verifying after each stage** — do not batch Stage 1 + Stage 2 again.
- During application, keep identifier spelling checked line-by-line against this note; after each file, run the relevant grep/python check immediately.

## 9. Clean start — what to add to the chat

1. `ainara/framework/capabilities/nexus.py` (full)
2. `ainara/framework/config.py` (or at least the `get_nexus_base_path` region + imports)
3. `scripts/_obfuscate.py`
4. `scripts/pyinstaller/servers.spec` (datas section)
5. `pyproject.toml`
6. `git show HEAD:ainara/__init__.py` output (resolve the version-location gotcha)
