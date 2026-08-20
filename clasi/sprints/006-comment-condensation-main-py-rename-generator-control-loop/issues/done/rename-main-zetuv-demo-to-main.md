---
status: done
sprint: '006'
tickets:
- 006-001
---

# Rename `src/main_zetuv_demo.py` to `src/main.py`

The on-device student-code entry point is stored in the repo as
`src/main_zetuv_demo.py` but is deployed to the device filesystem as
`main.py`. Rename it in the repo to match what it actually is:
`src/main.py`.

## What to do

```
git mv src/main_zetuv_demo.py src/main.py
```

then update the references:

- `manifest.py:58` — comment mentioning the file by name.
- `tests/test_manifest_freeze.py:12,21,38` — including
  `_BENCH_ONLY_MODULES = {"main_zetuv_demo.py"}`, the set that asserts
  this file is deliberately excluded from the frozen manifest.
- `src/demo_square.py:331,966` — two comment references.
- The file's own module docstring, which explains the old name.
- `docs/bench-log-zetuv-2026-08-19.md` — historical log; leave the
  existing entries as written (they record what was true at the time)
  and note the rename in a new entry rather than rewriting history.
- Any deploy command in docs/scripts of the form
  `mpremote ... fs cp src/main_zetuv_demo.py :main.py`, which becomes
  `... fs cp src/main.py :main.py`.

## Constraint that must survive the rename

`src/main.py` must stay OUT of `manifest.py`. `mp_main()` probes the
device *filesystem* for `main.py`; a frozen module named `main` would
never be found. The exclusion is currently enforced by
`_BENCH_ONLY_MODULES` in `tests/test_manifest_freeze.py` — update the
entry to `"main.py"` and keep the guard, so the rename does not make
it trivially easy for someone to later freeze the module and silently
break boot.

Related: [[condense-comments-across-the-codebase]] rewrites this same
file's docstring; land the two together.
