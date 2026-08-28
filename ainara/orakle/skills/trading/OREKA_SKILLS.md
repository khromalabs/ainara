# The `oreka_*` skills are copies. Do not edit them here.

`oreka_desk`, `oreka_signal` and `oreka_preflight` are maintained in the **Oreka**
repository at `integrations/ainara/`, so they version with the engine they wrap.
The files in this directory are snapshots taken by `cp`.

| | |
|---|---|
| Source | `<oreka>/integrations/ainara/` |
| Oreka version | `0.1.0` |
| Oreka commit | `7e485b3` |
| Copied on | 2026-08-27 |

The three `.py` files are **content-identical** to their source, so a diff
against Oreka is the staleness check:

```bash
diff --strip-trailing-cr <oreka>/integrations/ainara/oreka_desk.py oreka_desk.py
```

Use `--strip-trailing-cr` (or `git diff --no-index`): git checks these out with
CRLF endings on Windows while the Oreka working copy has LF, so a plain `diff`
reports every line as changed and tells you nothing. The `.SKILL.md` files differ only by the provenance keys in their
frontmatter (`version`, `oreka_version`, `oreka_commit`, `copied_on`), which
exist because a bare `version: "1.0"` could not tell a fresh copy from an old
one.

## Refreshing

```bash
cp <oreka>/integrations/ainara/oreka_*.py        ainara/orakle/skills/trading/
cp <oreka>/integrations/ainara/oreka_*.SKILL.md  ainara/orakle/skills/trading/
```

Then re-apply the provenance keys above with the new commit, and reinstall Oreka
into the environment Orakle runs in — the package changes, not just the skills.
Diff before copying: a local edit here was made for a reason.

## They need Oreka importable by Orakle

If `import oreka` fails, each skill returns a clear `{"installed": false,
"error": ...}` rather than a stack trace. That is deliberate — do not replace it
with a silent fallback. See `<oreka>/integrations/ainara/README.md` §3 for why
none of these can place an order, and §4 for the open import-versus-proxy
question.

## Not related to `carry_engine.py` / `portfolio.py` / `executor_client.py`

Those are Ainara's own pre-extraction carry skills and are a separate, older
implementation of the same strategy. They are untouched by this add-on, which is
why these files carry the `oreka_` prefix. Whether they are retired is the
owner's call.
