---
id: '003'
title: 'Condense comments: src/ remaining modules (config, msgs, line, otos, radio_shim,
  motion, telemetry, comms, wifi_at, demo_util)'
status: done
use-cases:
- UC-001
depends-on: []
github-issue: ''
issue: condense-comments-across-the-codebase.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Condense comments: src/ remaining modules (config, msgs, line, otos, radio_shim, motion, telemetry, comms, wifi_at, demo_util)

## Description

The remaining `src/` framework modules, per the issue's table:
`config.py` (43%, 196/206), `msgs.py` (44%, 51/47), `line.py` (38%,
51/58), `otos.py` (36%, 60/80), `radio_shim.py` (36%, 88/123),
`motion.py` (33%, 167/270), `telemetry.py` (29%, 71/145), `comms.py`
(29%, 244/488), `wifi_at.py` (25%, 216/550) — plus `demo_util.py`
(not in the issue's table but part of `src/`, not covered by ticket
002). Roughly 1144+ comment lines total. Disjoint from ticket 001's
touched files (no rename references land in any of these), so this
ticket has no file-level dependency and may run independently of
ticket 001/002.

Apply the same condensation discipline as ticket 002 (see that
ticket's Description for the full cut/keep list — narrative history
and provenance prose out, short module docstrings and trimmed
function docstrings and landmine markers in).

**`motion.py` gets no functional changes here** — this ticket is
comments-only. Ticket 007 (later, depends on this ticket) adds the
new generator-based move functions; sequencing this condensation
ticket first means ticket 007 edits an already-condensed file instead
of fighting an in-flight docstring rewrite.

**Comments-only. No behavior change.** `msgs.py` and `wire.py`-derived
modules in particular carry protocol-contract comments (verb payload
shapes, field offsets) — these are the "non-obvious constraint" kind
that must be *kept*, not narrative to cut. Read each comment before
deleting it; do not bulk-strip by pattern alone.

## Acceptance Criteria

- [x] All ten files (`config.py`, `msgs.py`, `line.py`, `otos.py`,
      `radio_shim.py`, `motion.py`, `telemetry.py`, `comms.py`,
      `wifi_at.py`, `demo_util.py`) keep: a short module docstring;
      trimmed function/method docstrings; every landmine marker
      (e.g. `motion.py`'s "every duration is milliseconds" L4
      regression-risk note; `comms.py`'s dispatch-order comments) and
      every wire/protocol-contract comment (verb payload shapes,
      field offsets, units) — these are load-bearing, not narrative.
- [x] Narrative history, provenance prose, and restated-next-line
      comments are removed or reduced to one-line pointers.
- [x] No executable line changes in any of the ten files.
- [x] `uv run pytest` stays green at the 223-passed / 518-subtests
      baseline, unchanged — in particular `tests/test_motion.py`,
      `tests/test_comms_loopback.py`, `tests/test_wifi_at.py`,
      `tests/test_telemetry.py`, `tests/test_otos.py`,
      `tests/test_line.py`, `tests/test_config.py`,
      `tests/test_radio_shim_fragments.py` all pass unmodified.
- [x] `python3 -m py_compile` and `mpy-cross` (if available) lint all
      ten changed files clean.

## Testing

- **Existing tests to run**: `uv run pytest` (223 passed / 518
  subtests baseline) — the full suite, since these ten modules are
  exercised by the majority of `tests/*.py`.
- **New tests to write**: none — comments-only.
- **Verification command**: `uv run pytest`
