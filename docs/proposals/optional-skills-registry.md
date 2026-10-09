# Proposal: Optional Skills Registry

**Status:** Draft — discussion and decision tracking in [Issue #17](https://github.com/khromalabs/ainara/issues/17); this document is the versioned record, with major decisions from the thread backported here.
**Author:** Rubén Gómez
**Date:** 2026-10-09
**Related:** Issue #17 (discussion), PR #11 (habit tracker / timezone skills), PR #12 (skill builder), PR #11 review thread (bundling mechanism)

---

## 1. Motivation

The core skills tree (`ainara/orakle/skills/`) is accumulating skills that do not
belong in core: a habit tracker, a timezone lookup, and similar personal-workflow
or niche capabilities are on their way in. This creates three concrete problems:

1. **Matcher degradation.** Every discovered skill is a matcher candidate for
   every user query (`OrakleMiddleware` registers all served capabilities with
   the semantic matcher). Core bloat directly reduces routing precision — the
   `report`-vs-notes confusion observed in PR #11's review is an early symptom.
2. **Coupled release cadence.** Framework releases and skill contributions are
   currently the same pipeline. A well-built but niche skill either waits on a
   framework release or dilutes core by landing there.
3. **Review friction.** Skill PRs must satisfy a higher bar (universality) than
   the code quality alone requires, which is hard to communicate and inconsistently
   applied.

## 2. Proposed model: three tiers plus Nexus

| Tier | Location | Content | Lifecycle |
|------|----------|---------|-----------|
| **Core** | `ainara/orakle/skills/` | Universally useful skills only | Ships and versions with the framework |
| **Curated optional** | Separate skills repository → installed locally | Community-maintained, reviewed skills | User opts in per skill; updates independent of framework releases |
| **User skills** | `user_skills.directory` | Personal and LLM-generated skills | User drops files or asks the skill builder (PR #12) |

**Nexus Apps** remain a tier above/alongside these: bundles with UI components,
licensing, persistence, and multi-capability apps. The boundary rule:

> If it needs a web component, vendor licensing, or a backend beyond a single
> `run()` call → **Nexus**. If it is one skill file + `SKILL.md` → **optional
> skill or user skill**.

## 3. What stays in core

Triage heuristic: *would virtually every user expect this to just work on first
run, with no configuration and no explanation?*

- **Passes:** calculator, file operations, current time/weather, URL opening —
  capabilities whose absence would make the assistant feel broken.
- **Fails (goes to the optional repo):** habit tracker, timezone lookup, crypto,
  stock lookup, niche integrations — excellent skills, but selectable rather
  than default.

Core should be a *small, boring, complete-feeling* baseline. Anything that
requires knowing the user's lifestyle, profession, or interests is optional.

## 4. The skills repository

A separate repository (e.g. `khromalabs/ainara-skills`) containing curated,
optional skills:

```
ainara-skills/
  registry.yaml          # index: name, version, description, category, license
  skills/
    productivity/
      habit_tracker/
        habit_tracker.py
        habit_tracker.SKILL.md
      pomodoro/
        ...
    finance/
      stock_quote/
        ...
```

Conventions:

- Each skill is **self-contained**: one `.py` file + one `SKILL.md` (agentskills.io
  front-matter format, already the project standard).
- One directory per skill; no cross-skill imports. Shared helpers belong in the
  framework or get duplicated deliberately.
- Skills declare `required_data` (already supported by `Skill`) and never write
  outside `get_data_dir()` (established in the #12 review).
- Each skill carries its own license header consistent with the project's
  dual-license model.

**Quality bar:** same review rigor as core PRs today (correctness, matcher_info
quality, structured returns, no secrets in code) minus the universality
requirement — that is precisely what the tier boundary replaces.

## 5. Installation and updates

**The Polaris wizard is the primary interface.** Polaris is a final-user-oriented
application — that is the whole reason the setup wizard exists — so curated
skills are offered where users already are: a new **Skills step in the wizard**
(and reachable later from settings) that browses the registry, shows
description/category/tier, and installs with one click. No terminal required,
consistent with the project's strong end-user vocation. A user-facing CLI is
deliberately out of scope; if developer tooling is wanted someday it can be
added on top of the same service, but it is not the adoption path.

Under the wizard sits a small **install/update service** — the contract, so the
UI stays thin:

```
GET  /skills/registry            # list available curated skills (from registry.yaml)
GET  /skills/installed           # what is installed, versions, provenance
POST /skills/install             # {name, version?} → installs into optional dir
POST /skills/remove              # {name}
POST /skills/update              # {name?} → pull newer versions
```

(the exact host/paths — Orakle vs. PyBridge — is an open question; see §10)

- **Provenance:** installed skills land in a dedicated directory (§6) so the
  system can distinguish *curated-installed* from *user-authored*. An
  `.installed-from.yaml` sidecar per skill records source repo, version, and
  install date — enabling updates and conflict detection (user edited an
  installed skill → warn instead of clobber). The wizard uses this to badge
  skills as *curated* vs. *yours* and to warn before overwriting edits.
- **Integrity:** v1 ships plain file copy. The sidecar format reserves fields
  for hashes/signatures so signed registries can be added without a migration.

## 6. Discovery changes

Config gains one key next to the existing `user_skills.directory`:

```yaml
skills:
  optional:
    directory: ~/.local/share/ainara/optional_skills   # registry installs
  user_skills:
    directory: ~/ainara_skills                         # personal / generated
```

`CapabilitiesManager` already instantiates one provider per root; adding a
third provider instance for the optional directory is a small, contained
change.

**Naming and collision prevention.** User skills are already prefixed with
`user_` by `UserSkillProvider.discover()` (`user_<category>_<name>`, e.g.
`user_tools_hello`) precisely so a personal skill can never collide with a
core capability id — visible today on `GET /capabilities`, where core skills
are unprefixed (`tools_calculator`) and user skills carry the prefix with
`type: user_skill`. Optional installed skills follow the same pattern with an
`opt_` prefix (`opt_<category>_<name>`): collision-freedom against core ids is
then guaranteed by construction rather than enforced by installer checks, and
the tier is readable straight from the capability name — useful in logs,
matcher traces, and the Polaris capabilities view.

Capability metadata gains provenance:

- `origin: "core" | "optional" | "user"` — set by the provider that discovered
  the skill (also derivable from the `opt_`/`user_` id prefix, but explicit
  metadata is cheaper for consumers than string parsing).
- Served in `get_capabilities()` and visible to Polaris; also lets the matcher
  pipeline and future UI group skills by tier.

**Matcher note:** optional skills register exactly like today — a skill only
becomes a routing candidate when the user installed it, which is the point.

## 7. Interaction with user skills and the skill builder (PR #12)

- The skill builder (PR #12) keeps writing to `user_skills.directory` —
  generated code is personal by definition.
- Before generating, the builder's duplicate check (`_find_existing_skill`)
  gains a "check the registry" step: if a curated skill matches, suggest
  suggest installing the curated skill from the registry (one click in the
  wizard) instead of generating a near-duplicate.
- If a curated skill is *close but not right*, users still generate into their
  personal directory — no conflict, since the directories are separate.

## 8. Migration plan

1. **Phase 0 — this proposal** is circulated for feedback (including the
   contributor of #11/#12, who has been effective in this area).
2. **Phase 1 — repository bootstrap:** create `ainara-skills` with
   `registry.yaml`, move `habit_tracker` and `timezone_lookup` (freshly merged
   in #11) from core to the repo, note the moves in release docs. Core shrinks
   by two; nothing is lost for users who install them.
3. **Phase 2 — discovery:** add the `skills.optional.directory` config key,
   third provider, `origin` metadata.
4. **Phase 3 — install service + wizard:** Skills step in the Polaris wizard
   (browse, install, remove, update) backed by the install/update service
   (§5); tier badges in the capabilities view.
5.  **Phase 4 — later:** signed registry, per-skill update channels, optional
   skill "collections" (e.g. install the trader pack → several skills +
   variables at once), possibly developer tooling on top of the service API.

## 9. Non-goals (for this proposal)

- No sandboxing of optional skills: local-first means the user is the authority
  on their own machine (same posture as PR #12's review).
- No remote/dynamic loading of skill code at runtime beyond install-then-restart;
  discovery requires a restart today and that stays acceptable.
- No changes to the Nexus Apps model — it already serves the complex end of the
  spectrum.

## 10. Open questions

1. Should optional skills be able to declare a *minimum framework version*
   (enforced by the install service and surfaced in the wizard)? Probably yes,
   cheap to add to `registry.yaml` now.
2. Filesystem/import namespace collisions: the `user_`/`opt_` prefixes make
   capability-id collisions impossible by construction, but the Python import
   namespace needs care — `UserSkillProvider` puts its directory on `sys.path`
   and imports each namespace as a top-level package (the shadowing problem
   PR #12's scaffolder guards against, e.g. a `time/` directory shadowing the
   stdlib module). The optional-skills provider must apply the same guards
   (stdlib/installed-module check, `my<ns>` fallback or refusal).
3. Should `capabilities` views (LLM/full) mark optional skills so the LLM can
   say "this capability is available but not enabled — want me to install it?"
   when a user asks for something matching an uninstalled registry skill? This
   needs a lightweight, non-bloated mechanism (e.g. only names+descriptions of
   uninstalled registry skills, injected lazily).
4. Where does the **install/update service** live (the wizard's backend)?
   Orakle (owns skills/discovery, but Polaris talks to it through PyBridge
   middleware) vs. PyBridge (owns user-facing services like chat and STT/TTS).
   Note the user-facing CLI is intentionally out of scope — see §5.
