# MicroPython semantics tests

These run under the **MicroPython** interpreter, not CPython, because
some of this firmware's behaviour depends on runtime semantics the two
do not share. A CPython-only suite cannot express the difference.

The motivating case (sprint 006 ticket 009): `motion.drive()`'s
generator has a `finally` that stops the wheels. Breaking out of a
`for` loop runs it on CPython (refcounting closes the generator at
once) and does **not** run it on MicroPython (mark-and-sweep does not).
The pytest suite asserted the path via `gen.close()`, passed, and the
robot kept driving after `break`. It took a build, a flash and a bench
session to find. `test_generator_semantics.py` here reproduces it in
milliseconds.

## Running

    uv run pytest tests/test_upy_semantics.py

That wrapper builds nothing — it locates the interpreter, runs every
`test_*.py` in this directory under it, and fails if any exits non-zero.
If the interpreter is missing the wrapper SKIPS rather than fails, so
CI and laptops without it stay green.

## Building the interpreter

    cd micropython-microbit-v2/lib/micropython/ports/unix
    make submodules
    make CFLAGS_EXTRA="-Wno-error=array-bounds -Wno-array-bounds -Wno-error" \
         MICROPY_PY_FFI=0 MICROPY_PY_USSL=0 MICROPY_SSL_AXTLS=0 MICROPY_PY_BTREE=0

Produces `ports/unix/micropython` (MicroPython 1.18, matching the
vendored tree the firmware is built from). The warning suppressions are
needed because 1.18 predates current clang and builds with `-Werror`;
FFI/SSL/BTREE are off because none of them matter for language
semantics and they drag in extra dependencies.

## Writing a test here

Plain scripts — no pytest, which does not run under MicroPython. Use
the tiny `check()` helper from `_harness.py`, print failures, and exit
non-zero if any check fails. Keep them dependency-free.

What belongs here: anything whose correctness depends on the *runtime*
rather than on logic — generator finalization and `GeneratorExit`
timing, `gc` behaviour, `bytearray`/`memoryview` slice assignment,
integer width, `struct` packing edges, and which exception type a
built-in raises. Ordinary logic tests belong in the normal pytest
suite, where they are easier to write and debug.

## What this does NOT catch

The unix port is not the micro:bit port. It runs the same interpreter
core, so **interpreter-level** semantics transfer — generator
finalization, GC behaviour, integer and float handling, exception
types. Those are what the tests here pin.

**Config-gated feature differences do not transfer**, and assuming they
do is the way to get burned. Worked example: `src/radio_shim.py` carries
a landmine saying bytearray slice-assignment raises `TypeError` *on
device*. It does not raise here — the unix port sets
`MICROPY_PY_ARRAY_SLICE_ASSIGN (1)` in its `mpconfigport.h`, while the
micro:bit port leaves it at the off-by-default for its ROM level. A test
here asserting slice-assign works would pass and prove nothing about the
device.

So:

- Semantics owned by the interpreter core → testable here, trust it.
- Behaviour gated by a `MICROPY_PY_*` config flag → **check both ports'
  `mpconfigport.h` before believing a result**, and verify on hardware.
- Anything touching the native `diffdrive`/`wifiuart` modules, CODAL, or
  real timing → hardware only. This harness cannot see them.

When a device-only behaviour bites, the fix is a bench log entry and a
landmine comment, as before. This harness shrinks that category; it does
not eliminate it.
