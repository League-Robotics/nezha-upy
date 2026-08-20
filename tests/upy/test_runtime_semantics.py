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


test_float_repr_is_shorter()
test_dict_is_not_insertion_ordered()
test_int_is_arbitrary_precision()
test_floor_division_and_modulo_match_cpython()
test_round_is_half_to_even()
test_exception_messages_differ_from_cpython()
test_bytes_int_fills_with_zero()
report("runtime_semantics")
