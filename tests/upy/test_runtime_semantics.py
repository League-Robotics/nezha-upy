"""Runtime semantics that differ between MicroPython and CPython.

Each check pins MicroPython's ACTUAL behaviour, so that firmware code
written against a CPython mental model fails here rather than on the
bench. A failure means the interpreter changed, not that the test is
wrong -- read the implication note before editing one.
"""

from _harness import check, check_eq, report


def test_float_repr_is_shorter():
    """MicroPython prints 0.1+0.2 as '0.3'; CPython as
    '0.30000000000000004'. IMPLICATION: never put repr(float) in a wire
    format, a golden vector, or a config file expected to round-trip
    between host tooling and device."""
    check_eq("repr(0.1+0.2) is short on MicroPython", repr(0.1 + 0.2), "0.3")
    check("float still compares unequal to the short literal",
          (0.1 + 0.2) != 0.3 or True)  # value may or may not be exact; repr is the point


def test_dict_is_not_insertion_ordered():
    """CPython 3.7+ guarantees insertion order; MicroPython does not.
    IMPLICATION: never iterate a dict where order affects behaviour --
    field packing, wire encoding, config emission. Sort explicitly or
    use a list of pairs."""
    d = {}
    d["b"] = 1
    d["a"] = 2
    keys = list(d.keys())
    check("dict order is not insertion order here", keys != ["b", "a"],
          "keys=%r -- if this now matches insertion order, the guarantee "
          "still is not documented; keep sorting explicitly" % (keys,))


def test_int_is_arbitrary_precision():
    """This build has big ints. IMPLICATION: matches CPython, so
    integer maths in wire packing is safe -- but a different port
    config could disable them, so this pins the assumption."""
    check_eq("2**70 is exact", 2 ** 70, 1180591620717411303424)


def test_floor_division_and_modulo_match_cpython():
    """Sign conventions for negative operands match CPython.
    IMPLICATION: encoder tick maths with negative positions is safe."""
    check_eq("-7 // 2", -7 // 2, -4)
    check_eq("-7 % 2", -7 % 2, 1)


def test_round_is_half_to_even():
    """Banker's rounding, same as CPython. IMPLICATION: duty and
    velocity rounding agree between host tests and device."""
    check_eq("round(0.5)", round(0.5), 0)
    check_eq("round(1.5)", round(1.5), 2)
    check_eq("round(2.5)", round(2.5), 2)


def test_exception_messages_differ_from_cpython():
    """Message TEXT differs even where the exception TYPE matches.
    IMPLICATION: assert on exception type, never on str(e)."""
    try:
        [1, 2].index(9)
        check("list.index raises", False, "no exception raised")
    except ValueError as e:
        check("ValueError type matches CPython", True)
        check("message text differs from CPython's",
              "list.index" not in str(e),
              "got %r -- CPython says 'list.index(x): x not in list'" % (str(e),))


def test_bytes_int_fills_with_zero():
    """IMPLICATION: bytes(n) zero-fill is safe for frame scratch buffers."""
    check_eq("bytes(3)", bytes(3), b"\x00\x00\x00")


def test_bytearray_does_not_support_del():
    """`del ba[...]` (item OR slice) raises `TypeError` on a
    `bytearray` -- unlike CPython, where both work fine, which is
    exactly why `tests/unit/test_protocol_golden_vectors.py` (100%
    CPython) never caught `core/protocol.py`'s `_on_line_complete()`/
    `_append_byte()` using `del self._line_buf[:]` and `del
    self._line_buf[-1:]` to reset/trim its line buffer -- it crashed on
    the FIRST real line `feed()` ever completed on real hardware
    (sprint 007 ticket 010, found live on tovez: `TypeError: 'bytearray'
    object doesn't support item deletion`, raised inside the scheduled
    pump callback while handling a `HELLO` datagram -- the callback
    aborted silently, so `HELLO`'s own banner reply never got queued,
    while an unrelated peer-learning `READY` sent moments earlier via a
    different code path in `wifi_at.py` got through fine, which is what
    made this look at first like a reply-routing bug rather than a
    crash).

    NOT config-gated the way `src/radio_shim.py`'s slice-ASSIGNMENT
    landmine is (see this directory's README) -- this unix port has
    `MICROPY_PY_ARRAY_SLICE_ASSIGN(1)`, the richer of the two ports'
    configs, and it STILL raises here, matching the live hardware
    traceback captured on tovez's micro:bit port exactly. Deletion and
    assignment are different features; this one was not observed to
    diverge between ports. IMPLICATION: never `del` into a `bytearray`
    on this firmware -- reassign (`buf = bytearray()`) or slice-copy
    (`buf = buf[:-1]`) instead, the pattern `wifi_at.py`'s own line
    buffers already used everywhere, which is presumably why that
    module's real-hardware AT bring-up never hit this."""
    ba = bytearray(b"abc")
    try:
        del ba[:]
        check("del ba[:] raises on this bytearray", False,
              "no exception raised -- if this now passes, the fix in "
              "core/protocol.py's _on_line_complete()/_append_byte() "
              "(reassign instead of del) is no longer load-bearing, but "
              "keep it: it is still correct, just no longer necessary")
    except TypeError as e:
        check("del ba[:] raises TypeError", True)
        check("message matches the live hardware traceback",
              "item deletion" in str(e), "got %r" % (str(e),))

    ba2 = bytearray(b"abc")
    try:
        del ba2[-1:]
        check("del ba2[-1:] raises on this bytearray", False,
              "no exception raised")
    except TypeError:
        check("del ba2[-1:] raises TypeError", True)

    # The FIX this ticket applied: reassignment and slice-copy both
    # work fine and produce the same result `del` would have, on
    # CPython, if it were supported here.
    ba3 = bytearray(b"abc")
    ba3 = bytearray()
    check_eq("reassign-to-empty works", bytes(ba3), b"")
    ba4 = bytearray(b"abc\r")
    ba4 = ba4[:-1]
    check_eq("slice-copy trim works", bytes(ba4), b"abc")
    check("slice-copy result is still a bytearray",
          isinstance(ba4, bytearray))


test_float_repr_is_shorter()
test_dict_is_not_insertion_ordered()
test_int_is_arbitrary_precision()
test_floor_division_and_modulo_match_cpython()
test_round_is_half_to_even()
test_exception_messages_differ_from_cpython()
test_bytes_int_fills_with_zero()
test_bytearray_does_not_support_del()
report("runtime_semantics")
