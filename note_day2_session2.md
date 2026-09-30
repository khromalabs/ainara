# HANDOFF NOTE — Nexus Apps decoupling, Day 2 (session 2)

**Companion to `note.md`** (Day 2 master note). Where the two overlap, this file is
newer; anything in `note.md` §1–§8 not repeated here stays authoritative. This note
records the second half of Day 2: the 2.1+2.2 verification & commit, the
platform-dependence review, the full Stage 2.3 slice (delivered **and applied** to
the working tree), and the exact outstanding checklist with expected outputs.

**How to resume:** add the files listed in §10 to the chat, then execute §3 top to
bottom. Never batch stages — apply → verify → proceed (note.md §8).

## 1. State at handoff (TL;DR)

- **Stage 1 — committed.** Namespace conversion + version single-sourcing
  (note.md §2/§3; the §3 namespace assert is the fixed
  `getattr(ainara, '__file__', None) is None` form).
- **2.1 + 2.2 — committed; that commit is the expected HEAD.**
  - `config.py`: `get_nexus_base_paths() -> List[Path]` — dev roots from
    `nexus.dev_apps` (app_id → repo root; runtime appends `/ainara/nexus`),
    then installed apps under `<data.directory>/nexus/.apps/<app_id>/ainara/nexus`
    (skips `.`/`_`-prefixed and `cache`), then the primary root from
    `get_nexus_base_path()` (kept as alias). Dedupe by resolved path, first
    occurrence wins. Hardened: primary alias via `get_nexus_base_path()`;
    sys.path dedupe guarded by `if p is not None`; a non-dict `nexus.dev_apps`
    logs a warning and is ignored.
  - `capabilities/nexus.py` `__init__`: `self.nexus_paths =
    config.get_nexus_base_paths()`; legacy ctor arg `nexus_path` accepted but
    unused; app site-roots prepended to `sys.path` in reverse order (dev ends up
    at `[0]`), `importlib.invalidate_caches()`, the
    `Nexus roots (precedence order): [...]` log line; mkdir fallback only for
    the primary root when not frozen.
- **2.3 — applied, NOT committed, NOT verified.** Wholesale replacement of
  `discover()` in `capabilities/nexus.py` (see §4) plus note.md updates
  (2.3 ✅ marker, §5b locked decisions, §5c fixture commands).
- **Outstanding:** pre-flight gate → Runs A/B/C with fixture + teardown → 2.3
  commit → ataria repo restructure → 2.4 verification → 2.5 (deferred).

> ⚠️ **Status caveat — read first.** note.md §5-2.3 already *reads* "Verified
> A/B/C: 8 → 9 → 8 skills" because that text shipped inside the pre-staged diff.
> It only becomes true when §3's runs actually execute and pass. Check shell
> history / logs for whether they ran; if not, run them now (or temporarily
> reword note.md to "pending verification"). Never commit a claim of
> verification that did not happen.

## 2. What 2.1+2.2 proved (V1–V3, all green)

- **V1 — root list matches the primary alias.** With no dev apps and no
  installed apps, `get_nexus_base_paths()` returns exactly
  `[get_nexus_base_path()]`.
- **V2 — sys.path neutrality.** Instantiating the provider from the repo cwd
  does not duplicate the cwd entry: `''` resolves to the repo root and the
  resolved-path dedupe collapses it (`if p is not None` guards None entries).
- **V3 — byte-identical baseline.** 8 nexus skills from khromalabs/ataria,
  identical to the pre-change run when compared as **sorted ID lists + counts**.
  The `_components` warnings pointing at `/home/ruben/lab/src/ataria` are
  expected: they prove symlink-based discovery, they are not errors.
- **Discipline:** verification output is set-hashed; warning/log ORDER is noise.
  Every future verification compares sorted lists and counts, never log order.

## 3. Outstanding checklist — execute in order

### 3.0 Pre-flight gate

```bash
cd <ainara repo root>
git status --short          # expect EXACTLY:
#                            M ainara/framework/capabilities/nexus.py
#                            M note.md
git log --oneline -3        # HEAD must be the 2.1+2.2 commit
```

- Anything else modified → stop and identify it before proceeding.
- If the tree is clean and HEAD already contains a 2.3 commit, the runs were
  finished after this note was written — skip to §6.

### 3.1 Run A — neutrality baseline (fixture absent)

Confirm the fixture is absent (`test -e "$APPS_ROOT/testapp"` → nothing), then:

```bash
python - <<'EOF'
from ainara.framework.capabilities.nexus import NexusSkillProvider
from ainara.framework.config import config

provider = NexusSkillProvider("ainara/nexus", config, None)
caps = provider.discover()
ids = sorted(k for k, v in caps.items() if v.get("type") == "nexus")
print("NEXUS_SKILL_COUNT:", len(ids))
for i in ids:
    print("  ", i)
EOF
```

Expect: `NEXUS_SKILL_COUNT: 8`; the `Nexus roots (precedence order)` log lists
only the primary root; final log `Loaded 8 nexus skills.`
**Save the sorted list — it is the frozen baseline for Run C.**

### 3.2 Create the fixture

Use note.md §5c verbatim (repeated here for self-containment; it must match):

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

`APPS_ROOT` is config-derived on purpose (portable across the Windows
`Saved Games` layout). Bundle-level `__init__.py` included; `hello/` relies on
PEP 420. Class name is dictated by discovery: `Testlab` + `Demoapp` + `Hello` +
`World` → id `testlab_demoapp_hello_world`.

### 3.3 Run B — second root active

Re-run the §3.1 harness. Expect:

- `NEXUS_SKILL_COUNT: 9`, including `testlab_demoapp_hello_world`;
- the precedence log lists TWO roots, testapp portion first:
  `[<data>/nexus/.apps/testapp/ainara/nexus, <repo>/ainara/nexus]`;
- two `Scanning for Nexus bundles in:` lines (one per root);
- `Loaded 9 nexus skills.`

Then exercise execution (first real use of the 2.2 sys.path prepend for a
non-cwd root — `hello.world` imports through the testapp site-root):

```bash
python - <<'EOF'
from ainara.framework.capabilities.nexus import NexusSkillProvider
from ainara.framework.config import config

provider = NexusSkillProvider("ainara/nexus", config, None)
provider.discover()
print(provider.execute("testlab_demoapp_hello_world", {}))
EOF
# expect: {'greeting': 'hello from testlab/demoapp'}
```

### 3.4 Teardown (mandatory) + Run C

```bash
rm -rf "$APPS_ROOT/testapp"
```

The fixture lives outside the repo and would silently shift every future
baseline if left behind. Re-run the §3.1 harness: the sorted list must EQUAL
Run A's saved list (list equality, not just the count 8).

### 3.5 Commit 2.3

Only after A/B/C pass. Optional tidy: note.md §5-2.1 still contains the
superseded "primary root first" phrasing (§5b supersedes it, but the stale
words remain) — fix it to "dev > installed > primary" in the same commit.

```bash
git add ainara/framework/capabilities/nexus.py note.md
git commit -F - <<'MSG'
feat(nexus): multi-root discover() with first-wins precedence (Stage 2.3)

- Scan every root from config.get_nexus_base_paths() (dev > installed >
  primary) instead of only the primary alias; per-root is_dir()/OSError
  guards and sorted() scan order for reproducible verifications.
- seen_bundles gives (vendor, bundle) first-wins semantics across roots;
  a bundle yielding zero skills in a higher-precedence root never falls
  back to a lower copy (that would mask dev-tree errors).
- Fix latent accumulation bug: BasePythonSkillProvider.discover() resets
  self.capabilities on every call, so the old update-into-self pattern
  kept only the last-scanned bundle; skills now accumulate into a local
  all_caps dict with a single final assignment.
- Rename local `root` -> `root_name` in the register_nexus_root block to
  avoid shadowing the scan-loop variable.

Verified A/B/C against the testlab/demoapp fixture (note.md §5c):
8 -> 9 -> 8 nexus skills; execute('testlab_demoapp_hello_world') OK.
MSG
```

## 4. What the 2.3 discover() replacement does (record)

- Root loop over `self.nexus_paths` with per-root `is_dir()`/`OSError` guards
  and `sorted()` for deterministic vendor/bundle scan order.
- `seen_bundles` set: `(vendor, bundle)` **first-wins** across roots — the
  highest-precedence root that CONTAINS a bundle owns it even if it yields
  zero skills; no silent fallback to lower-precedence copies.
- Skills accumulate into a local `all_caps` dict; single
  `self.capabilities = all_caps` at the end. This fixes the latent bug where
  `super().discover()` (BasePythonSkillProvider, `skills.py`) resets
  `self.capabilities` per call — the old update-into-self pattern would have
  kept only the last-scanned bundle in a multi-root scan.
- `root` → `root_name` rename in the `register_nexus_root` block to avoid
  shadowing the loop variable.
- Unchanged by design: `manager.py`, `serve_component`, `skills.py`; the
  provider ctor still accepts the legacy `nexus_path` arg (unused).

## 5. Findings recorded this session (no code changes generated)

1. **`data.directory` platform dependence** (`/home/ruben/.local/state/ainara`
   here; Windows `Saved Games\Ainara\Data`): irrelevant to Stage 2 *code* —
   everything derives from `data.directory` via `get_default_data_dir()`.
   It matters for: (a) verification one-liners — keep them config-derived
   (the `APPS_ROOT` pattern in §3.2); (b) shell quoting around the
   `Saved Games` space → Stage 4 doc note; (c) the future installer must
   derive paths from config.
2. **First-run config quirk (pre-existing):** the no-file branch of
   `load_config()` populates only `logging.directory`, so `data.directory`
   can be unset on first launch. `get_nexus_base_paths()` degrades gracefully
   (primary only, no crash). Non-blocking cleanup candidate: populate
   `data`/`cache` defaults in that branch too.
3. **`$XDG_STATE_HOME` inconsistency:** `get_default_data_dir()` hardcodes
   `~/.local/state` on Linux (ignores `$XDG_STATE_HOME`) while
   `get_default_log_dir()` honors `$XDG_DATA_HOME`. Deferred — explicitly no
   changes generated yet.
4. **Schema:** `resources/config.schema.json` needs NO change for
   `nexus.dev_apps` — the root schema doesn't set `additionalProperties: false`,
   so the key passes Draft7 validation as-is.
5. **Day-1 leftover (still pending, non-blocker):** Orakle user-skill import
   check (`grep -rn "class Khromalabs" ... /ataria/crypto`). Its path changes
   after the §6 restructure — re-derive from the new payload location.

## 6. Next after the 2.3 commit — ataria repo restructure (gates 2.4)

Goal: the ataria repo itself adopts the app payload layout so `nexus.dev_apps`
can point at it (§5b: value = repo root containing the `ainara/nexus` portion).

1. Inside `/home/ruben/lab/src/ataria`: create `ainara/nexus/khromalabs/ataria/`
   and `git mv` the bundle content into it — skills packages (e.g. `crypto/`),
   the bundle-level `__init__.py`, `nexus.json`, `providers_registry.json`,
   `skills_metadata.json`, `site/`, `_components/` if present at the root.
   **`_scripts/` stays at the repo root, outside the payload** (locked, §5b).
2. Host repo: re-point the dev symlink at the new payload path:
   ```bash
   ln -sfn /home/ruben/lab/src/ataria/ainara/nexus/khromalabs/ataria \
           ainara/nexus/khromalabs/ataria
   readlink ainara/nexus/khromalabs/ataria   # verify
   ```
3. Re-verify: namespace chain snippet from note.md §3, plus the §3.1 harness —
   still 8 skills, sorted-equal to the frozen baseline.
4. Build tooling expects no change: `_obfuscate.py` dereferences the symlink
   via `os.path.realpath()` into `build/ataria_compiled`, and
   `_strip_namespace_inits()` only strips nexus-/vendor-level inits, so the
   bundle-level `__init__.py` survives (the invariant Stage 3's PyArmor story
   depends on). Only rebuild if you touch those scripts anyway (Stage 4
   removes this path entirely).

## 7. Then 2.4 — dev apps via config (mostly pre-wired)

The runtime side of 2.4 landed early inside `get_nexus_base_paths()` (2.1): it
already reads `nexus.dev_apps` as `{app_id: repo-root-containing-ainara/nexus}`
and appends `/ainara/nexus` internally. Remaining work:

1. End-to-end verify with the restructured ataria repo as a dev app. Add to a
   test config (`AINARA_CONFIG` or user config):
   ```yaml
   nexus:
     dev_apps:
       ataria: /home/ruben/lab/src/ataria
   ```
   Expect: 8 skills with the dev root FIRST in the precedence log. With the
   symlink still present, the bundle exists under two roots; first-wins makes
   the dev root own it and the primary scan logs the skip — expected, not a bug
   (and the resolved-path dedupe does not collapse them: different directories).
2. Record the config.yaml decision as final (lean was config.yaml; the
   implementation already uses `nexus.dev_apps`); clear the OPEN marker in
   note.md §6-1 and the "(blocked on ataria restructure — §5b)" marker in §5-2.4.
3. Symlink retirement (note.md §6-4: keep until 2.4 verified): remove
   `ainara/nexus/khromalabs/ataria` after 2.4 passes and re-verify (still 8
   skills, now served by the dev root).

## 8. Deferred — 2.5 pybridge multi-root docs

- `ainara/framework/pybridge.py` (~lines 1260 & 1282): `/docs/list` and
  `serve_docs` read `config.get_nexus_base_path()` — single-root; convert to
  iterate `config.get_nexus_base_paths()`.
- The §5c/§3.2 fixture is kept re-creatable precisely to exercise a second
  root in `/docs/list`.
- Still open from note.md §7: whether `pybridge/server.py` is distinct from
  `ainara/framework/pybridge.py` — 2.5 touches the latter; ask before editing.

## 9. Unchanged files / Stage 3–4 context

- Unchanged this session: `capabilities/skills.py`, `capabilities/manager.py`,
  `scripts/_obfuscate.py`, `scripts/_build.py`, `scripts/build`,
  `scripts/pyinstaller/servers.spec`, `pyproject.toml`,
  `resources/config.schema.json`.
- Stage 3 (per-app packaging in each app's repo: stage → optional PyArmor with
  ONE pinned version — regular package input since bundle has `__init__.py` →
  wheel/bundle + `manifest.json` v1 + detached minisign; containment allowlist:
  top level only `ainara/`, `manifest.json`, `pyarmor_runtime_*/`) and Stage 4
  (installer; then strip edition machinery `-e`/`POLARIS_EDITION`/`.edition`/
  supporters branches/ataria materialization from `_build.py`, `_obfuscate.py`,
  `servers.spec`; host ships no nexus app code) are untouched. `AuthManager`
  degrades to public mode without `supporters.auth_core` (note.md §4-6).

## 10. Files to add to the chat at next session start

1. `note.md` + this note
2. `ainara/framework/config.py`
3. `ainara/framework/capabilities/nexus.py` (full)
4. `ainara/framework/capabilities/skills.py` (BasePythonSkillProvider lives here)
5. `ainara/framework/capabilities/manager.py` (wiring reference)
6. `ainara/framework/pybridge.py` (2.5 target; also resolve the
   `pybridge/server.py` question)
7. `scripts/_obfuscate.py`, `scripts/_build.py`, `scripts/build`,
   `scripts/pyinstaller/servers.spec` (Stage 3/4; read-only for now)
8. `pyproject.toml`
9. `resources/config.schema.json` (only if schema work comes up)

## 11. Working rules (carried + added this session)

- Never batch stages; apply → verify → proceed.
- Verification = **sorted lists + counts**, never log order (set-hash noise).
- Fixture teardown is mandatory; it lives outside the repo.
- Pre-written note text is not verification — runs must actually execute
  before claims or commits.
- Keep verification one-liners config-derived (APPS_ROOT pattern) so they
  survive platform moves; mind `Saved Games` quoting on Windows.
- Identifier spelling checked line-by-line (`nexus_path`/`nexus_paths` was a
  crash cause); grep broadly (`__version`, not one import pattern) and
  cross-tree (scripts/, polaris/, specs), not just `*.py`.
- Confirm deletions with `git status --short`, never assume.
- Ask for file contents before drafting edits — true file state beats summaries.
- User-level compiled app: no pip / no interpreter / no CLI assumptions, ever.
