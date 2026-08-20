---
status: done
sprint: '006'
tickets:
- 006-002
- 006-003
- 006-004
- 006-005
- 006-010
---

# Condense the comments across the codebase

Comments have grown to the point where they crowd out the code. 3567
of 11201 lines (32%) across `src/`, `native/`, `tests/`, and
`patches/` are comment or docstring lines, and in the worst files the
comments outnumber the code two-to-one. Strip them back to only what
is needed to understand what the code does.

## Symptom

Per-file comment share (comment lines / code lines / total):

| file | cmt% | cmt | code | total |
| --- | ---: | ---: | ---: | ---: |
| `src/main_zetuv_demo.py` | 66% | 243 | 87 | 366 |
| `src/demo_square.py` | 58% | 564 | 308 | 971 |
| `src/boot.py` | 55% | 201 | 118 | 363 |
| `src/wire.py` | 50% | 163 | 111 | 323 |
| `src/config.py` | 43% | 196 | 206 | 460 |
| `src/msgs.py` | 44% | 51 | 47 | 115 |
| `src/line.py` | 38% | 51 | 58 | 133 |
| `src/otos.py` | 36% | 60 | 80 | 168 |
| `src/radio_shim.py` | 36% | 88 | 123 | 247 |
| `src/motion.py` | 33% | 167 | 270 | 511 |
| `src/telemetry.py` | 29% | 71 | 145 | 242 |
| `src/comms.py` | 29% | 244 | 488 | 845 |
| `src/wifi_at.py` | 25% | 216 | 550 | 865 |
| `native/moddiffdrive.cpp` | 24% | 117 | 332 | 489 |
| `native/wifi_uart_fwd.h` | 68% | 72 | 20 | 106 |
| several small `native/hal/*.h` | 42–73% | | | |

`src/main_zetuv_demo.py` is the headline case and is effectively
unreadable: its module docstring alone runs past line 70 before the
first import, narrating the `.mpy`-vs-`.py` heap failure, the
`sys.modules.pop` reload trick, why `config.load_robot_config()` is
not used, and which bench log section proves each point.

## What to do

Reduce each file to the comments necessary to understand the code —
what a function does, units and frame conventions, and the
non-obvious constraint behind a line that would otherwise look
arbitrary. Delete the rest.

Cut:

- Multi-paragraph narrative of how a decision was reached, what was
  tried first, and what failed on the bench. That history belongs in
  `docs/bench-log-*.md` and the sprint tickets, which already carry
  it; a one-line pointer replaces pages of retelling.
- Citations of ticket/sprint/UC ids, "bench-verified this ticket",
  "probed directly this session, not assumed", and similar
  provenance-assertion prose.
- Restatement of what the next line plainly says.
- Explanations of standard Python/MicroPython or CODAL semantics.

Keep:

- A short module docstring: what the module is for, one or two lines.
- Function/method docstrings stating purpose, parameters with units,
  and return value — trimmed to a couple of lines each.
- Landmine markers: the single-line "this is here because X breaks
  otherwise" note, with a pointer to the doc or log entry that has
  the full story.
- Units in `// [unit]` trailing comments on the C/C++ side, per
  `CLAUDE.md` style.

## Constraints

- `vendor/` is synced from radio-robot and must not be touched.
- Comments-only edits: no behaviour change. The test suite must pass
  unchanged afterward, and the frozen-manifest size checks in
  `tests/test_manifest_freeze.py` should only move in the smaller
  direction (docstrings are frozen into the image, so this shrinks
  it).
- `tests/` is included in the sweep, but test docstrings that state
  what a test asserts are the useful kind — trim the narrative, keep
  the assertion statement.
- Reference material under `reference/` is copied from elsewhere;
  leave it alone.

Related: [[rename-main-zetuv-demo-to-main]] touches the same file and
should land in the same pass to avoid conflicting rewrites.
