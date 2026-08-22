"""tests/unit/test_protocol_golden_vectors.py -- ticket 001 gate,
retargeted by ticket 012 (2026-08-21 reliability-layer retarget):
``src/core/protocol.py``'s ``ProtocolHandler`` against
``tests/fixtures/protocol_golden_vectors_reliability.txt`` (this
repo's own fixture, mechanically derived from
``reference/protocol-draft-2026-08-21.md``'s Sec 6/8 tables), plus
explicit unit tests for what a tidy golden vector never exercises.

Shape ported from radio-robot-lib's
``tests/protocol/test_protocol_harness.py`` -- two kinds of coverage,
same as there:

1. ``test_golden_vector_block`` drives every block in the fixture
   through ``ProtocolHandler`` + a mock Adapter/Sink and asserts the
   sink's captured output line-for-line. As of the 2026-08-21 retarget
   every verb this sprint scopes in (13, RUN/debug included) is fully
   implemented, so -- unlike the pre-retarget fixture this harness used
   to drive -- EVERY block in the new fixture runs for real; there is
   no per-block skip/classify mechanism any more (there is nothing left
   to defer to a later ticket).

2. The individual ``test_*`` functions below (largely UNCHANGED by
   this retarget -- see each one's own docstring for which pre-
   retarget shapes it still pins, pending ticket 013's reconciliation)
   cover ``feed()``'s byte-block-boundary contract, the 240-byte
   overflow-discard rule, blank/all-whitespace-line silence, the
   malformed-line recovery rules in more depth than the fixture alone
   provides, and ``HELP``'s "generated from the dispatch table"
   guarantee. A NEW section at the end of this file (search for
   "ticket 012 (2026-08-21 retarget): new reliability-layer tests")
   adds hand-written coverage for what the fixture alone cannot prove
   (e.g. a resent id must not re-drive the wheels -- a call-count
   assertion, not a wire-visible one).

Run with::

    python3 -m pytest tests/unit/test_protocol_golden_vectors.py -v
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = _REPO_ROOT / "src"
_THIS_DIR = Path(__file__).resolve().parent
# Ticket 012 (2026-08-21 retarget): re-pointed from the now-superseded
# protocol_golden_vectors.txt (still present, banner-marked, gating
# nothing) to this repo's own reliability-layer fixture.
_FIXTURE_PATH = (_REPO_ROOT / "tests" / "fixtures"
                  / "protocol_golden_vectors_reliability.txt")

for _path in (_SRC_DIR, _THIS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from core import protocol  # noqa: E402  (path must be set up first)
import _protocol_fixture  # noqa: E402
import _protocol_mock_adapter  # noqa: E402


def _new_handler():
    adapter = _protocol_mock_adapter.MockAdapter()
    sink = _protocol_mock_adapter.RecordingSink()
    handler = protocol.ProtocolHandler(adapter, sink)
    return handler, adapter, sink


# ---------------------------------------------------------------------------
# Acceptance criterion: the fixture parses structurally into a runnable
# block list with zero parse errors, independent of whether the
# handler implements anything at all.
# ---------------------------------------------------------------------------

_FIXTURE_TEXT = _FIXTURE_PATH.read_text()
_BLOCKS = _protocol_fixture.parse_golden_vectors(_FIXTURE_TEXT)


def test_fixture_parses_with_no_errors():
    assert len(_BLOCKS) > 0, (
        "no golden-vector blocks parsed -- fixture path or format broke")


def test_fixture_block_count_is_stable():
    """Pinned so a future edit of the fixture (deliberate or not) shows
    up as a visible diff here, not a silent drop. Recount if
    protocol_golden_vectors_reliability.txt gains or loses vectors."""
    assert len(_BLOCKS) == 37


# ---------------------------------------------------------------------------
# Unlike the pre-retarget fixture this harness used to drive, EVERY
# verb this sprint scopes in (13, RUN/debug included) is fully
# implemented as of the 2026-08-21 retarget -- there is no per-block
# skip/classify mechanism any more; every block below runs for real.
# ---------------------------------------------------------------------------

# The fixture's own SETUP key comment: "setresult <ordinal> --
# Protocol::Result's declaration-order ordinal, see
# test_protocol_harness.py's RESULT_* map". This is the C++
# archetype's own enum declaration order (kOk=0, kUnknown=1,
# kBadArg=2, kRange=3, kFull=4, kUnimplemented=5, kNotReady=6,
# kBusy=7, kDuplicateId=8), which is NOT the same sequence as this
# port's own protocol.Result values (protocol.py's own Result
# docstring: each attribute's value already IS its wire code, so
# kUnimplemented's ordinal 5 lands on wire code 6, etc.) -- this table
# is the fixture-format's own translation from one numbering to the
# other, kept here rather than in protocol.py because it is a property
# of THIS fixture's SETUP syntax, not of the port itself.
_SETRESULT_ORDINAL_TO_RESULT = (
    protocol.Result.OK,             # 0
    protocol.Result.UNKNOWN,        # 1
    protocol.Result.BADARG,         # 2
    protocol.Result.RANGE,          # 3
    protocol.Result.FULL,           # 4
    protocol.Result.UNIMPLEMENTED,  # 5
    protocol.Result.NOT_CONFIGURED,  # 6
    protocol.Result.BUSY,           # 7
    protocol.Result.DUPLICATE_ID,   # 8
)


def _apply_setup(adapter, key, tokens):
    if key == "identity":
        name, serial, drivetrain, profile, version = tokens
        adapter.name = name
        adapter.serial = serial
        adapter.drivetrain = drivetrain
        adapter.profile = profile
        adapter.version = version
    elif key == "now":
        adapter.now_value = int(tokens[0])
    elif key == "status":
        ready, active, connl, connr, otos, wedge, flags, tlm = tokens
        adapter.status_ready = bool(int(ready))
        adapter.status_active = bool(int(active))
        adapter.status_conn_left = bool(int(connl))
        adapter.status_conn_right = bool(int(connr))
        adapter.status_otos = bool(int(otos))
        adapter.status_wedge = bool(int(wedge))
        adapter.status_flags = int(flags)
        adapter.status_tlm = tlm
    elif key == "setresult":
        adapter.set_result = _SETRESULT_ORDINAL_TO_RESULT[int(tokens[0])]
    elif key == "wheelsresult":
        adapter.wheels_result = _SETRESULT_ORDINAL_TO_RESULT[int(tokens[0])]
    elif key == "stopresult":
        adapter.stop_result = _SETRESULT_ORDINAL_TO_RESULT[int(tokens[0])]
    elif key == "runresult":
        adapter.run_result = _SETRESULT_ORDINAL_TO_RESULT[int(tokens[0])]
    elif key == "runvalue":
        adapter.run_value = tokens[0]
    elif key == "runhasvalue":
        adapter.run_has_value = bool(int(tokens[0]))
    elif key == "getoverride":
        name, value = tokens
        adapter.get_overrides[name] = float(value)
    elif key == "fieldnames":
        adapter.field_names = list(tokens)
    else:
        raise ValueError(
            "SETUP key %r not recognized by this fixture's mock adapter -- "
            "protocol_golden_vectors_reliability.txt's own header comment "
            "lists every key this harness supports; either the fixture or "
            "_apply_setup() needs to grow to match" % (key,))


def _apply_emit_action(handler, payload):
    """``payload`` is the fixture's own EMIT sub-syntax: a list of
    ``"<name>:<hex0or1>:<value>"`` tokens (see
    protocol_golden_vectors.txt's own header comment) -- unpacked here
    into the ``(name, value, hex)`` tuples ``ProtocolHandler.
    emit_telemetry()`` takes, then fed straight to it. Never touches
    ``feed()`` -- EMIT drives ``emit_telemetry()`` directly, the same
    way the C++ harness's own ``phEmitTelemetry()`` call does, since
    there is no wire form a host ever sends this on."""
    columns = []
    for token in payload:
        name, hexflag, value = token.split(":")
        columns.append((name, int(value), bool(int(hexflag))))
    handler.emit_telemetry(columns)


def _run_block(block):
    handler, adapter, sink = _new_handler()
    for key, tokens in block.setup:
        _apply_setup(adapter, key, tokens)
    for kind, payload in block.actions:
        if kind == "IN":
            handler.feed((payload + "\n").encode("ascii"))
        elif kind == "EMIT":
            _apply_emit_action(handler, payload)
        elif kind == "DEBUG":
            # protocol.md Sec 6.2: send_debug() is unsolicited,
            # robot-to-host only -- never reached through feed(), so
            # this fixture's own DEBUG action calls it directly, the
            # same way EMIT calls emit_telemetry() directly.
            handler.send_debug(payload)
        else:
            raise ValueError("action kind %r not supported" % (kind,))
    return sink.lines()


_PARAMS = [
    pytest.param(_index, _block, id="block%02d" % _index)
    for _index, _block in enumerate(_BLOCKS)
]


@pytest.mark.parametrize("index,block", _PARAMS)
def test_golden_vector_block(index, block):
    actual = _run_block(block)
    assert actual == block.expected_out, (
        "golden vector block %d (actions=%r) mismatch:\n"
        "  expected: %r\n"
        "  actual:   %r" % (index, block.actions, block.expected_out, actual))


# ---------------------------------------------------------------------------
# feed()'s byte-block-boundary contract (protocol.md Sec 2/2.1)
# ---------------------------------------------------------------------------

def test_feed_several_complete_lines_in_one_block():
    handler, adapter, sink = _new_handler()
    adapter.now_value = 111
    handler.feed(b"PING #1\nPING #2\nPING #3\n")
    assert adapter.now_calls == 3
    assert sink.lines() == [
        "ack 1 0", "pong 111",
        "ack 2 0", "pong 111",
        "ack 3 0", "pong 111",
    ]
    assert handler.malformed_count() == 0


def test_feed_block_ending_mid_line_buffers_the_remainder():
    handler, adapter, sink = _new_handler()
    adapter.now_value = 222
    handler.feed(b"PI")
    assert sink.lines() == [], "dispatched before the line completed"
    assert adapter.now_calls == 0
    handler.feed(b"NG #1\n")
    assert sink.lines() == ["ack 1 0", "pong 222"]
    assert adapter.now_calls == 1


def test_feed_fragment_alone_never_dispatches():
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELLO")  # no terminator, ever
    assert sink.lines() == []
    assert adapter.identity_calls == 0
    assert handler.malformed_count() == 0


def test_feed_strips_lone_cr_before_terminator():
    handler, adapter, sink = _new_handler()
    adapter.now_value = 333
    handler.feed(b"PING #1\r\n")
    assert sink.lines() == ["ack 1 0", "pong 333"]
    assert handler.malformed_count() == 0


def test_feed_overlong_line_discarded_not_truncated():
    """protocol.md Sec 2/2.1: a line over the 240-byte cap must be
    discarded to the next '\\n', never truncated into a prefix that
    still parses as something the host never sent. The line's first 5
    bytes are a perfectly valid, correct-arity HELLO command -- if the
    implementation truncated instead of discarding, a naive truncation
    could dispatch as a bare HELLO. It must not."""
    handler, adapter, sink = _new_handler()
    overlong = b"HELLO " + (b"X" * 300) + b"\n"
    assert len(overlong) > 240
    handler.feed(overlong)
    assert adapter.identity_calls == 0, (
        "the valid-looking HELLO prefix must NOT have dispatched")
    assert sink.lines() == []
    assert handler.malformed_count() == 1

    # The parser must resync cleanly on the next line.
    adapter.now_value = 444
    handler.feed(b"PING #1\n")
    assert sink.lines() == ["ack 1 0", "pong 444"]


def test_feed_exactly_240_bytes_is_accepted():
    """Boundary companion to the overflow test above: a line whose
    TOTAL wire length (content + '\\n') is exactly 240 bytes -- Sec 2's
    own stated maximum -- must be accepted and dispatched normally, not
    discarded. Built on an unknown verb with an in-order id (rather
    than a verb this ticket's own stub bodies don't observably act on)
    so the assertions below (the ack, then the err) are proof the line
    was processed, not silently swallowed by the overflow path --
    overflow never replies at all."""
    handler, adapter, sink = _new_handler()
    padding = b"X" * 232
    line = b"FOO " + padding + b" #1"
    assert len(line) + 1 == 240
    handler.feed(line + b"\n")
    assert handler.malformed_count() == 1
    assert sink.lines() == ["ack 1 0", "err 1 #1"]


def test_feed_241_bytes_overflows():
    """One byte over the boundary above must overflow -- proving the
    cap is exactly 240, not off by one in either direction."""
    handler, adapter, sink = _new_handler()
    padding = b"X" * 233
    line = b"FOO " + padding + b" #7"
    assert len(line) + 1 == 241
    handler.feed(line + b"\n")
    assert handler.malformed_count() == 1
    assert sink.lines() == []


# ---------------------------------------------------------------------------
# Blank / all-whitespace lines are ignored SILENTLY (protocol.md Sec 2).
# ---------------------------------------------------------------------------

def test_blank_line_is_silently_ignored_not_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    handler.feed(b"\n\n\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    adapter.now_value = 666
    handler.feed(b"PING #1\n")
    assert sink.lines() == ["ack 1 0", "pong 666"]


def test_all_whitespace_line_is_silently_ignored_not_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"     \n")  # spaces only, no verb at all
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    adapter.now_value = 777
    handler.feed(b"PING #1\n")
    assert sink.lines() == ["ack 1 0", "pong 777"]


# ---------------------------------------------------------------------------
# A run of spaces is ONE separator; leading/trailing line whitespace is
# ignored (protocol.md Sec 2).
# ---------------------------------------------------------------------------

def test_space_run_between_fields_is_one_separator():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO   1   2   3   #1\n")
    assert sink.lines() == ["ack 1 0", "err 1 #1"]
    assert handler.malformed_count() == 1


def test_leading_and_trailing_line_whitespace_is_ignored():
    handler, adapter, sink = _new_handler()
    adapter.now_value = 888
    handler.feed(b"   PING #1  \n")
    assert sink.lines() == ["ack 1 0", "pong 888"]
    assert handler.malformed_count() == 0


# ---------------------------------------------------------------------------
# Case is direction (protocol.md Sec 2.1) -- the v5 DBG:-flood incident's
# structural fix.
# ---------------------------------------------------------------------------

def test_lowercase_verb_dropped_silently_not_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"dbg something happened\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    handler.feed(b"ack 5 0\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    adapter.now_value = 555
    handler.feed(b"PING #1\n")
    assert sink.lines() == ["ack 1 0", "pong 555"]


def test_mixed_case_verb_is_unknown_not_dropped():
    handler, adapter, sink = _new_handler()
    handler.feed(b"Ping\n")  # starts uppercase, not the literal PING
    assert sink.lines() == []
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# Unknown verb / wrong arity under mandatory sequencing (protocol.md Sec
# 8.4, superseding the old Sec 2.3 recovery rule this subsection used to
# pin): a well-formed, IN-ORDER id acks unconditionally, before the verb
# is even looked up -- an unrecognized verb (or a known verb with the
# wrong remaining-field count) is then a content-decode failure layered
# on top, err 1/2 #<id>, never a bare or id-first reply. No trailing
# field at all, or a trailing field that is not a well-formed '#[0-9]+',
# is still unclassifiable and gets no reply at all (Sec 8.4 items 1-2) --
# there is no longer any other kind of "unrecoverable" line, because an
# out-of-order id (retransmit/gap) is classified and answered on the id
# alone, without ever inspecting the verb (Sec 8.1/9.8 item 1).
# ---------------------------------------------------------------------------

def test_unknown_verb_no_reply_when_no_id_at_all_or_id_ill_formed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1

    handler.feed(b"FOO 1 2 3\n")  # last field "3" is not '#[0-9]+'
    assert sink.lines() == []
    assert handler.malformed_count() == 2


def test_unknown_verb_with_in_order_id_gets_ack_then_err_unknown():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO 1 2 3 #1\n")
    assert sink.lines() == ["ack 1 0", "err 1 #1"]
    assert handler.malformed_count() == 1
    sink.clear()

    handler.feed(b"BAR #2\n")
    assert sink.lines() == ["ack 2 0", "err 1 #2"]
    assert handler.malformed_count() == 2


def test_unknown_verb_trailing_id_zero_is_a_stale_retransmit_no_verb_lookup():
    """Since ids start at 1, an inbound "#0" always compares less than
    expected_next -- it is an ordinary retransmit (Sec 2.2/8.1), acked
    against the highest already-accepted id (0, nothing accepted yet)
    with the verb never even looked up. This supersedes the old "#0
    suppresses the reply" rule this test used to pin -- there is no
    longer any way to suppress a reply at all (Sec 2.2)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO #0\n")
    assert sink.lines() == ["ack 0 0"]
    assert handler.malformed_count() == 0


def test_wrong_arity_known_verb_still_acks_before_erring():
    """PING's only field is its own mandatory id -- "PING extra #1" has
    ONE real field ("extra") beyond the id, which is wrong arity for a
    zero-field verb; the ack still fires unconditionally (the id itself
    is in order) before the arity error is layered on top."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"PING extra #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1


def test_wrong_arity_rejected_no_best_effort_parse():
    handler, adapter, sink = _new_handler()
    handler.feed(b"PING extra\n")  # no '#id' at all -- unclassifiable
    assert sink.lines() == []
    assert handler.malformed_count() == 1

    handler.feed(b"HELLO extra\n")  # HELLO takes 0 fields, unsequenced
    assert sink.lines() == []
    assert adapter.identity_calls == 0
    assert handler.malformed_count() == 2


def test_id_rejects_leading_plus_sign():
    """The id's own grammar ('#' [0-9]+) allows no sign at all, unlike
    protocol.md Sec 2's general "every wire value is ... optionally
    signed" rule for ordinary fields -- "#+5" must NOT be treated as a
    well-formed id, so the whole line is unclassifiable (Sec 8.4 item
    2) and gets no reply at all."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO #+5\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# ESTOP: now ALWAYS replies the bare word "estop" (protocol.md Sec
# 8.3/SUC-002, flipped 2026-08-21 -- this supersedes the pre-retarget
# "ESTOP never replies" rule this subsection used to pin). Maximally
# forgiving: ANY line whose verb token is exactly ESTOP executes the
# stop and then replies, regardless of trailing junk or arity, and
# never increments malformed_count() -- there is no arity to inspect at
# all any more (resolved ambiguity #3, sprint 007 ticket 012).
# ---------------------------------------------------------------------------

def test_estop_replies_estop_after_executing():
    handler, adapter, sink = _new_handler()
    handler.feed(b"ESTOP\n")
    assert sink.lines() == ["estop"]
    assert adapter.estop_calls == 1
    assert handler.malformed_count() == 0


def test_estop_wrong_arity_still_replies_estop():
    handler, adapter, sink = _new_handler()
    handler.feed(b"ESTOP 1\n")
    assert sink.lines() == ["estop"]
    assert adapter.estop_calls == 1, "the stop must still have executed"
    assert handler.malformed_count() == 0


def test_estop_with_trailing_id_still_just_replies_estop():
    """The sharpest version of the ESTOP carve-out: `ESTOP #5` has a
    perfectly well-formed, in-order-looking trailing id -- every OTHER
    verb in this suite acks that shape (see
    test_wrong_arity_known_verb_still_acks_before_erring above). ESTOP
    is outside the sequence entirely: no ack, no err, just the bare
    `estop` reply, same as every other ESTOP shape."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"ESTOP #5\n")
    assert sink.lines() == ["estop"], (
        "ESTOP must reply the bare word 'estop', never ack/err, even "
        "with a trailing token that looks like a well-formed id")
    assert adapter.estop_calls == 1
    assert handler.malformed_count() == 0


# ---------------------------------------------------------------------------
# HELP: generated from the same dispatch table dispatch() uses
# (protocol.md Sec 4) -- cannot drift.
# ---------------------------------------------------------------------------

def test_help_text_is_generated_from_the_dispatch_table():
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELP #1\n")
    lines = sink.lines()
    assert len(lines) == 2
    assert lines[0] == "ack 1 0"
    expected_names = [
        name.decode("ascii") for name, _handler in protocol.ProtocolHandler.VERB_TABLE]
    assert lines[1] == "help " + " ".join(expected_names)


def test_help_matches_this_sprints_own_scoped_13_verb_list():
    """Renamed from the pre-retarget "...12_verb_list" (sprint 007
    ticket 013): RUN is in scope as of ticket 012's reliability-layer
    retarget, so HELP's reply grows to 13 verbs, RUN last (protocol.md
    Sec 6/9.7) -- reached via a mandatory in-order id now that HELP
    itself is sequenced (Sec 8.3/8.4), with the ack always ahead of
    HELP's own informational reply (Sec 8.1's "ack first, always")."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELP #1\n")
    assert sink.lines() == [
        "ack 1 0",
        "help HELLO PING ID VER STATUS HELP GET SET TLM WHEELS STOP "
        "ESTOP RUN",
    ]


def test_help_wrong_arity_still_acks_then_errs():
    """"HELP #3" alone is NOT wrong arity any more -- the trailing
    token is HELP's own mandatory id, consumed before HELP's own (zero
    remaining fields) arity check ever runs, and #3 would in any case
    be a gap against a fresh handler's expected_next=1. Wrong arity for
    a sequenced, zero-field verb now needs a genuine extra field ahead
    of an in-order id."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELP extra #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# Result -> wire error-code table (protocol.md Sec 4/6.1), ticket 002.
# ---------------------------------------------------------------------------

def test_result_code_covers_every_declared_error_code():
    """protocol.md Sec 6.1's full table, all 8 rejection codes -- in
    this port each Result attribute's own int value already IS its
    wire code (protocol.py's own Result docstring), so this is mostly
    an identity check, but it is pinned one attribute at a time, the
    same way the C++ archetype's own resultCode() switch is exercised
    one enumerator at a time in its own test suite."""
    assert protocol.result_code(protocol.Result.UNKNOWN) == 1
    assert protocol.result_code(protocol.Result.BADARG) == 2
    assert protocol.result_code(protocol.Result.RANGE) == 3
    assert protocol.result_code(protocol.Result.FULL) == 4
    assert protocol.result_code(protocol.Result.UNIMPLEMENTED) == 6
    assert protocol.result_code(protocol.Result.NOT_CONFIGURED) == 8
    assert protocol.result_code(protocol.Result.BUSY) == 10
    assert protocol.result_code(protocol.Result.DUPLICATE_ID) == 11


def test_result_code_falls_back_to_unknown_for_an_untaught_value():
    """Mirrors the C++ archetype's own defensive switch fallthrough
    ("kept so a FUTURE enumerator trips -Wswitch instead of silently
    falling through a default case") -- an int this table has never
    declared maps onto ERR_UNKNOWN here, not onto itself."""
    assert protocol.result_code(99) == protocol.Result.UNKNOWN


# ---------------------------------------------------------------------------
# GET (protocol.md Sec 6/7.1): pure delegation, no field table, no
# bounds -- the handler holds none of that; ticket 002. The fixture
# has ZERO GET blocks at all (grep protocol_golden_vectors.txt for
# "^IN GET" -- nothing), so every GET behavior below is this ticket's
# own explicit coverage, not a golden-vector un-skip.
# ---------------------------------------------------------------------------

def test_get_named_field_returns_one_get_reply():
    handler, adapter, sink = _new_handler()
    adapter.get_overrides["wheel_control.pid_kp"] = 0.03
    handler.feed(b"GET wheel_control.pid_kp #1\n")
    assert sink.lines() == ["ack 1 0", "get wheel_control.pid_kp 0.030000"]
    assert handler.malformed_count() == 0
    assert adapter.get_calls == ["wheel_control.pid_kp"]


def test_get_unknown_name_is_silent_not_malformed():
    """protocol.md Sec 6's own table note: an unknown GET name still
    gets the ack (Sec 8.1's unconditional in-order ack), but no `get`
    line and no `err` either -- and is NOT counted malformed. This is
    the one unknown-token case in the whole grammar that does not
    increment malformed_count(), distinct from every other
    unknown-name/unknown-verb case this test module otherwise covers."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"GET no.such.field #1\n")
    assert sink.lines() == ["ack 1 0"]
    assert handler.malformed_count() == 0
    assert adapter.get_calls == ["no.such.field"]


def test_get_bare_dumps_one_line_per_declared_field_in_order():
    """Bare GET (protocol.md Sec 6: "one get line per field") -- the
    Adapter's own field_count()/field_name() enumeration, in order;
    the handler holds no field list of its own."""
    handler, adapter, sink = _new_handler()
    adapter.field_names = ["wheel_control.pid_kp", "wheel_control.pid_ki"]
    adapter.get_overrides["wheel_control.pid_kp"] = 0.03
    adapter.get_overrides["wheel_control.pid_ki"] = 0.002
    handler.feed(b"GET #1\n")
    assert sink.lines() == [
        "ack 1 0",
        "get wheel_control.pid_kp 0.030000",
        "get wheel_control.pid_ki 0.002000",
    ]
    assert handler.malformed_count() == 0


def test_get_bare_skips_a_declared_field_the_adapter_cannot_answer():
    """A name the Adapter declares (via field_name()) but cannot
    currently answer (on_get() returns None for it) is skipped in the
    bare-GET dump, not emitted with a placeholder value -- mirrors
    protocol_handler.cpp's own `if (!adapter_.onGet(name, value))
    continue;`."""
    handler, adapter, sink = _new_handler()
    adapter.field_names = ["known", "unanswerable"]
    adapter.get_overrides["known"] = 1.0
    handler.feed(b"GET #1\n")
    assert sink.lines() == ["ack 1 0", "get known 1.000000"]


def test_get_wrong_arity_still_acks_before_erring():
    handler, adapter, sink = _new_handler()
    handler.feed(b"GET a b #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.get_calls == []


def test_get_clamps_nan_from_adapter_to_zero():
    """protocol.md Sec 9.4 finding 1: formatConfigValue() casting a
    NaN straight to uint32_t was undefined behavior in the C++
    archetype, reachable only through the Adapter seam (a stored
    config value that is itself NaN, read back by GET -- never through
    the wire, since parse_wire_float() already rejects NaN on the way
    in). Ported as an explicit clamp to 0.0 rather than reproducing the
    bug class."""
    handler, adapter, sink = _new_handler()
    adapter.get_overrides["weird"] = float("nan")
    handler.feed(b"GET weird #1\n")
    assert sink.lines() == ["ack 1 0", "get weird 0.000000"]


def test_get_name_that_fails_ascii_decode_is_silent_like_unknown():
    """A wire name field can be any byte except ' '/'\\n' (protocol.md
    Sec 2) -- not restricted to ASCII, even though every real
    field-table name is. A non-ASCII name can never match a real name,
    so it takes the exact same silent path as an ordinary unknown
    name (still acked, no `get` line), and the handler must not crash
    trying to decode it."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"GET \xff\xfe #1\n")
    assert sink.lines() == ["ack 1 0"]
    assert handler.malformed_count() == 0


# ---------------------------------------------------------------------------
# SET's guarded numeric-field parser (protocol.md Sec 2.2/7.2/9.4),
# ticket 002's own named findings -- underscore, embedded whitespace,
# hex-float. The fixture's own SET blocks (test_golden_vector_block,
# now unskipped) already cover the id-outcome/Result-code matrix in
# depth; these tests cover what a tidy golden vector never exercises.
# ---------------------------------------------------------------------------

def test_set_rejects_underscore_digit_separator():
    """protocol.md Sec 9.4: Python's float() accepts '_' as a digit
    group separator ('1_000' == 1000.0) -- the wire grammar has no such
    spelling at all. Guarded explicitly so this is ERR_BADARG, not a
    silently accepted value."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp 1_000 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


@pytest.mark.parametrize("byte_value", [9, 11, 12, 13], ids=["tab", "vt", "ff", "cr"])
def test_set_rejects_field_containing_disallowed_whitespace_byte(byte_value):
    """protocol.md Sec 9.4's leading-whitespace finding, generalized:
    this test is NOT covering the leading-literal-SPACE case -- that
    one is closed structurally by the tokenizer itself (a run of
    spaces is one separator, protocol.md Sec 2), so a value field can
    never begin with a literal ' ' byte at all. What this test DOES
    cover is the field grammar's own residue: '\\t'/'\\v'/'\\f'/'\\r'
    are all ordinary, legal field bytes under "any bytes except ' '
    and '\\n'", and Python's float() would silently .strip() any of
    them from either end, exactly reproducing the bug class for a
    byte set the space-grammar migration never touched."""
    handler, adapter, sink = _new_handler()
    value_field = bytes([byte_value]) + b"5.0"
    handler.feed(b"SET wheel_control.pid_kp " + value_field + b" #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_value_field_never_sees_a_literal_leading_space():
    """The structural companion to the test above: this pins that a
    run of extra spaces between SET's name and value tokens is
    absorbed by the tokenizer as ONE separator (protocol.md Sec 2), so
    the value field itself never begins with a literal ' ' byte for
    the guard to even have an opinion about -- the leading-space case
    this module's own docstrings describe as "closed structurally"."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp     5.0 #1\n")
    assert sink.lines() == ["ack 1 0"], "ok is gone -- the ack IS the acceptance"
    assert adapter.set_calls == [("wheel_control.pid_kp", 5.0, 1)]


def test_hex_float_literal_rejected_by_numeric_parser():
    """protocol.md Sec 9.4 finding 2: a hex-float literal
    ("0x1.8p3") bypassed the C++ archetype's own "no exponents" guard
    entirely -- that guard only checked for 'e'/'E', not hex-float's
    'p' exponent marker, gated behind a '0x' prefix the guard never
    looked for, so strtof silently decoded it to 12.0. A C++-only
    divergence: neither CPython's nor MicroPython's float() accepts
    hex-float syntax at all, so no additional guard code is needed
    here -- but it is pinned directly with this test so it can never
    silently regress if the parsing helper changes later (this
    ticket's own stated acceptance criterion)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp 0x1.8p3 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_rejects_decimal_exponent_notation():
    """protocol.md Sec 2: "No exponents" -- unlike the hex-float case
    above, Python's float() DOES accept plain decimal-exponent syntax
    ("1e2" == 100.0), so this guard is genuinely load-bearing, not
    merely a pin of accidental ValueError behavior."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp 1e2 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_rejects_inf_and_nan_literal_text():
    """protocol.md Sec 2: "no NaN, no inf" -- Python's float() parses
    the literal text "inf"/"nan" successfully (no exponent, no
    underscore, no stray whitespace involved), so this is checked
    post-parse via a non-finite result, the same way the C++
    archetype's own std::isnan/std::isinf calls do. Content-decode
    failures still consume a sequence slot (Sec 9.8 item 1), so the
    second command's id must advance to #2."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp inf #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    handler.feed(b"SET wheel_control.pid_kp nan #2\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1", "ack 2 0", "err 2 #2"]
    assert handler.malformed_count() == 2
    assert adapter.set_calls == []


def test_set_bad_value_with_nonzero_id_still_acks_before_erring():
    """The fixture's own bad-value block only exercises the smallest
    in-order case -- this covers the same shape with a different,
    explicit id: a malformed VALUE with an in-order id still acks
    against that id (unconditionally, before the value is even
    decoded), then layers the BADARG err on top."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp notanumber #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_id_zero_is_a_stale_retransmit_before_any_value_decode():
    """"#0" no longer suppresses anything (Sec 2.2/8.1) -- since ids
    start at 1, it always compares less than expected_next and is an
    ordinary retransmit, classified on the id ALONE before the verb
    (let alone its value field) is ever looked up. This supersedes the
    old "#0 suppresses every reply" rule this test used to pin."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp notanumber #0\n")
    assert sink.lines() == ["ack 0 0"]
    assert handler.malformed_count() == 0
    assert adapter.set_calls == []


def test_set_third_field_not_a_well_formed_id_is_malformed():
    """SET has no OTHER use for a 3rd positional field -- a token
    that is present but not '#'-shaped (or not well-formed digits)
    makes the WHOLE line malformed, not merely "SET with an id-less
    extra field" (protocol_handler.cpp's own resolveTrailingOptionalId()
    comment, ported as a design decision, not just an implementation
    detail)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp 0.03 notanid\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_wrong_arity_one_field_still_acks_before_erring():
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_wrong_arity_too_many_fields_no_recoverable_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET name value extra stuff\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_name_that_fails_ascii_decode_is_treated_as_unknown():
    """A non-ASCII name field can never match a real (always-ASCII)
    field-table name -- treated as ERR_UNKNOWN, the same code a real
    Adapter would return for any other name it does not recognize,
    rather than crashing on the decode."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET \xff\xfe 5.0 #1\n")
    assert sink.lines() == ["ack 1 0", "err 1 #1"]
    assert handler.malformed_count() == 0
    assert adapter.set_calls == []


# ---------------------------------------------------------------------------
# TLM (protocol.md Sec 6): mode decode only, no reply, no id. The
# fixture has ZERO TLM blocks at all (its own EMIT-driven telemetry
# vectors exercise emitTelemetry(), which is ticket 003's scope, not
# the TLM verb itself) -- every TLM behavior below is this ticket's own
# explicit coverage.
# ---------------------------------------------------------------------------

def test_tlm_valid_mode_persists_via_adapter_with_no_own_reply():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM POSE #1\n")
    assert sink.lines() == ["ack 1 0"]
    assert adapter.tlm_calls == ["POSE"]
    assert handler.malformed_count() == 0


@pytest.mark.parametrize(
    "mode", ["OFF", "POSE", "FULL", "NOW", "AUTO", "BUFFER"])
def test_tlm_decodes_every_documented_mode(mode):
    handler, adapter, sink = _new_handler()
    handler.feed(("TLM %s #1\n" % mode).encode("ascii"))
    assert sink.lines() == ["ack 1 0"]
    assert adapter.tlm_calls == [mode]
    assert handler.malformed_count() == 0


def test_tlm_unknown_mode_is_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM SIDEWAYS #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.tlm_calls == []


def test_tlm_mode_is_case_sensitive():
    """The mode table's names are the same uppercase-command spelling
    as every other wire token (protocol.md Sec 2.1) -- "pose" is not
    "POSE"."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM pose #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert adapter.tlm_calls == []


def test_tlm_wrong_arity_still_acks_before_erring():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM POSE EXTRA #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.tlm_calls == []


def test_tlm_bare_id_only_has_zero_mode_fields_is_wrong_arity():
    """Under mandatory sequencing the id is UNCONDITIONALLY the line's
    last token (protocol.md Sec 8.4), never content-inspected the way
    the pre-retarget optional-id design would have -- "TLM #1" is not
    "an invalid mode field that happens to recover as an id" any more;
    the id consumes the only trailing token, leaving TLM with ZERO
    mode fields, which is ordinary wrong arity (same shape as
    test_tlm_wrong_arity_still_acks_before_erring above, just with too
    FEW fields instead of too many)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.tlm_calls == []


def test_tlm_bare_no_field_at_all_has_no_recoverable_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.tlm_calls == []


# ---------------------------------------------------------------------------
# WHEELS (protocol.md Sec 5/9.1), ticket 003. Golden-vector blocks
# (now unskipped, test_golden_vector_block above) already cover the
# id-outcome/Result-code matrix; these tests cover the numeric-field
# reuse, wrong arity, and the #0-legality flip against STOP below.
# ---------------------------------------------------------------------------

def test_wheels_call_receives_parsed_numeric_fields_untouched():
    """protocol.md Sec 9.1: the handler holds no bounds table -- the
    Adapter receives left/right/duration exactly as
    parse_wire_float() decoded them, with no scaling, clamping, or
    int-casting performed here (that is ticket 005's job)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 -50 1000 #1\n")
    assert sink.lines() == ["ack 1 0"], "ok is gone -- the ack IS the acceptance"
    assert adapter.wheels_calls == [(100.0, -50.0, 1000.0, 1)]


def test_wheels_wrong_arity_two_fields_no_recoverable_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_wrong_arity_five_fields_still_acks_before_erring():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 1 2 3 4 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]  # BADARG -- known verb
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_fourth_field_not_a_well_formed_id_is_malformed():
    """WHEELS has no other use for a 4th positional field -- a token
    that is present but not '#'-shaped makes the WHOLE line
    malformed, not "WHEELS with an id-less extra field" (same call
    SET's own resolve_trailing_optional_id() use makes for its own
    3rd field)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100 1000 notanid\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_rejects_underscore_digit_separator():
    """protocol.md Sec 9.4, reused from SET's own guarded parser
    (ticket 002) rather than a second, divergent one."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 1_00 100 1000 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_rejects_hex_float_literal():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 0x1.8p3 100 1000 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_rejects_inf_and_nan_literal_text():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS inf 100 1000 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    handler.feed(b"WHEELS 100 nan 1000 #2\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1", "ack 2 0", "err 2 #2"]
    assert handler.malformed_count() == 2
    assert adapter.wheels_calls == []


def test_wheels_bad_value_with_no_id_at_all_gets_no_reply():
    """No trailing '#id' token at all -- the line is unclassifiable
    (protocol.md Sec 8.4 item 1), so there is no id to ack against and
    no reply of any kind, regardless of what the bad value field would
    otherwise have decoded to. This supersedes the pre-retarget "bare
    err, no id" shape this test used to pin -- that bare-err reply no
    longer exists at all (Sec 8.6)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS notanumber 100 1000\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_id_zero_is_a_stale_retransmit_before_any_field_decode():
    """"#0" no longer suppresses anything (Sec 2.2/8.1) -- it is an
    ordinary retransmit, classified on the id alone before WHEELS's own
    fields (valid or not) are ever looked at. This supersedes the old
    "#0 suppresses the reply" rule this test used to pin."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS notanumber 100 1000 #0\n")
    assert sink.lines() == ["ack 0 0"]
    assert handler.malformed_count() == 0
    assert adapter.wheels_calls == []


# ---------------------------------------------------------------------------
# STOP (protocol.md Sec 5.1/9.1), ticket 003.
# ---------------------------------------------------------------------------

def test_stop_bare_no_field_has_no_recoverable_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.stop_calls == []


def test_stop_wrong_arity_two_fields_still_acks_before_erring():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP #5 #1\n")
    assert sink.lines() == ["ack 1 0", "err 2 #1"]
    assert handler.malformed_count() == 1
    assert adapter.stop_calls == []


def test_stop_field_not_hash_shaped_is_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP notanid\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.stop_calls == []


def test_stop_rejected_by_adapter_still_acks_before_erring():
    """Every sequenced verb is always acked on an in-order id, rejection
    or not (protocol.md Sec 8.2) -- STOP is no longer distinguished
    from SET/WHEELS on this point the way the pre-retarget "STOP's id
    is REQUIRED, unlike every other verb" design used to frame it: ALL
    of PING/ID/VER/STATUS/HELP/GET/SET/TLM/WHEELS/STOP/RUN carry a
    mandatory id now, so there is no more asymmetry to single STOP out
    for."""
    handler, adapter, sink = _new_handler()
    adapter.stop_result = protocol.Result.BUSY
    handler.feed(b"STOP #1\n")
    assert sink.lines() == ["ack 1 0", "err 10 #1"]
    assert adapter.stop_calls == [1]


# ---------------------------------------------------------------------------
# "#0" under mandatory sequencing (protocol.md Sec 2.2/8.1, sprint 007
# ticket 013): the pre-retarget WHEELS-vs-STOP asymmetry this
# subsection used to pin ("#0" silently executes an optional-id verb
# like WHEELS but is malformed on a required-id verb like STOP) is
# GONE by design -- every sequenced verb is mandatory-id now, so there
# is no more "optional-id verb" for WHEELS to be. Since ids start at 1,
# an inbound "#0" always compares less than expected_next and is
# therefore always an ordinary retransmit (Sec 8.1): acked against the
# highest already-accepted id (0, nothing accepted yet) with the verb
# NEVER looked up or executed, for WHEELS and STOP alike. What used to
# be a deliberate asymmetry between two verb classes is now one uniform
# rule with no verb-specific carve-out at all -- tested side by side,
# same as before, so the "one deliberate fact" framing survives even
# though the fact itself flipped.
# ---------------------------------------------------------------------------

def test_wheels_hash_zero_is_a_stale_retransmit_never_executes():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100 1000 #0\n")
    assert sink.lines() == ["ack 0 0"]
    assert handler.malformed_count() == 0, "WHEELS #0 is well-formed, not malformed"
    assert adapter.wheels_calls == [], (
        "a retransmit id must never reach on_wheels() -- WHEELS #0 no "
        "longer executes at all, unlike the pre-retarget optional-id rule")


def test_stop_hash_zero_is_a_stale_retransmit_never_executes():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP #0\n")
    assert sink.lines() == ["ack 0 0"]
    assert handler.malformed_count() == 0, (
        "STOP #0 is no longer malformed -- it is an ordinary retransmit, "
        "the same as WHEELS #0 (the pre-retarget required-id/optional-id "
        "asymmetry between the two verbs is gone)")
    assert adapter.stop_calls == [], "the retransmit must never reach on_stop()"


# ---------------------------------------------------------------------------
# ESTOP (protocol.md Sec 5.1/8.3/SUC-002), ticket 003's own addition,
# flipped by ticket 012/013's 2026-08-21 retarget: confirming the
# well-formed and trailing-junk shapes both land on the SAME "estop"
# reply for the SAME underlying reason (ESTOP is maximally forgiving --
# it never inspects its own arity at all any more), not by coincidence
# of two different code paths that happen to agree. The individual
# shapes are each already covered above (test_estop_replies_estop_
# after_executing / test_estop_wrong_arity_still_replies_estop /
# test_estop_with_trailing_id_still_just_replies_estop) -- this test is
# the side-by-side confirmation ticket 003 originally called for, now
# re-pinned to the reply-flip rather than the silence it used to pin.
# ---------------------------------------------------------------------------

def test_estop_wellformed_and_with_trailing_junk_both_reply_estop_for_the_same_reason():
    handler, adapter, sink = _new_handler()

    handler.feed(b"ESTOP\n")  # well-formed
    assert sink.lines() == ["estop"]
    assert adapter.estop_calls == 1
    assert handler.malformed_count() == 0

    handler.feed(b"ESTOP #5\n")  # trailing junk: an id-shaped extra field
    assert sink.lines() == ["estop", "estop"], (
        "ESTOP must reply 'estop' again, unconditionally, even though "
        "'#5' looks like a well-formed id every OTHER verb would ack")
    assert adapter.estop_calls == 2, "the second ESTOP must also have executed"
    assert handler.malformed_count() == 0, (
        "ESTOP never increments malformed_count() -- there is no arity "
        "to inspect at all any more (resolved ambiguity #3)")


# ---------------------------------------------------------------------------
# emit_telemetry() (protocol.md Sec 5.2/6.2), ticket 003: thdr once /
# thdr again on column-set change / t every call, and per-handler-
# instance isolation. The fixture's own multi-frame EMIT block (now
# unskipped, test_golden_vector_block above) covers the literal spec
# S6.2 worked example; these tests cover header-change detection in
# more depth than that one fixture block does.
#
# 2026-08-21 retarget (Sec 8.5): emit_telemetry() now ALSO piggybacks
# the current reliability line -- "ack <expected_next-1> <last_done>"
# when no gap is outstanding, else "nack <expected_next> <last_done>"
# -- on every call, AFTER the thdr/t frame it accompanies (Sec 9.8 item
# 5). None of these tests ever feed() a sequenced command, so
# expected_next stays 1 and last_done stays 0 throughout: every call
# below piggybacks the same "ack 0 0" line.
# ---------------------------------------------------------------------------

_COLUMNS_A = [("seq", 1, False), ("flags", 216, True)]
_COLUMNS_A_AGAIN = [("seq", 2, False), ("flags", 8, True)]  # same names/hex, new values


def test_emit_telemetry_sends_thdr_once_then_t_every_call():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry(_COLUMNS_A)
    handler.emit_telemetry(_COLUMNS_A_AGAIN)
    handler.emit_telemetry(_COLUMNS_A_AGAIN)
    assert sink.lines() == [
        "thdr seq flags",
        "t 1 d8",
        "ack 0 0",
        "t 2 8",
        "ack 0 0",
        "t 2 8",
        "ack 0 0",
    ]


def test_emit_telemetry_resends_thdr_when_column_count_changes():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry(_COLUMNS_A)
    handler.emit_telemetry([("seq", 3, False)])  # one column dropped
    assert sink.lines() == [
        "thdr seq flags",
        "t 1 d8",
        "ack 0 0",
        "thdr seq",
        "t 3",
        "ack 0 0",
    ]


def test_emit_telemetry_resends_thdr_when_column_name_changes():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry(_COLUMNS_A)
    handler.emit_telemetry([("seq", 3, False), ("otherflags", 1, True)])
    assert sink.lines() == [
        "thdr seq flags",
        "t 1 d8",
        "ack 0 0",
        "thdr seq otherflags",
        "t 3 1",
        "ack 0 0",
    ]


def test_emit_telemetry_resends_thdr_when_hex_flag_changes():
    """Same names, same count, only a column's hex-ness flips -- the
    C++ archetype's own headerChanged() compares hex per-column
    explicitly, independent of the name compare, so this must trigger
    a fresh thdr on its own, not just when a name differs."""
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry(_COLUMNS_A)
    handler.emit_telemetry([("seq", 5, True), ("flags", 216, True)])
    assert sink.lines() == [
        "thdr seq flags",
        "t 1 d8",
        "ack 0 0",
        "thdr seq flags",
        "t 5 d8",
        "ack 0 0",
    ]


def test_emit_telemetry_header_state_is_per_handler_instance_not_shared():
    """sprint.md's Design Rationale: one ProtocolHandler per transport,
    each with its own independent thdr-once-per-subscriber tracking --
    two freshly constructed instances receiving the identical column
    set must EACH emit their own thdr once; neither's remembered header
    state may leak into the other."""
    handler_a, _adapter_a, sink_a = _new_handler()
    handler_b, _adapter_b, sink_b = _new_handler()

    handler_a.emit_telemetry(_COLUMNS_A)
    handler_a.emit_telemetry(_COLUMNS_A_AGAIN)
    assert sink_a.lines() == [
        "thdr seq flags", "t 1 d8", "ack 0 0", "t 2 8", "ack 0 0"]

    # handler_b has never emitted before -- even though handler_a has
    # already "seen" this exact column set, handler_b's own thdr is
    # still due, proving the state is not shared module-level state.
    handler_b.emit_telemetry(_COLUMNS_A)
    assert sink_b.lines() == ["thdr seq flags", "t 1 d8", "ack 0 0"]


def test_emit_telemetry_decimal_column_formats_signed_no_hex():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry([("x", -1234, False), ("y", 892, False)])
    assert sink.lines() == ["thdr x y", "t -1234 892", "ack 0 0"]


def test_emit_telemetry_hex_column_formats_lowercase_no_prefix():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry([("flags", 4096, True)])
    assert sink.lines() == ["thdr flags", "t 1000", "ack 0 0"]


# ---------------------------------------------------------------------------
# Embedded-NUL divergence (protocol.md Sec 9.4's characterization finding,
# ticket 004's own named acceptance criterion): the C++ archetype's
# strcmp()-based -- and, post grammar-migration, its NUL-terminated-
# C-string tokenizer scan -- both stop at the first embedded NUL byte, so
# `PING\x00extra\n` is indistinguishable from a bare `PING\n` to that
# implementation: it dispatches as PING (reply `pong 0`), silently
# discarding "extra". Spec Sec 2's verb grammar (`verb ::= [A-Za-z]
# [A-Za-z0-9_]*`) admits no NUL at all, so the GRAMMAR-CORRECT behavior
# is to reject this line as unparseable -- the C++ implementation's
# C-string-comparison behavior is a characterization artifact of its own
# storage representation, not something this port re-derives or
# reproduces.
#
# Python `bytes` equality is length- and content-aware (embedded NUL
# bytes included) -- `b"PING\x00extra" == b"PING"` is `False` -- so this
# port naturally takes the grammar-correct path with NO special-case
# code: the whole line tokenizes to the single token
# b"PING\x00extra" (no space anywhere in it), which fails every
# VERB_TABLE comparison in `_dispatch()`, falls through to the
# unknown-verb path, and is counted malformed. There being only one
# token on the line (no space), there is no separate trailing field for
# the malformed-line `#id`-recovery rule to find, so this specific input
# also gets no reply -- opposite of the C++ archetype's `pong 0`, and
# THIS divergence is deliberate, not a gap: it is this test's whole
# point, not an accident of the reply-shape rule.
# ---------------------------------------------------------------------------

def test_embedded_nul_immediately_after_verb_is_rejected_not_truncated():
    """Pins the deliberate divergence from
    test_embedded_nul_immediately_after_verb_matches_bare_verb in
    radio-robot-lib's tests/protocol/test_protocol_adversarial.py (read
    there for the C++ characterization this test's docstring
    contrasts with). That test asserts the C++ archetype's `feed()`
    equivalent treats `PING\x00extra\n` exactly like `PING\n` and
    replies `pong 0\n` -- a C-string-comparison artifact, NOT
    grammar-correct behavior (spec Sec 2's verb grammar admits no NUL
    byte at all). THIS test asserts the opposite outcome for the
    IDENTICAL input bytes: this Python port's `bytes`-based, length-
    and content-aware comparison can never match `PING\x00extra`
    against the table entry `b"PING"`, so the line is rejected as an
    unknown verb -- counted malformed, and (since there is no separate
    `#id` token on this particular line to recover) no reply at all,
    rather than the C++ archetype's silent `pong 0` truncation.

    This is a divergence test PINNING correct Python behavior, not a
    port of the C++ characterization test -- it does not reproduce the
    C++ bug, and it must never be "fixed" to match the C++ output."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"PING\x00extra\n")
    assert sink.lines() == [], (
        "must NOT have dispatched as a bare PING (the C++ archetype's "
        "own truncation bug) -- Python bytes comparison is length-aware, "
        "so b'PING\\x00extra' can never match the VERB_TABLE's b'PING' "
        "entry")
    assert adapter.now_calls == 0, (
        "on_ping()'s only observable adapter call (now()) must never "
        "have fired -- confirms this took the unknown-verb path, not "
        "the PING handler, not merely that the reply text happened to "
        "come out empty")
    assert handler.malformed_count() == 1

    # The recovery invariant (matches every other malformed-line case in
    # this suite): a clean, in-order PING right after must still
    # dispatch normally -- this one deliberately-malformed line must
    # not have wedged the handler's parse state.
    adapter.now_value = 999
    handler.feed(b"PING #1\n")
    assert sink.lines() == ["ack 1 0", "pong 999"]


def test_embedded_nul_immediately_after_verb_with_an_in_order_id_gets_ack_then_err_unknown():
    """The companion shape to the test above, added by sprint 007
    ticket 013's own reconciliation: under mandatory sequencing (Sec
    8.4) the id is unconditionally the line's LAST token, extracted
    before verb lookup ever runs -- so "PING\\x00extra #1" has a
    perfectly well-formed, in-order id ("#1") even though its verb
    token still cannot match VERB_TABLE's b"PING" entry for the exact
    same length-aware-comparison reason as the no-id case above. The
    ack fires unconditionally on the in-order id, THEN the unknown-verb
    err layers on top -- this is the "ack + err 1" outcome the ticket's
    own description calls out, distinct from the no-id case's "no reply
    at all"."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"PING\x00extra #1\n")
    assert sink.lines() == ["ack 1 0", "err 1 #1"]
    assert adapter.now_calls == 0, (
        "must have taken the unknown-verb path, not the PING handler")
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# Adversarial-input hardening, ported from radio-robot-lib's
# tests/protocol/test_protocol_adversarial.py (ticket 004's own
# instruction to port adversarial cases applicable to a Python handler
# that tickets 001-003's tests don't already cover). That file's own
# job is proving the C++ archetype's feed() never crashes, overflows, or
# traps under ASan/UBSan on hostile bytes, AND that a well-formed line
# right after any garbage still dispatches correctly (the "recovery
# invariant" -- a handler that wedges after one bad frame is useless on
# a lossy radio link).
#
# The memory-safety half of that file's own three-part job (point 1 in
# its module docstring: "never crashes... demonstrated here [under
# ASan/UBSan], not asserted") does NOT port here at all -- there is no
# sanitizer-instrumented executable to link against, and Python has no
# buffer-overflow/use-after-free/UB hazard class for a
# bytearray-and-list-based parser to fall into in the first place (this
# module's own docstring: no fixed-size field-token array, no
# kMaxHeaderColumns cap). What DOES port, unchanged, is the RECOVERY
# INVARIANT itself: however hostile the input, `feed()` must never raise
# an uncaught exception, and a subsequent well-formed `PING` must still
# dispatch correctly. Every RUN_* case from that file is dropped
# entirely -- RUN is not ported in this sprint at all (this port's own
# module docstring), so there is no handler behavior for those cases to
# characterize.
# ---------------------------------------------------------------------------

_ADVERSARIAL_RECOVERY_CASES = [
    # ---- embedded NUL bytes mid-line, beyond the dedicated divergence
    # test above -- these exercise NUL surviving through FIELD content
    # (name/value decoding), not just verb lookup.
    ("embedded_nul_mid_verb", [b"PI\x00NG\n"]),
    ("embedded_nul_in_set_name", [b"SET foo\x00bar 1.0\n"]),
    ("embedded_nul_in_set_value", [b"SET group.alpha 1\x002 #9\n"]),
    ("embedded_nul_in_wheels_field", [b"WHEELS 1\x0000 100 1000\n"]),
    ("embedded_nul_in_get_name", [b"GET foo\x00bar\n"]),
    ("embedded_nul_in_id", [b"STOP #1\x002\n"]),

    # ---- 8-bit / high-ASCII and UTF-8 sequences ----
    ("high_ascii_full_line", [bytes(range(0x80, 0x100)) + b"\n"]),
    ("high_ascii_verb", [bytes([0xC0, 0xC1, 0xFE, 0xFF]) + b"\n"]),
    ("utf8_verb", ["日本語".encode("utf-8") + b"\n"]),
    ("utf8_in_set_value",
     [b"SET " + "日本語".encode("utf-8") + b" 1.0\n"]),
    ("utf8_in_get_name",
     [b"GET " + "éèê\U0001F600".encode("utf-8") + b"\n"]),

    # ---- other control characters ----
    ("c0_control_chars_full_line",
     [bytes(b for b in range(1, 32) if b not in (0x0A,)) + b"\n"]),
    ("del_byte_full_line", [b"\x7f\n"]),
    ("del_byte_in_set_value", [b"SET group.alpha 1\x7f0\n"]),
    ("bell_and_escape_in_verb", [b"P\x07I\x1bNG\n"]),

    # ---- very long runs of '#' / hash-only lines / trailing hashes --
    # the space grammar's own special byte (the id marker) ----
    ("very_long_hash_run", [b"#" * 300 + b"\n"]),
    ("line_only_hashes_short", [b"###\n"]),
    ("line_only_hashes_long", [b"#" * 238 + b"\n"]),
    ("verb_directly_followed_by_hashes_no_space",
     [b"PING" + b"#" * 50 + b"\n"]),
    ("known_verb_directly_followed_by_hashes_no_space",
     [b"STOP" + b"#" * 100 + b"\n"]),
    ("known_verb_space_then_long_non_digit_hash_field",
     [b"STOP " + b"#" * 100 + b"\n"]),
    ("bare_hash_as_id_no_digits", [b"STOP #\n"]),
    ("hash_then_non_digit", [b"STOP #x\n"]),
    ("hash_with_leading_plus", [b"STOP #+5\n"]),
    ("hash_with_leading_minus", [b"STOP #-5\n"]),
    ("multiple_hash_tokens_last_one_wins", [b"STOP #5 #7\n"]),
    ("huge_digit_run_after_hash_overflows_uint32",
     # Python ints have no width to overflow -- unlike the C++
     # archetype, this parses to one (very large) legitimate nonzero
     # id rather than characterizing a wraparound. Ported anyway for
     # the same reason every other case here is: it must not crash and
     # must not wedge the parser, whatever it decides the id means.
     [b"STOP #" + b"9" * 300 + b"\n"]),

    # ---- space-run stress: the grammar's own separator, hammered ----
    ("huge_space_run_between_fields",
     [b"WHEELS 100" + b" " * 200 + b"100 1000\n"]),
    ("many_spaces_then_nothing_is_blank", [b" " * 239 + b"\n"]),
    ("verb_alone_no_trailing_content", [b"WHEELS\n"]),
    ("verb_then_trailing_spaces_only", [b"WHEELS" + b" " * 50 + b"\n"]),
    ("stop_alone_no_id", [b"STOP\n"]),
    ("stop_then_trailing_spaces_only", [b"STOP" + b" " * 50 + b"\n"]),

    # ---- empty lines / blank-line runs ----
    ("empty_line", [b"\n"]),
    ("three_empty_lines", [b"\n\n\n"]),
    ("many_empty_lines", [b"\n" * 20]),
    ("mixed_blank_and_whitespace_lines", [b"\n   \n\t\n \n"]),

    # ---- \r handling: lone \r, \r\n, \n\r ----
    ("crlf", [b"\r\n"]),
    ("lfcr", [b"\n\r"]),
    ("cr_mid_field_not_at_terminator", [b"WHEELS \r100 100 1000\n"]),
    ("multiple_lone_cr_mid_line", [b"PING\r\r\r\n"]),

    # ---- lines at/around the 240-byte cap, beyond the two dedicated
    # boundary tests above (this sweep's own point: recovery, not just
    # the exact malformed_count()/reply-shape those tests already
    # pin) ----
    ("line_content_238_total_239_under_cap", [b"Z" * 238 + b"\n"]),
    ("line_content_239_total_240_exact_cap", [b"Z" * 239 + b"\n"]),
    ("line_content_240_total_241_over_cap", [b"Z" * 240 + b"\n"]),
    ("line_content_1000_way_over_cap", [b"Z" * 1000 + b"\n"]),

    # ---- unterminated: partial lines, huge no-terminator blobs, spread
    # across multiple feed() calls ----
    ("unterminated_short_fragment", [b"WHEELS 100 100"]),
    ("unterminated_lone_cr", [b"\r"]),
    ("unterminated_4kb_single_call", [b"A" * 4096]),
    ("unterminated_plausible_prefix_then_huge_continuation",
     [b"WHEELS 100 100 1000", b"B" * 5000]),
    ("unterminated_split_across_many_small_calls",
     [b"W", b"H", b"E", b"E", b"L", b"S", b" ", b"1" * 300]),

    # ---- mixed-case / case-as-direction edge cases ----
    ("all_lowercase_verb_dropped", [b"ping\n"]),
    ("mixed_case_verb_unknown", [b"Wheels 100 100 1000\n"]),
    ("lowercase_verb_with_spaces_and_high_bytes",
     [b"dbg " + bytes(range(0x80, 0x90)) + b"\n"]),

    # ---- numeric-field adversarial spellings ----
    ("wheels_field_all_pluses", [b"WHEELS +100 +100 +1000\n"]),
    ("wheels_field_leading_zeros", [b"WHEELS 000100 00100 0001000\n"]),
    ("set_value_only_a_sign", [b"SET group.alpha -\n"]),
    ("set_value_only_a_dot", [b"SET group.alpha .\n"]),
    ("set_value_many_dots", [b"SET group.alpha 1.2.3.4\n"]),
    ("wheels_duration_huge_digit_run",
     [b"WHEELS 100 100 " + b"9" * 40 + b"\n"]),

    # ---- non-space whitespace bytes as a field's LEADING byte -- the
    # hazard that survives the space-grammar migration (a literal
    # leading ' ' is structurally impossible; '\t'/'\v'/'\f'/'\r' remain
    # legal, ordinary field bytes per the field grammar) ----
    ("tab_leading_wheels_field", [b"WHEELS \t100 100 1000\n"]),
    ("vtab_leading_set_value", [b"SET group.alpha \v1.0\n"]),
    ("formfeed_leading_wheels_duration", [b"WHEELS 100 100 \f1000\n"]),
    ("cr_leading_set_value_not_at_terminator",
     [b"SET group.alpha \r1.0\n"]),
]


def _adversarial_recovery_ids():
    return [name for name, _chunks in _ADVERSARIAL_RECOVERY_CASES]


@pytest.mark.parametrize(
    "name,chunks", _ADVERSARIAL_RECOVERY_CASES, ids=_adversarial_recovery_ids())
def test_recovers_after_adversarial_input(name, chunks):
    """The recovery invariant (protocol.md Sec 2/2.1), ported from
    radio-robot-lib's own test_recovers_after_adversarial_input: however
    hostile `chunks` is, `feed()` must (a) never raise an uncaught
    exception and (b) still dispatch a clean, in-order PING correctly
    once the garbage line is closed out with a plain '\\n' -- a handler
    that wedges after one bad frame is useless on a lossy radio link.
    None of these cases ever produces a legitimate, in-order sequenced
    command (every one is either unclassifiable, out-of-order, or
    otherwise malformed -- audited case by case for sprint 007 ticket
    013's own reconciliation), so `expected_next` is still 1 on a fresh
    handler by the time the recovery probe runs, for every case
    uniformly -- "PING #1" is always in order here. If `feed()` itself
    raises, this test fails with that exception's own traceback rather
    than a clean assertion message -- that failure mode IS the point of
    this test, not a bug in it."""
    handler, adapter, sink = _new_handler()
    adapter.now_value = 0
    for chunk in chunks:
        handler.feed(chunk)
    # A bare '\n' first closes out whatever partial/overflowing line the
    # adversarial chunks left pending, so PING below arrives as its own
    # clean line -- matches radio-robot-lib's own module docstring
    # rationale for why the recovery command is not concatenated
    # directly onto an unterminated garbage prefix.
    handler.feed(b"\n")
    handler.feed(b"PING #1\n")
    assert sink.lines()[-2:] == ["ack 1 0", "pong 0"], (
        "case %r: PING after the garbage did not produce the expected "
        "reply -- handler did not recover; sink had %r"
        % (name, sink.lines()))


def test_recovers_after_every_adversarial_input_in_one_session():
    """Companion to the per-case sweep above, ported from
    radio-robot-lib's own test_recovers_after_every_adversarial_input_
    in_one_session: ALL adversarial cases, back-to-back, on ONE handler
    instance (rather than a fresh handler per case) -- the failure mode
    a per-case sweep cannot see is state leaking or accumulating badly
    enough across many bad lines that some LATER, unrelated line
    misdispatches. A PING is interleaved after every case; every one
    must come back clean, and the total count must match exactly (a
    deficit means some PING got lost; a surplus means a "malformed"
    case actually dispatched as PING when it should not have). None of
    the adversarial cases ever legitimately advances the sequence (same
    per-case audit as the test above), so on this ONE shared handler
    the recovery PING's own id must climb by one per case (#1, #2,
    #3, ...) -- each recovery PING is the only thing in the whole
    session that ever successfully advances `expected_next`."""
    handler, adapter, sink = _new_handler()
    adapter.now_value = 0
    for case_index, (_name, case_chunks) in enumerate(_ADVERSARIAL_RECOVERY_CASES):
        for chunk in case_chunks:
            handler.feed(chunk)
        handler.feed(b"\n")
        handler.feed(("PING #%d\n" % (case_index + 1)).encode("ascii"))
    pong_count = sink.lines().count("pong 0")
    assert pong_count == len(_ADVERSARIAL_RECOVERY_CASES), (
        "expected %d pong replies (one recovery PING per case), got %d "
        "-- a PING somewhere in the session did not come back, so state "
        "from an earlier case corrupted a later one"
        % (len(_ADVERSARIAL_RECOVERY_CASES), pong_count))


# ---------------------------------------------------------------------------
# ticket 012 (2026-08-21 retarget): new reliability-layer tests. These
# cover what the new fixture (protocol_golden_vectors_reliability.txt)
# cannot prove on its own -- the fixture only sees the SINK's wire
# output, not the mock adapter's own call counts, so the acceptance
# criterion "a resent WHEELS must not drive the wheels twice" (and its
# gap-side counterpart, "a gapped WHEELS must not execute at all")
# needs its own hand-written assertion against wheels_calls. Everything
# else in this section either exercises a call-count the fixture can't
# see, or a wire-shape corner the mechanically-derived fixture vectors
# did not happen to cover.
#
# Unlike every OTHER section above, this one is NOT ticket 013's to
# reconcile -- it is this ticket's own new coverage for its own new
# behavior, not a pin of the pre-retarget scheme.
# ---------------------------------------------------------------------------

def test_retransmit_does_not_redrive_the_wheels():
    """protocol.md Sec 8.1's own named hazard: "a resent WHEELS ...
    must NOT drive the wheels a second time." Resending the SAME
    already-accepted id must reach on_wheels() exactly once, with the
    second (retransmit) reply echoing the highest already-accepted id,
    not the resent one."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100 1000 #1\n")
    assert sink.lines() == ["ack 1 0"]
    assert adapter.wheels_calls == [(100.0, 100.0, 1000.0, 1)]
    sink.clear()

    handler.feed(b"WHEELS 100 100 1000 #1\n")  # the exact same line again
    assert sink.lines() == ["ack 1 0"], (
        "a retransmit's ack must echo the highest ALREADY-accepted id "
        "(expected_next - 1), not advance the sequence again")
    assert adapter.wheels_calls == [(100.0, 100.0, 1000.0, 1)], (
        "on_wheels() must have been called exactly ONCE -- the retransmit "
        "must not have re-executed the command")


def test_gap_does_not_execute_the_wheels_at_all():
    """The gap branch's own rule (Sec 8.1): "do NOT execute" -- an
    out-of-order id must never reach the Adapter, not even once."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100 1000 #5\n")  # expected_next is 1
    assert sink.lines() == ["nack 1 0"]
    assert adapter.wheels_calls == [], (
        "a gapped id must never reach on_wheels() at all")


def test_gap_then_retransmit_of_the_gapped_id_still_does_not_execute():
    """Once a gap is filled and the sequence has moved on, the id that
    ONCE would have been in order is now itself a stale retransmit --
    still must never execute, and still echoes the (by-then) highest
    accepted id."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 1 1 1 #1\n")  # in order, executes
    handler.feed(b"WHEELS 2 2 2 #2\n")  # in order, executes
    sink.clear()

    handler.feed(b"WHEELS 3 3 3 #1\n")  # long-stale retransmit of #1
    assert sink.lines() == ["ack 2 0"]
    assert adapter.wheels_calls == [
        (1.0, 1.0, 1.0, 1),
        (2.0, 2.0, 2.0, 2),
    ], "the stale id must not have produced a third on_wheels() call"


def test_estop_never_increments_malformed_count():
    """Resolved ambiguity #3 (this ticket's own record): ESTOP inspects
    nothing about its own line under the 2026-08-21 forgiveness rule,
    so there is no wrong-arity case left to count -- unlike the
    pre-retarget behavior this supersedes (which still bumped
    malformed_count() on a trailing-field ESTOP)."""
    handler, adapter, sink = _new_handler()
    for line in (b"ESTOP\n", b"ESTOP 1 2 3\n", b"ESTOP #5\n", b"ESTOP #abc\n"):
        handler.feed(line)
    assert handler.malformed_count() == 0
    assert sink.lines() == ["estop"] * 4
    assert adapter.estop_calls == 4


def test_send_debug_strips_embedded_newline_and_carriage_return():
    """protocol.md Sec 6.2: '\\n'/'\\r' are STRIPPED (removed, not just
    trimmed from the ends) so free text can never forge a second line
    onto the wire -- this is the one sanitization case the text-based
    fixture format cannot itself spell (a fixture line cannot contain a
    literal embedded newline)."""
    handler, adapter, sink = _new_handler()
    handler.send_debug("line one\nline two\r\nstill one line")
    assert sink.lines() == ["debug line oneline twostill one line"]


def test_send_debug_none_and_text_that_sanitizes_to_nothing_are_the_same_bare_line():
    handler, adapter, sink = _new_handler()
    handler.send_debug(None)
    handler.send_debug("")
    handler.send_debug("\n\r\n\r")  # sanitizes down to the empty string
    assert sink.lines() == ["debug", "debug", "debug"]


def test_run_ret_value_is_sanitized_and_truncated_like_debug_text():
    """RUN's returned value gets the SAME treatment send_debug()'s text
    does (protocol.md Sec 6.3): '\\n'/'\\r' stripped, whole line
    truncated (never overflowed) to the 240-byte cap."""
    handler, adapter, sink = _new_handler()
    adapter.run_result = protocol.Result.OK
    adapter.run_value = "has\na\rnewline"
    adapter.run_has_value = True
    handler.feed(b"RUN echo #1\n")
    assert sink.lines() == ["ack 1 0", "ret hasanewline #1"]

    sink.clear()
    long_value = "X" * 300
    adapter.run_value = long_value
    handler.feed(b"RUN echo #2\n")
    lines = sink.lines()
    assert lines[0] == "ack 2 0"
    ret_line = lines[1]
    assert len(ret_line) <= protocol.MAX_LINE_BYTES - 1, (
        "the formatted ret line must be truncated to fit the 240-byte "
        "cap including its trailing newline")
    assert ret_line.startswith("ret " + "X" * 10)
