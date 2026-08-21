---
status: done
---

# Deploy user programs to the filesystem; freeze only firmware

## Description

Every Python module is currently frozen into ROM, including
`demo_square.py` and `demo_util.py`. That inverts the cost curve: the
demo is the module iterated on most, and each change costs a ~4-minute
`./build.sh --clean` plus a reflash.

The target is the split a production user would actually see:

| Tier | Contents | Change cost |
| --- | --- | --- |
| Frozen firmware | `core/*`, `hardware/*`, `devices/*`, `boot.py` | rebuild + flash |
| User programs (filesystem) | `main.mpy`, `demo_square.mpy`, `robot.json` | deploy, seconds |

## Cause

Two constraints put every module in ROM and keep it there.

**`.mpy` cannot be loaded from the filesystem on this build.**
`MICROPY_PERSISTENT_CODE_LOAD` is 0 (upstream default; the port never
sets it), so `stat_file_py_or_mpy` never tries the `.mpy` extension.
A filesystem module must therefore be raw `.py` compiled on-device at
import, and `demo_square.py` at ~14.7 KB stripped will not compile in a
~17 KB free heap — that is the `MemoryError` that forced freezing in the
first place. `mpy-cross` in this build is consequently only a syntax
lint (`docs/design/specification.md` §7.4).

**Packages can never live on the filesystem**, regardless of the above.
`uos_mbfs_import_stat` (`micropython-microbit-v2/src/codal_port/
microbitfs.c`) cannot return `MP_IMPORT_STAT_DIR` because the micro:bit
FS is flat, so `builtinimport.c`'s `stat_dir_or_file` can never descend
into `core/`. Frozen-only for the packages is structural, not a choice —
which is exactly the tier split wanted here, but it bounds what deploy
can ever cover.

One helpful fact already holds: `sys.path` is `["", ".frozen"]`, so a
filesystem module automatically shadows its frozen twin. The deploy
semantics come for free once loading works.

## Proposed fix

### A. Enable `.mpy` loading from the filesystem

Three edits in the vendored checkout, applied by `build.sh` following
the existing idempotent `if "MARKER" not in src` patch pattern (see its
step 13d):

1. `mpconfigport.h`: `#define MICROPY_PERSISTENT_CODE_LOAD (1)`
2. `mpconfigport.h`: `#define MICROPY_HAS_FILE_READER (1)`
   **Not optional.** With only the first define, `stat_file_py_or_mpy`
   finds `foo.mpy` and then `do_load` falls through to
   `mp_lexer_new_from_file`, feeding binary bytecode to the *parser*. It
   surfaces as a syntax error — looking like a corrupt file rather than
   a missing feature.
3. A ~15-line `mp_reader_new_file()` in the port. Upstream defines it
   only under `MICROPY_READER_POSIX` (`lib/micropython/py/reader.c`).
   Model it on `uos_mbfs_new_reader` (`microbitfs.c`), filling an
   `mp_reader_t` instead of calling `mp_lexer_new`. `file_read_byte`
   already returns `(mp_uint_t)-1`, which is exactly `MP_READER_EOF`.

Cost ~4-5.5 KB flash against ~88 KB headroom below `_fs_start`;
`tests/test_build_gate.py`'s ceiling gate still passes. mpy v5 and the
feature byte already match what the in-tree `mpy-cross` emits, so there
is no version work.

Do NOT enable `MICROPY_READER_VFS` — it drags in the whole VFS
subsystem this port does not have.

### B. Make the user program actually a user program

`demo_square.py` compiles to ~7.5 KB of bytecode because it carries the
move engine, geometry derivation, config parsing, `balanced_duties`, the
legacy segment engine, and tour construction. Most of that is firmware.

Move into frozen `src/hardware/motion.py` (already the drivetrain layer,
already frozen):

- `_move()` — the tuned ramp/taper/`neutral()` engine and its constants
  (`MOVE_RAMP_MS`, `MOVE_DIST_TAPER`, `MOVE_YAW_TAPER`, margins)
- `_configure_and_start()` and the `_started` once-per-boot latch
- `VELOCITY_GAINS` and the `TICKS_PER_MM` scaling
- `geometry_from_robot_config()` / `_wiring_from_robot_config()`

`src/demo_square.py` then becomes a thin script: build the leg/turn
list, call the frozen move API, save tour state. Target ~1.5 KB `.mpy`.

This is what makes the whole change safe on heap — see Risks.

Keep the legacy duty-mode segment engine where it is:
`tests/test_demo_square.py` pins `balanced_duties` and friends, and it
remains the non-PID fallback path.

### C. `tools/deploy.py` — a committed deploy path

There is no deploy script in the repo at all today. It has always been
hand-typed `mpremote fs cp` against hand-generated stripped files, and
the `robot.json` strip transform exists only as prose — the bench log's
"command" is literally `python3 -c "... strip ..."` with ellipses.

`tools/deploy.py <robot>` should, in order:

1. Strip `data/<robot>.json`: drop `_`-prefixed keys recursively, then
   `json.dumps(separators=(',', ':'))`. Documented in `data/README.md`
   and the bench log; encode it once, in code.
2. Compile each user program with the in-tree `mpy-cross` (`-O3`).
3. **Budget-check before copying**, against the real usable size:
   160 chunks x 126 B = 20,160 B, NOT the 24,576 B region size. Today
   this failure only ever surfaces at the bench as
   `mpremote: cp: robot.json: No space left on device`.
4. Resolve the target by UID from `config/devices.json` (never by drive
   letter) and confirm on-device identity before writing.
5. Copy via `mpremote fs cp`, then read back and verify sizes.

Print a table of source -> deployed bytes and the budget total.

While here: `build.sh`'s closing hint (`cp ... /Volumes/MICROBIT`)
contradicts the UID-only convention in
`docs/bench-acceptance-procedures.md`. Fix that line.

### D. Manifest and tests follow the split

- `manifest.py`: drop `demo_square.py` / `demo_util.py`; keep `boot.py`
  and the three packages. Also fix the stale comment block still
  claiming `demo_square` is "DELIBERATELY ABSENT" from a list it sits in.
- `tests/test_manifest_freeze.py`: `_BENCH_ONLY_MODULES` grows from
  `{"main.py"}` to the user-program set. Keep the exact-set-equality
  invariant — it is what stops a module being silently left unfrozen.
- New test for the deploy budget: stripped `robot.json` plus the
  compiled user programs must fit 20,160 B.

## Verification

1. `uv run pytest` — 248 passing before and after.
2. `./build.sh --clean --with-diffdrive`, then
   `pytest tests/test_build_gate.py` to confirm `flash_end < _fs_start`
   still holds with the loader compiled in.
3. Flash the target by UID, then `python3 tools/deploy.py <robot>`.
4. Prove the mechanism on device rather than assuming it:
   - `sys.modules` / `demo_square.__file__` show the FILESYSTEM copy in
     use, not the frozen one.
   - Deploy an edited `demo_square.mpy` (change a printed string), reset,
     and confirm the new string appears with NO reflash.
5. `python3 tools/tour_run.py <port> --robot <robot>` — closure and
   per-move overshoot must match the current baseline: legs within a few
   mm of 500 mm, turns within ~2 deg of 90 deg.
6. Virtual button press (the `uart` trigger variant) to confirm the
   button path still drives after the refactor.
7. Report free heap after boot, before and after. This is the number the
   change risks; measure it, do not infer it.

## Risks

- **Heap is the binding constraint, not flash or filesystem.** A
  filesystem `.mpy` is copied into the 40 KB GC heap; a frozen one
  executes in place from ROM. Free heap after boot measures ~17 KB and a
  recent `MemoryError` needed 3 KB contiguous. If the part B refactor
  does not get `demo_square.mpy` to ~1.5 KB, stop and re-measure before
  going further — reverting to frozen demos is the fallback.
- Moving the move engine touches the code path that currently produces
  good tours. Re-run the tour benchmark immediately after, not at the end.
- A stale `.mpy` on the device silently shadows a fixed frozen module.
  Deploy should report exactly what it wrote, and there should be an
  obvious way to clear the filesystem back to factory behaviour.

## Related

Deferred, and worth separate issues rather than folding in here:

- `crawlPulse` (sub-breakaway dithering), still unadopted from
  `pxt-nezha-diffdrive` and the likely lever on residual turn scatter.
- That project's `RUN:<n>` host-trigger dispatch. Needs the serial
  arbitration question answered first — the TLM stream and the
  REPL/file-transfer channel contend for the same USB CDC link.
- An intermittent leg that terminated ~408 mm short in one of three
  tours, unexplained; recorded in commit `c0d9ad4`.

## Resolution

Done in `e05c606` (OOP, master). Parts A, C and D as written. **Part B
was deliberately NOT done** — see below.

### Measured outcomes

| | Before | After |
| --- | --- | --- |
| Free heap after boot | 16,704 B | **23,408 B** |
| Deploy payload | n/a | **13,270 B** of 20,160 B |
| Tour legs / turns / closure | +/-1.9 mm, +/-1.4 deg, 14-24 mm | +/-1.7 mm, +/-1.1 deg, 24 mm |
| Tests | 248 | **257** (518 subtests) |

Deployed sizes: `robot.json` 61044 -> 2866, `main.mpy` 9826 -> 1601,
`demo_util.mpy` 4417 -> 1114, `demo_square.mpy` 30935 -> 7689.

### The mechanism was proven, not assumed

Verification step 4 was the point of the whole exercise. Injected an
`FS-DEPLOY-MARKER` string into `demo_square.py`, ran only
`tools/deploy.py`, and the robot printed
`demo_square: FS-DEPLOY-MARKER d=500mm y=0deg dL=6406 dR=6403` — **no
rebuild, no reflash**. Marker reverted and redeployed afterwards.

Part A's config edits were likewise confirmed by linker-map ADDRESS
(`mp_reader_new_file` @ `0x0000c19c`, `mp_raw_code_load_file` @
`0x000266fc`), not by the build log — because the first attempt
"succeeded" with the feature silently off.

### Part B skipped — and why that is the right call

Part B (move the `_move()` engine into frozen `hardware/motion.py`)
existed for exactly one reason, stated in Risks: get `demo_square.mpy`
small enough that a filesystem copy fits the heap. It would also have
touched the code path that currently produces good tours.

**Change E instead**: `boot.run()` now extracts the scalars it needs
from the parsed `robot.json` and releases the document. Measured on
tovez, that document is 6,912 B resident of a 16,704 B heap — 41% of it,
the single largest allocation on the device — and `ConfigDispatch` was
pinning it alive through a `self._config` reference it never read.

Releasing it freed **6,704 B**, more than Part B's ~6 KB of bytecode
relocation would have, without moving a line of tuned motion code. The
7,689 B `demo_square.mpy` then fits with room to spare (7,920 B free
mid-drive, no leak across runs).

`config_ok()` became the readiness flag as a consequence:
`robot_config is not None` no longer answers "did config load", since
the document is now released on the success path.

### Four build failures worth keeping

All are now encoded in `build.sh` step 13e so a fresh checkout
reproduces them:

1. **The config anchor must be a REGEX.** `mpconfigport.h` is
   column-aligned, so the literal `#define MICROPY_MODULE_FROZEN_MPY (1)`
   never matched the real `...MPY               (1)`. The patch warned
   and silently left the feature off — and the build still succeeded.
2. `persistentcode.c` trips `-Werror=unused-but-set-variable`. Scoped a
   per-file `-Wno-error=` in `codal_port/Makefile`, following the
   existing `sam.o` precedent rather than weakening the global flags.
3. `mp_reader_new_file` needs casts on its callbacks —
   `mp_reader_t` holds `void*`-typed function pointers, matching
   `uos_mbfs_new_reader`.
4. **`MICROPY_EMIT_INLINE_THUMB` had to be turned OFF.** It forces
   `MICROPY_EMIT_MACHINE_CODE`, which makes `persistentcode.c` compile
   native-loading paths referencing `mp_fun_table` — undefined without
   the native emitter, so the link failed. *This reverses my earlier
   stated position that the inline-Thumb emitter should stay on.*
   Nothing in the tree uses `@micropython.asm_thumb` (grepped); if
   something ever needs it, the native emitter has to come on with it.

### Structural limit, now documented

`uos_mbfs_import_stat` cannot return `MP_IMPORT_STAT_DIR` on this flat
filesystem, so `core/`, `hardware/` and `devices/` can **never** be
filesystem-deployed. Frozen-only for packages is a property of the port,
not a policy choice. Noted in `manifest.py`;
`tests/test_deploy_budget.py` enforces that the deploy set and the
freeze list can never overlap.

### Deferred items split out

The three "Related" items became their own pool issues rather than
riding along here: `crawlpulse-sub-breakaway-dithering.md`,
`host-triggered-program-dispatch-over-serial.md`,
`intermittent-short-leg-in-square-tour.md`.
