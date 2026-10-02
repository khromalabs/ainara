# SEED NOTE — Stage 4 direction: universal bundles via a host-side loader library

Status: IDEA RECORD (no implementation yet). Written post-Stage-3b review
session (host `71d76891`, ataria `307fc53`) so the design survives until
work resumes. Nothing below is built; everything below is reachable from
what IS built.

---

## 1. Problem being solved

Protected (obfuscated) Nexus bundles are platform-specific today: the
PyArmor runtime (`pyarmor_runtime_<license>/`, native `.so`/`.dll`) ships
inside each artifact, glibc-bound to the pack machine. Consequences:
one artifact per OS/arch, a glibc floor at *pack* time, and users must
pick the right download. Open bundles don't have this problem
(`platform: "universal"`).

The obfuscated blobs themselves ARE portable — bytecode interpreted by
the runtime. The only native material is the loader.

## 2. The idea: loaders as an independent, host-managed library

Move the native loaders OUT of the bundles into a framework-owned,
platform-specific, user-updatable library in data space:

```
<data.directory>/nexus/loaders/
  pyarmor/
    015212/
      linux-x86_64/pyarmor_runtime_015212/…
      win-amd64/…
      darwin-arm64/…
      manifest.json          # hashes + minisign signatures
```

- Bundles return to `universal`: portable blobs + a bootstrap that
  *requests* a loader instead of carrying one.
  Manifest: `"loaders": [{"kind": "pyarmor", "id": "015212", …}]`.
- The loader library lives in DATA space, not inside the frozen app —
  loaders update like drivers, independently of Polaris releases.
- The bundle's plaintext bootstrap `__init__.py` (shipped since the
  protected-pack stage) becomes a DISPATCHER through an open framework
  module, e.g. `ainara.framework.nexus_loaders.ensure_runtime(kind, id)`.
- Precedent: the JVM/.NET/WASM model — universal code, platform-specific
  engine installed once and shared.

## 3. Why this is framework-shaped (Nexus App Editor Toolkit)

- `kind` generalizes: "pyarmor" today, "wasm"/"native-ext"/… later. A
  loader is just *platform-specific execution material a universal bundle
  may request*. Framework owns the contract (resolution API, manifest
  schema, verification rules); loaders are pluggable.
- Completes a three-way decoupling, each with its own cadence:
  Polaris/servers (app) / loader library (platform material) / bundles
  (universal vendor payload).
- Ecosystem win: vendors publish ONE universal artifact per release;
  users install ONE bundle; platform material is fetched automatically.

## 4. Evolution path (nothing already built is invalidated)

- The current protected-pack pipeline, platform tags and bootstrap are
  load-bearing parts of this future: the bootstrap literally becomes the
  dispatcher; the platform tag becomes the loader-selection key.
- Fallback chain to preserve: bundle-local runtime (self-contained
  platform variant, what ships today) → loader library → host
  `_internal` → clear error. Manifest declares which mode the artifact
  was packed for (`"runtime": "bundled" | "host" | "loader"`).
- Transitional state (today): `platform`-tagged protected zips remain
  correct and shippable; the loader model can land per-bundle later
  without repacking old artifacts (they keep their bundled runtime).

## 5. Open questions / sharp edges

1. **Per-vendor license wrinkle**: PyArmor's runtime dir name derives
   from the obfuscator's license (015212 = ours). Other vendors
   obfuscating under their own regcode request different loader ids →
   loader library must be a registry keyed by (kind, id, version,
   platform), populated per-vendor. Investigate whether PyArmor CI/CD or
   trial modes yield generic runtime names.
2. **Supply chain**: loaders are native code executing protected blobs.
   Loader packs MUST be signed (framework channel key + vendor pack
   key) and hash-verified by `ensure_runtime` before touching sys.path.
   Non-negotiable.
3. **glibc floor**: doesn't disappear — moves into each linux loader
   pack, solved once per loader version (builder container, glibc 2.35),
   not once per bundle pack. Strictly better, not free.
4. **License terms**: redistributing PyArmor runtime outputs is the
   normal model (already done inside today's zips); generating loaders
   for other platforms needs the Pro tier (held: pyarmor-vax-015212).
   Skim regfile terms when implementing.

## 6. Related Stage 4 items (from the same review session)

- `AuthManager` → bundle-provided issuer (licensing service inside the
  protected bundle; LGPL seam already in place — public mode when the
  bundle is absent).
- Polaris UI licensing signal (currently always 'public' with the
  `.edition` marker gone).
- Transitional installer CLI: verify (sha256+minisign vs pinned vendor
  pubkey) → lint manifest vs running Polaris + platform tag → atomic
  swap into `<data.directory>/nexus/.apps/<app_id>`.
- Real creatorId (Solana pubkey) — packs still need `--allow-placeholder`.
- `dist/pp` transient (note_stage3_forensic §6.10) — still unexplained.
