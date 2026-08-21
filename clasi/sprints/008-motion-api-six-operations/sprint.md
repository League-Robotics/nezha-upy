---
id: 008
title: "Motion API \u2014 six operations"
status: roadmap
branch: sprint/008-motion-api-six-operations
worktree: false
use-cases: []
issues:
- motion-api-six-operations.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 008: Motion API — six operations

## Goals

Rebuild a MOVE-capable motion API on top of the v6 line protocol
(sprint 007): implement all **six** operations from
`radio-robot-lib/docs/design/motion-api.md` — `wheels_x`, `wheels_v`,
`move_x`, `move_v`, `go_to_r`, `go_to_w` — not just the two
primitives, per stakeholder decision (2026-08-21). This is a roadmap
placeholder only; full architecture, use cases, and tickets are
deferred to Detail Mode, run after sprint 007 closes.

## Problem

- `motion.py`'s `MoveQueue`/`Move`/generator-mode and
  `demo_square._move()`'s tuned loop are two independent, forked
  implementations of "move the robot a bounded amount" — prior art,
  not the target shape (see issue
  `move-engine-forked-between-demo-square-and-tour-run.md`, not
  claimed by this sprint but named here as the fork this work is the
  natural point to end).
- The v5-shaped `MOVE`/`GO_TO` verbs retire with sprint 007's hard
  cutover and are not rebuilt there (out of scope for that sprint by
  design — v6's verb scope there is deliberately limited to
  `HELLO PING ID VER STATUS HELP GET SET TLM WHEELS STOP ESTOP`).
  Six new wire verbs (`WHEELS_X`, `WHEELS_V`, `MOVE_X`, `MOVE_V`,
  `GO_TO_R`, `GO_TO_W`) and their adapter methods are needed to
  restore (and generalize) that capability.

## Solution (sketch — not detailed here)

Per `motion-api.md` §2: every one of the six operations is one or
more constant-ratio wheel segments, each bounded by a displacement or
a time; the four body/position forms are coordinate changes over
`wheels_x`/`wheels_v`. Build the two primitives and the segment/
profiler machinery first, then compose the rest. Three execution
modes (fiber-driven, caller-iterated/generator, blocking-with-
callback) share one post/tick contract. Full breakdown — module
responsibilities, diagrams, design rationale, use cases, and
tickets — happens at Detail Mode time, not here.

## Dependency

**Requires sprint 007 (v6 line protocol cutover + WiFi bring-up on
tovez) closed first.** The six new verbs are v6 adapter methods
(`motion-api.md` §9) — there is no v5 wire form for any of them, and
building this sprint's adapter surface against a protocol handler
that doesn't exist yet is not viable. Do not detail-plan or open this
sprint before sprint 007's status is `closed`.

## Scope (sketch)

- In scope (at Detail Mode time): `wheels_x`, `wheels_v`, `move_x`,
  `move_v`, `go_to_r`, `go_to_w`; the segment/profiler engine
  underneath them; three execution modes; six new wire verbs +
  adapter methods; kinematic-translation unit tests; the 50° pivot
  threshold; wheel-swap sign test; odometry epoch/unwrap handling;
  hardware acceptance on tovez (`move_x(400, 0)`, `move_x(0, 90)`,
  square tour vs. `demo_square`'s numbers).
- Out of scope: the vendored `DiffDrive` kernel (untouched —
  everything lands above `diffdrive.drive/step/neutral/estop`);
  ending the `demo_square`/`tour_run` fork itself (named in Problem
  as context, not claimed — that is
  `move-engine-forked-between-demo-square-and-tour-run.md`'s own
  issue, not linked to this sprint); any v5 protocol work (retired by
  sprint 007, not revisited here).

## Design authority

`radio-robot-lib/docs/design/motion-api.md` — the full six-operation
spec, the segment/profile model, the 50° pivot rule, `go_to_r`'s
supervisory re-solve policy, and the three-mode execution contract.
Read it in full at Detail Mode time; this roadmap entry deliberately
does not restate it.

## Architecture

(Deferred — Detail Mode only, after sprint 007 closes. Not written
for a roadmap-phase sprint.)

## Use Cases

(Deferred — Detail Mode only, after sprint 007 closes. Not written
for a roadmap-phase sprint.)

## GitHub Issues

(GitHub issues linked to this sprint's tickets. Format: `owner/repo#N`.)

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [ ] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [ ] Architecture review passed (or skipped, for changes with no
      architectural impact)
- [ ] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On |
|---|-------|------------|

Tickets execute serially in the order listed.
