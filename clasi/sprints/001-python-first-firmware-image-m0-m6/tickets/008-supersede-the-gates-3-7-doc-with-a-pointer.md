---
id: 008
title: Supersede the gates-3-7 doc with a pointer
status: done
use-cases: []
depends-on: []
github-issue: ''
issue: incorporate-nezha-upy-review-into-main-design-document.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Supersede the gates-3-7 doc with a pointer

## Description

This ticket has no dedicated use case in `docs/design/usecases.md` —
it is process/documentation housekeeping that directly implements
issue `incorporate-nezha-upy-review-into-main-design-document.md`
rather than a functional use case. This is a stated, deliberate
exception (see sprint.md's Use Cases section).

Add an explicit supersession banner to the top of
`docs/micropython-full-firmware-in-the-image-gates-3-7.md`, stating it
is superseded as architecture by `docs/design/specification.md` (per
the stakeholder's 2026-08-19 decision) and pointing to
`specification.md` §8 for the constraints it carries forward.
`docs/design/overview.md` and `specification.md` already describe the
gates-3-7 doc as superseded — verify those existing references resolve
correctly and are not stale; add a reciprocal link from the gates-3-7
doc back to `specification.md` if one doesn't already exist.

Close the loop on issue 4's original request ("capture any
architecture, risks, gaps, recommendations, or validation notes from
the review that should live in the main design document"): confirm all
four `docs/nezha-upy-review.md` findings (heap-corruption mechanism
closed, starvation/polling-idiom case, fiber-exit design, mpy-cross-is-
lint) are represented in `specification.md` §7 — they already are, per
this sprint's own read of both documents during planning — and record
that confirmation in this ticket rather than re-authoring content that
already exists.

## Acceptance Criteria

- [x] `docs/micropython-full-firmware-in-the-image-gates-3-7.md` opens
      with a clearly marked supersession banner naming
      `docs/design/specification.md` as authoritative and
      `specification.md` §8 as where its carried-over constraints live.
- [x] `docs/design/specification.md` and `docs/design/overview.md`
      both link to the gates-3-7 doc and those links resolve (relative
      path check) — verify existing links rather than assuming.
- [x] The gates-3-7 doc links back to `specification.md`.
- [x] A short confirmation note (in this ticket, or a one-line
      changelog entry) records that all four `nezha-upy-review.md`
      findings are represented in `specification.md` §7 — a
      traceability check, not new authoring.
- [x] No content is duplicated between the two docs beyond the
      existing carried-over-constraints summary already in
      `specification.md` §8.

## Verification notes (recorded during execution)

- **Existing links checked, not stale.** `docs/design/overview.md`
  "Governing documents" (lines 42–45) and `docs/design/specification.md`
  header (lines 3–9) and §8 heading (line 316) already reference
  `docs/micropython-full-firmware-in-the-image-gates-3-7.md` by
  repo-root-relative path; both paths exist on disk (verified by direct
  file-existence check). No edit was needed to either file.
- **Reciprocal link added.** The gates-3-7 doc did not previously link
  back to `specification.md`; the new banner adds that pointer plus a
  pointer to `PLAN.md` and `docs/design/overview.md`.
- **Traceability confirmation — the four `nezha-upy-review.md` findings
  map onto `specification.md` §7 as follows** (verified by reading both
  documents in full during this ticket):
  1. Heap-corruption mechanism (CODAL shared-stack + in-switch
     malloc/free; hook question permanently closed) → §7.1.
  2. Starvation is a control gap; realistic trigger is the
     `radio.receive()` polling idiom, not the busy-wait; watchdog must
     be visible → §7.2.
  3. Fiber-exit design (`step()` as a re-entrant non-blocking state
     machine off a pended SWI) if M1's safety gate reads badly → §7.3.
  4. `mpy-cross` compiles as a lint only, not a load-path proof (this
     port cannot load `.mpy` from the filesystem); module shipping is
     `manifest.py` freezing → §7.4.

  All four are represented; no re-authoring was needed.
- **No duplication introduced.** The two new banners are pointers
  (a few sentences each), not restatements of content — the
  carried-over-constraints summary already lives solely in
  `specification.md` §8, and the findings summary already lives solely
  in `specification.md` §7.

## Testing

- **Existing tests to run**: none (doc-only ticket).
- **New tests to write**: none; verification is a manual
  cross-reference read plus a relative-link resolution check (confirm
  every linked path in the touched docs exists on disk).
- **Verification command**: none applicable — this is a documentation
  ticket with no automated test suite; the acceptance criteria above
  are the gate.

## Implementation Plan

**Approach**: doc-only edits. Read both documents fully, add the
banner and cross-links, verify path resolution.

**Files to create/modify**:
`docs/micropython-full-firmware-in-the-image-gates-3-7.md`, and
`docs/design/specification.md`/`docs/design/overview.md` only if a
link is found missing or stale.

**Testing plan**: manual read-through plus link-path existence check.

**Documentation updates**: this ticket *is* the documentation update.
