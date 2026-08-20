---
id: '001'
title: Rename src/main_zetuv_demo.py to src/main.py
status: done
use-cases:
- UC-002
depends-on: []
github-issue: ''
issue: rename-main-zetuv-demo-to-main.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Rename src/main_zetuv_demo.py to src/main.py

## Description

The on-device student-code entry point is stored in the repo as
`src/main_zetuv_demo.py` but is deployed to the device filesystem as
`main.py`. Rename it to match what it actually is, and update every
reference. This ticket lands **before** any comment-condensation
ticket touches the same file, so a full docstring rewrite (ticket 002)
happens once, on the already-renamed file — not twice, unsequenced.

This is a mechanical rename plus reference updates only. Do **not**
attempt to condense this file's docstring beyond fixing the
name-identifying sentences below — that is ticket 002's job, on the
same file, next.

Steps:

1. `git mv src/main_zetuv_demo.py src/main.py`.
2. `manifest.py:58` — update the comment mentioning the file by its
   old name (`"src/main_zetuv_demo.py) call demo_square.run()..."` →
   `src/main.py`).
3. `tests/test_manifest_freeze.py` — update:
   - Line ~38: `_BENCH_ONLY_MODULES = {"main_zetuv_demo.py"}` →
     `_BENCH_ONLY_MODULES = {"main.py"}`. **Keep the guard** — do not
     remove it. This is the hard constraint: `mp_main()` probes the
     device *filesystem* for `main.py`; a frozen module literally
     named `main` would never be found by `mp_main()`'s
     filesystem-only probe, so `src/main.py` must stay OUT of
     `manifest.py`'s freeze list.
   - The docstring prose (lines ~12, ~21) that names
     `main_zetuv_demo.py` — update to `main.py`, preserving the
     surrounding explanation of why the exclusion exists.
4. `src/demo_square.py:331` and `:966` — update the two comment
   references to `src/main_zetuv_demo.py` → `src/main.py`.
5. `src/main.py`'s own module docstring — fix only the
   name-identifying sentences (it currently explains "this copy under
   `src/main_zetuv_demo.py` exists purely for version control" and
   references `mpremote ... fs cp src/main_zetuv_demo.py :main.py`).
   Update these to the new filename. Do not otherwise rewrite or
   condense the docstring — that is ticket 002's scope, immediately
   after this ticket.
6. `docs/bench-log-zetuv-2026-08-19.md` — this is a historical log;
   do **not** rewrite existing entries. Add one new entry noting the
   rename (repo-side only — no bench/hardware action).
7. Search for any deploy command of the form `mpremote ... fs cp
   src/main_zetuv_demo.py :main.py` in docs/scripts and update it to
   `src/main.py`.

## Acceptance Criteria

- [x] `src/main_zetuv_demo.py` no longer exists; `src/main.py` exists
      (via `git mv`, preserving history).
- [x] `manifest.py:58`'s comment reference is updated; `src/main.py`
      is confirmed **absent** from `manifest.py`'s `freeze()` call
      (grep check, not just visual inspection).
- [x] `tests/test_manifest_freeze.py`'s `_BENCH_ONLY_MODULES` is
      `{"main.py"}`; its docstring prose no longer names the old
      filename; the guard itself is unchanged in behavior (still
      excludes exactly one bench-only module from the freeze-list
      check, now under the new name).
- [x] `src/demo_square.py:331` and `:966` reference `src/main.py`, not
      the old name.
- [x] `src/main.py`'s module docstring no longer references
      `main_zetuv_demo.py` anywhere (name-identifying sentences only —
      full condensation is out of scope here).
- [x] `docs/bench-log-zetuv-2026-08-19.md` has a new entry noting the
      rename; no existing entry's text is altered.
- [x] No remaining reference to `main_zetuv_demo` anywhere in the repo
      (`grep -rn main_zetuv_demo .` returns nothing outside `.git/`
      and this ticket's own sprint files).

## Testing

- **Existing tests to run**: `uv run pytest` (223 passed / 518
  subtests baseline) — must stay green, unchanged. In particular
  `tests/test_manifest_freeze.py` (both
  `test_manifest_lists_exactly_the_src_py_modules` and the exclusion
  behavior) must pass with the renamed file.
- **New tests to write**: none — this is a rename plus reference
  updates, not new behavior. `test_manifest_freeze.py`'s existing
  assertions already encode the invariant this ticket must preserve.
- **Verification command**: `uv run pytest`
