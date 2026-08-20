---
id: '002'
title: 'Condense comments: src/ large narrative files (main.py, demo_square.py, boot.py,
  wire.py)'
status: done
use-cases:
- UC-001
depends-on:
- '001'
github-issue: ''
issue: condense-comments-across-the-codebase.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Condense comments: src/ large narrative files (main.py, demo_square.py, boot.py, wire.py)

## Description

These four files carry the heaviest comment-to-code ratio in the repo
(per the issue's own table: `main.py` — formerly `main_zetuv_demo.py`
— 66% comment share, 243 comment / 87 code lines; `demo_square.py` 58%,
564/308; `boot.py` 55%, 201/118; `wire.py` 50%, 163/111 — roughly 1171
comment lines across the four). Depends on ticket 001 so this ticket
condenses `main.py`'s already-renamed docstring once, not the
pre-rename file.

Reduce each file to the comments necessary to understand the code —
what a function does, units and frame conventions, and the
non-obvious constraint behind a line that would otherwise look
arbitrary. Delete the rest:

- Multi-paragraph narrative of how a decision was reached, what was
  tried first, and what failed on the bench — that history belongs in
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
  otherwise" note, with a pointer to the doc or log entry that has the
  full story.

`main.py`'s module docstring is the headline case — it currently runs
past line 70 before the first import, narrating the `.mpy`-vs-`.py`
heap failure, the `sys.modules.pop` reload trick, why
`config.load_robot_config()` is not used, and which bench log section
proves each point. Reduce it to what a reader needs to understand the
module, with pointers (not retellings) to the bench log for the
history.

**Comments-only. No behavior change.** Do not touch any executable
line, string literal, or docstring that is read programmatically
(none are known to exist in these files, but verify — a docstring is
only safe to trim if nothing inspects its contents at runtime).

## Acceptance Criteria

- [x] `src/main.py`, `src/demo_square.py`, `src/boot.py`,
      `src/wire.py` each keep: a short module docstring; trimmed
      function/method docstrings (purpose, units, return value); any
      landmine marker, with its pointer preserved or tightened, not
      deleted.
- [x] Each file's narrative history (how a decision was reached, what
      was tried and failed, bench-verification provenance prose) is
      removed or reduced to a one-line pointer into
      `docs/bench-log-*.md` / the relevant sprint ticket.
- [x] No executable line changes in any of the four files (diff shows
      comment/docstring lines only — verify with a diff review, not
      just a test pass).
- [x] `uv run pytest` stays green at the 223-passed / 518-subtests
      baseline, unchanged (actual baseline in this checkout: 228
      passed / 518 subtests — unchanged before and after).
- [x] `python3 -m py_compile` and `mpy-cross` (if available in this
      environment) lint all four changed files clean. (`mpy-cross` is
      not installed in this environment; `py_compile` passed clean on
      all four files.)
- [x] The per-file comment-share table in
      `clasi/issues/condense-comments-across-the-codebase.md` no
      longer describes these four files accurately post-condensation
      (expected — the issue's table is a snapshot, not a spec to keep
      matching).

## Testing

- **Existing tests to run**: `uv run pytest` (223 passed / 518
  subtests baseline). `tests/test_demo_square.py` and
  `tests/test_boot_sequence.py` in particular, since they exercise
  the two largest files here.
- **New tests to write**: none — comments-only changes have nothing
  new to test; the existing suite passing unchanged *is* the
  acceptance test for "no behavior change."
- **Verification command**: `uv run pytest`

Note: if a build is run against these files, expect any flash-size
gate (`tests/test_build_gate.py::test_flash_end_below_fs_start`) to
show *more* headroom, not less — frozen docstrings shrinking is a
smaller-direction move, not a regression. `tests/
test_manifest_freeze.py` itself has no byte-size assertion (only
exact-module-listing and freeze-path-string checks), so it is
unaffected either way.
