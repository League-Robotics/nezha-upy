---
id: '003'
title: 'Protocol handler: WHEELS/STOP/ESTOP verbs + telemetry emission (thdr/t, header-change
  detection)'
status: open
use-cases: [SUC-001, SUC-002, SUC-004]
depends-on: ['002']
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Protocol handler: WHEELS/STOP/ESTOP verbs + telemetry emission (thdr/t, header-change detection)

## Description

Complete `src/core/protocol.py`'s verb scope with `WHEELS`, `STOP`,
`ESTOP`, and add unsolicited telemetry emission (`emitTelemetry()`).
This ticket implements the handler side only — the real kernel/config
plumbing behind these verbs is `ProtocolAdapter` (ticket 005); here,
the golden-vector harness's mock adapter stands in.

- `WHEELS left right duration [#id]` → `ok [#id]` / `err [#id]
  <code>`. Id is **optional**; `#0` legal (executes silently, no
  reply). Values are ordinary signed numeric fields (this ticket's
  parser, from ticket 002, already guards whitespace/underscore).
- `STOP #id` → `ok #<id>` / `err #<id> <code>`. Id is **required**;
  `#0` on `STOP` is itself malformed (distinct from `WHEELS`/`SET`,
  where it's legal) — needs its own test, since it's the one place
  in this verb scope where `#0`'s legality flips.
- `ESTOP` → **never any reply**, well-formed or malformed alike —
  already partially covered by ticket 001's malformed-recovery tests;
  this ticket adds the well-formed-`ESTOP`-produces-nothing case and
  confirms the two paths (well-formed vs. malformed) both land on
  "no reply" for the same underlying reason (§2.3's carve-out), not
  by coincidence of two different code paths.
- `emitTelemetry(snapshot)`: `thdr <col1> <col2> ...` once, and again
  whenever the column set changes; `t <v1> <v2> ...` every call
  after. Header-change detection is **per-handler-instance** state
  (see sprint.md's Design Rationale on one-handler-per-transport) —
  this ticket's tests should include two independent handler
  instances receiving different column sets and confirm neither's
  `headerNames_`-equivalent state leaks into the other.

## Acceptance Criteria

- [ ] `WHEELS`/`STOP`/`ESTOP` implemented, dispatched through the
      shared tokenizer/dispatch core.
- [ ] `emitTelemetry()` implemented with `thdr`-once / `thdr`-again-
      on-column-change / `t`-every-call semantics.
- [ ] Golden-vector harness green for every `WHEELS`/`STOP`/`ESTOP`/
      telemetry vector, including the multi-frame TLM vector (`thdr`
      once, `t` repeating across several `EMIT` actions in one
      block).
- [ ] Explicit tests: `STOP #0` is malformed (required-id verb);
      `WHEELS ... #0` executes silently (optional-id verb) — same
      token, opposite legality, both tested; well-formed `ESTOP`
      produces no reply (sink empty); two independent handler
      instances' telemetry-header state don't cross-contaminate.
- [ ] `py_compile` clean; no MicroPython-incompatible syntax.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/`
- **New tests to write**: WHEELS/STOP/ESTOP golden-vector cases;
  `#0`-legality-flip test (`STOP` vs. `WHEELS`); well-formed-ESTOP-
  silent test; telemetry thdr/t sequencing test; per-handler-instance
  header-state isolation test.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: `STOP`/`WHEELS` share the numeric-field parser from
ticket 002 but differ in id-required-ness — implement id handling as
a small shared helper parameterized by "required"/"optional", not two
copies. `emitTelemetry()`'s header-change detection is a small piece
of per-instance state (a remembered column-name list), matching the
C++ archetype's `headerNames_`/`headerHex_`/`everEmittedHeader_`
fields — port the shape, not the fixed-array sizing (Python has no
`kMaxHeaderColumns` constraint).

**Files to modify**:
- `src/core/protocol.py` — add `WHEELS`/`STOP`/`ESTOP` handlers,
  `emitTelemetry()`, header-change state.
- `tests/unit/test_protocol_golden_vectors.py` — extend with this
  ticket's vectors/cases.

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket.
