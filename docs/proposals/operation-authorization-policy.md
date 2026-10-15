# Proposal: Framework Operation Authorization Policy

**Status:** Draft — discussion and decision tracking in [Issue #18](https://github.com/khromalabs/ainara/issues/18); this document is the versioned record, with major decisions from the thread backported here.
**Author:** Rubén Gómez
**Date:** 2026-10-15
**Related:** Issue #18 (discussion), Issue #12 / PR #12 (skill builder — first consumer, interim static gate), Issue #17 (optional skills registry — curated vs. generated code may get different default postures)

---

## 1. Problem

Ainara increasingly has operations that are *powerful* rather than merely
convenient — code generation that writes files (skill builder, #12), future
capabilities that touch credentials, network uploads, system modification,
etc. Today there is no mechanism to decide, per user, whether such
operations require consent, are allowed by default, or are forbidden.

This originates from the PR #12 (skill builder) review walk-back: whether a
potentially insecure operation requires per-operation authorization, is
allowed by default, or is entirely restricted is a **user-level policy
decision**, not logic embedded in individual skills.

## 2. Failed alternatives (the case for a framework-level solution)

1. **Per-skill confirmation UX** — the original #12 review asked the
   skillbuilder for a dry-run-then-confirm flow. Withdrawn: it would be
   inconsistent (no other skill has it) and unskippable (no way to opt out
   of the friction). Whether an operation needs consent is a *user policy*,
   not skill logic.
2. **One static flag per skill** (`skills.builder.enabled: false`) —
   workable as an interim, but binary, per-skill, and duplicates policy
   logic across every skill that needs it.

## 3. Proposal: three user-chosen postures

A **core framework authorization/policy layer** that skills consult (or
that the framework enforces before executing a skill/operation) to decide
whether an operation may proceed. Three postures, chosen by the user —
fits the existing end-user/wizard philosophy: this is a
**wizard-configurable setting**, not a config-file-only toggle.

| Policy | Behavior |
|--------|----------|
| `prompt` | Sensitive operations ask for consent per operation (UI surface in Polaris; headless behavior: see open questions) |
| `allow_all` | Sensitive operations run without asking — for users who prefer zero friction |
| `restricted` | Listed operation classes are denied entirely |

Illustrative config shape (to be designed in the thread):

```yaml
security:
  policy: "prompt"          # "prompt" | "allow_all" | "restricted"
  restricted_operations:    # when policy: restricted
    - code_generation.write
    - credentials.read
  always_prompt:            # when policy: prompt, force prompting even if allowlisted
    - network.upload
```

## 4. What counts as "sensitive"

Operations that **write code or files outside ephemeral space, read
credentials/secrets, perform network uploads of local data, or modify
system state**.

Classification should be **declarative** (a skill/operation declares
`sensitivity: <class>` in metadata or the call site), so the policy applies
uniformly without each skill implementing anything — no per-skill
confirmation UX, ever.

## 5. First consumer: the skill builder (#12)

The skill builder is currently gated by the interim static flag
`skills.builder.enabled: false`. When this policy system lands, that flag
migrates to the policy layer (e.g. `code_generation.write` becomes a
sensitive operation class), and the enable-gate simplifies or disappears.

## 6. Open questions (tracked in #18)

- [ ] Enforcement point — Orakle's capability execution boundary (uniform,
      covers all skills) vs. opt-in per skill.
- [ ] Classification mechanism — skill metadata (`SKILL.md` front-matter?)
      vs. call-site declaration vs. a registry of operation classes.
- [ ] The `prompt` posture in headless contexts (Sentinel scheduler runs) —
      auto-deny, configurable default, or queue for the next interactive
      session.
- [ ] UI surface in Polaris: wizard setting + runtime consent dialog; how
      consent dialogs interact with the chat flow vs. background runs.
- [ ] Whether `opt_`/user-generated skill code (via the builder) gets a
      different default posture than reviewed curated skills.
- [ ] Migration path for `skills.builder.enabled` and any future per-skill
      flags.

## 7. Non-goals

- **No sandboxing** — local-first means the user is the authority on their
  own machine (recorded principle). This system is about *informed
  consent*, not containment.
- Not an authentication/identity system — single-user, local.
