---
id: '001'
title: Golden-vector harness + protocol handler core (feed/tokenizer/dispatch, malformed-line
  + ESTOP-exception recovery, session verbs)
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-005
depends-on: []
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Golden-vector harness + protocol handler core (feed/tokenizer/dispatch, malformed-line + ESTOP-exception recovery, session verbs)

## Description

Lay the foundation for the entire v6 protocol port: copy the
cross-language conformance fixture, build the CPython harness that
drives it, and implement enough of `src/core/protocol.py` to make the
session-verb and malformed-line vectors pass. Every later ticket in
this sprint's Track A extends this same handler and harness.

Port from `radio-robot-lib/src/protocol/protocol_handler.{h,cpp}`
(read the file headers first — they document every ambiguity this
file already resolved, so don't re-derive them) and
`radio-robot-lib/tests/protocol/test_protocol_harness.py` (the C++
side's own harness — read its SETUP/IN/OUT block runner and its
`RESULT_*` ordinal map; port the *shape* of the runner, not its
C++-specific plumbing).

Grammar to implement this ticket (`protocol.md` §2/§2.1/§2.2/§2.3/§3):
- `line ::= sp? verb (sp field)* sp? '\n'`; a run of spaces is one
  separator; leading/trailing whitespace ignored; a blank/whitespace-only
  line is ignored silently (not malformed).
- Case is direction: verb lookup is case-sensitive; a lowercase-led
  line is another robot's reply and is dropped silently, NOT counted
  malformed.
- Trailing `#<n>` id: digits-only (`#+5`/`#-5`/`# 5` are all
  malformed — needs its own digit-only scan, not the general integer
  parser).
- Malformed-line recovery: unknown verb / wrong arity / unparseable
  field → count malformed; if the line's raw last token is a
  well-formed nonzero `#id`, reply `err #<id> <code>`, else no reply.
  `ESTOP` is the one exception and wins even when malformed: never
  any reply, ever.
- `feed()` must survive: several complete lines in one block; a block
  ending mid-line (buffer the remainder); a block that's only a
  fragment; a lone `\r` before `\n` stripped (never elsewhere); a line
  over the 240-byte max discarded to the next `\n` and counted
  malformed (never truncated into something that parses).
- Session verbs this ticket implements: `HELLO` (`device NEZHA2 robot
  <name> <serial>`), `PING` (`pong <now>`), `ID` (`id <drivetrain>
  <profile> <version>`), `VER` (`ver <version>`), `STATUS` (`status
  ready=1 active=0 connL=1 connR=1 otos=0 wedge=0 flags=<hex>
  tlm=off`), `HELP` (`help HELLO PING ID VER STATUS HELP GET SET TLM
  WHEELS STOP ESTOP` — generated from the same dispatch table, so it
  cannot drift). `GET`/`SET`/`TLM`/`WHEELS`/`STOP` are dispatched to
  as unknown-but-well-formed verb NAMES only in this ticket (full
  bodies land in tickets 002/003) — `HELP`'s text must still list all
  of them.

The `Adapter`/`Sink`/`Result` seam (`protocol.md` §4) is defined in
this ticket as a small interface (duck-typed, no ABC — MicroPython
has no `abc` module) with a mock implementation for the harness only;
the real `ProtocolAdapter` is ticket 005.

## Acceptance Criteria

- [x] `tests/fixtures/protocol_golden_vectors.txt` exists, copied
      verbatim from `radio-robot-lib/tests/protocol/golden_vectors.txt`.
- [x] A CPython harness (e.g. `tests/unit/test_protocol_golden_vectors.py`
      + a small `_protocol_fixture.py` block parser) parses every
      SETUP/IN/OUT block in the fixture into a runnable list with zero
      parse errors — asserted independently of whether the handler
      exists yet, i.e. block-count and structural parsing are tested
      first against the raw fixture text.
- [x] `src/core/protocol.py` exists with `ProtocolHandler.feed()`,
      the tokenizer, dispatch skeleton, and `HELLO`/`PING`/`ID`/`VER`/
      `STATUS`/`HELP` fully implemented.
- [x] Every golden vector for session verbs and for malformed-line /
      `ESTOP`-exception recovery passes through the harness with a
      mock adapter.
- [x] `feed()`'s robustness list (multi-line block, mid-line split
      across two `feed()` calls, overlong-line discard, blank-line
      silence, lowercase-verb silent drop) each has an explicit test,
      not just fixture coverage.
- [x] `HELP`'s reply text is generated from the same verb table
      `dispatch()` uses (a test asserting they can't drift is
      sufficient — no need to hand-duplicate the string).
- [x] No MicroPython-incompatible syntax (no f-strings, no PEP 604/
      generic-subscript hints, no host-only stdlib) — `py_compile`
      clean.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (full suite,
  confirm no regression — this ticket adds files, doesn't touch
  existing ones yet).
- **New tests to write**: the golden-vector harness itself (block
  parser + runner); `feed()` robustness unit tests (multi-line,
  split-mid-line, overflow, blank-line, lowercase-drop); malformed-line
  `#id` recovery tests (well-formed recoverable id, non-recoverable
  cases, `ESTOP`-wins-even-when-malformed); `HELP`-text-matches-table
  test.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Read `protocol_handler.h`'s file header first (it
documents every ambiguity — the malformed-`#id`-recovery/`ESTOP`
collision, the id's stricter digit-only grammar, RUN's open arity —
already resolved; don't re-litigate them). Build the harness against
the raw fixture text before writing any handler code, so ticket
review can confirm the fixture parses correctly independent of the
port. Then implement `feed()`/tokenizer/dispatch and the six session
verbs, running the harness after each verb to catch regressions
early.

**Files to create**:
- `src/core/protocol.py` — `ProtocolHandler`, `Sink`, `Result` (as
  much of the enum as session verbs need — full table lands ticket
  002), the mock-adapter-facing dispatch skeleton.
- `tests/fixtures/protocol_golden_vectors.txt` — copied fixture.
- `tests/unit/test_protocol_golden_vectors.py` (or similar) — harness
  + session-verb/malformed-line test cases.
- A small mock adapter for the harness (port the shape of
  `radio-robot-lib`'s `mock_adapter.h` / the C++ harness's own mock,
  not its C++ specifics).

**Files to modify**: none (purely additive — `wire.py`/`msgs.py`/
`comms.py`/`motion.py` are untouched until ticket 006).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket (the sprint-level doc
update lands in ticket 006, once the cutover is real).
