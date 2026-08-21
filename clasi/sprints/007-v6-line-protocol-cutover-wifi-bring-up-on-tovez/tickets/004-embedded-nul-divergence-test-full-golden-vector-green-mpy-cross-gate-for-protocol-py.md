---
id: '004'
title: Embedded-NUL divergence test, full golden-vector green, mpy-cross gate for
  protocol.py
status: done
use-cases:
- SUC-005
depends-on:
- '003'
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Embedded-NUL divergence test, full golden-vector green, mpy-cross gate for protocol.py

## Description

Close out the handler-only portion of Track A: confirm the full
`protocol_golden_vectors.txt` fixture passes end to end (every
applicable vector, across all verb families from tickets 001–003),
pin the one deliberate divergence from the C++ archetype, and add the
`mpy-cross` compile gate for the new module.

**Embedded-NUL divergence** (`protocol.md` §9.4's characterization
finding, issue item 3): the C++ handler's `strcmp()`-based verb
lookup stops at the first NUL, so `PING\0extra` compares equal to
`"PING"` and dispatches as a bare `PING` — a characterization
artifact of C-string comparison, not grammar-correct (the grammar's
`verb ::= [A-Za-z][A-Za-z0-9_]*` admits no NUL at all). Python
`bytes`/`str` comparisons are length-aware, so this port naturally
does the grammar-correct thing: reject a NUL-embedded verb rather
than silently truncating and matching it. Write
`test_embedded_nul_immediately_after_verb_is_rejected_not_truncated`
(or similar) asserting `feed(b"PING\x00extra\n")` does **not**
dispatch as `PING` — it should count malformed (no recoverable `#id`
in this example) rather than reply `pong <now>`. This is a
**divergence test pinning correct Python behavior**, not a port of
the C++ characterization test — do not reproduce the C++ bug.

**Full-fixture pass**: run the complete
`tests/fixtures/protocol_golden_vectors.txt` through the harness and
confirm every vector not specific to C++-only behavior (i.e.,
excluding the embedded-NUL case, which gets the divergence test
above instead) passes.

**mpy-cross gate**: add `src/core/protocol.py` (and, once it exists,
`src/hardware/protocol_adapter.py` — ticket 005 lands after this one,
so wire the gate to pick up new modules by glob/manifest rather than
a hardcoded file list) to whatever `mpy-cross` lint step this repo
already runs (see `tests/test_build_gate.py` / existing `py_compile`+
`mpy-cross` convention referenced in `docs/bench-acceptance-procedures.md`
§A.0).

## Acceptance Criteria

- [x] Full `protocol_golden_vectors.txt` fixture green through the
      harness (every applicable vector; C++-only vectors identified
      and excluded with a comment explaining why, not silently
      skipped).
- [x] Embedded-NUL divergence test written and passing, with a
      docstring/comment explicitly contrasting it with the C++
      characterization bug it deliberately does NOT reproduce.
- [x] `mpy-cross` compiles `src/core/protocol.py` cleanly as part of
      the offline gate.
- [x] `python3 -m pytest tests/` fully green.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (tickets
  001–003's full suite).
- **New tests to write**: full-fixture pass-through test; embedded-NUL
  divergence test; `mpy-cross` compile check (as a test or a Makefile/
  script step this repo's existing gate already has a place for).
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: This is primarily a verification/closing ticket, not
new feature surface — if the full-fixture pass surfaces a gap missed
by tickets 001–003's incremental vector coverage, fix it here rather
than reopening an earlier ticket (the earlier tickets' own acceptance
criteria were scoped to their own verb families; a cross-family
interaction bug belongs to whichever ticket completes full coverage,
which is this one).

**Files to modify**:
- `src/core/protocol.py` — any fixes surfaced by the full-fixture
  pass.
- `tests/unit/test_protocol_golden_vectors.py` — the full-pass
  assertion, embedded-NUL divergence test.
- The repo's existing `mpy-cross`/`py_compile` gate (wherever
  `tests/test_build_gate.py` or an equivalent script enumerates
  modules to lint) — add `src/core/protocol.py`.

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket.
