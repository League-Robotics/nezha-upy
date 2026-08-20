---
status: pending
---

# Run the test suite under MicroPython, not only CPython

The offline suite runs on CPython, whose semantics differ from
MicroPython's in ways that have now silently passed broken code to
hardware at least twice. Build the in-tree MicroPython unix port and
run a semantics-sensitive subset of the tests under it.

## The evidence

Sprint 006 ticket 009, bench run on tovez:

`motion.drive()`'s generator has a `finally` block that lands a neutral
and a final step. `tests/test_motion.py` asserted it via `gen.close()`
and passed. On hardware, the documented student idiom — `break` out of
the `for` loop — does **not** run that `finally` at all:

| Path | cycleCount | duty after | finally ran |
| --- | ---: | --- | --- |
| `gen.close()` | 5 → 6 | 0.0 / 0.0 | yes |
| `break` | 12 → 12 | 17.0 / 17.0 | no |
| `break` + `gc.collect()` | 12 → 12 | 17.0 / 17.0 | no |

CPython's refcounting closes a suspended generator promptly;
MicroPython's mark-and-sweep does not, so `GeneratorExit` never fires.
The suite was green the whole time and the wheels kept turning.

This is not the first instance of the same class. `src/radio_shim.py`
carries a landmine about `bytearray` slice-assignment raising
`TypeError` on device but working fine on CPython — found the same
way, on hardware, after the fact.

## What to do

`micropython-microbit-v2/lib/micropython/ports/unix` is already present
in the tree. Build it, and run a targeted subset of the suite against
that interpreter in addition to CPython.

The subset is the point — this is not "run everything twice." Target
tests whose correctness depends on runtime semantics rather than on
logic:

- generator finalization and `GeneratorExit` timing
- `gc` behaviour, anything asserting cleanup happened
- `bytearray` / `memoryview` slice assignment
- integer width, float formatting, `struct` packing edge cases
- exception types raised by built-ins (MicroPython often differs)

Mark such tests with a marker (e.g. `@pytest.mark.upy_semantics`) so
the MicroPython pass has a clear, maintained target set rather than
drifting.

## Why it is worth the setup cost

Every bug of this class currently costs a full build-flash-bench cycle
to find, and is only found if someone thinks to test that exact path on
hardware. The generator bug was found only because the bench leg
explicitly compared `close()` against `break`. A CPython-only suite
cannot express the difference at all.

Related: [[tlm-stream-ignores-tlm-off]] and
[[robot-identity-collision-and-stale-device-map]] were also found on
the bench during the same session.
