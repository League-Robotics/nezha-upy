"""tests/unit/test_protocol_golden_vectors.py -- ticket 001 gate:
``src/core/protocol.py``'s ``ProtocolHandler`` against
``tests/fixtures/protocol_golden_vectors.txt`` (radio-robot-lib's own
cross-language conformance fixture, copied verbatim), plus explicit
unit tests for what a tidy golden vector never exercises.

Shape ported from radio-robot-lib's
``tests/protocol/test_protocol_harness.py`` -- two kinds of coverage,
same as there:

1. ``test_golden_vector_block`` drives every block in the fixture
   through ``ProtocolHandler`` + a mock Adapter/Sink and asserts the
   sink's captured output line-for-line. Blocks this sprint's reduced
   verb scope does not (or does not yet) implement are marked
   ``pytest.mark.skip`` per-block, with a reason naming the verb and
   which ticket (if any) implements it -- see ``_classify()`` below.
   Session verbs (HELLO/PING/ID/VER/STATUS/HELP), ``ESTOP``, and every
   malformed-line-recovery vector (unknown verb, wrong arity, the
   `#id` recovery rule, the lowercase-verb drop) run for real.

2. The individual ``test_*`` functions below cover ``feed()``'s
   byte-block-boundary contract, the 240-byte overflow-discard rule,
   blank/all-whitespace-line silence, the malformed-line ``#id``
   recovery rule in more depth than the fixture alone provides, and
   ``HELP``'s "generated from the dispatch table" guarantee.

Run with::

    python3 -m pytest tests/unit/test_protocol_golden_vectors.py -v
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = _REPO_ROOT / "src"
_THIS_DIR = Path(__file__).resolve().parent
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "protocol_golden_vectors.txt"

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
    """Pinned so a future re-sync of the fixture (or an accidental
    change to the parser) shows up as a deliberate diff here, not a
    silent drop. Recount if protocol_golden_vectors.txt is re-synced
    from radio-robot-lib with new vectors."""
    assert len(_BLOCKS) == 43


# ---------------------------------------------------------------------------
# Classify each block by the verb (or action kind) it exercises, so
# blocks outside this ticket's -- or this sprint's -- scope are marked
# skip cleanly, by verb, rather than deleted from the fixture-driven
# run. See this module's own docstring and src/core/protocol.py's for
# the sprint-scope rationale (RUN/debug never ported at all;
# GET/SET/TLM/WHEELS/STOP deferred to tickets 002/003).
# ---------------------------------------------------------------------------

_OUT_OF_SPRINT_SCOPE_VERBS = (b"RUN",)


def _classify(block):
    """Returns ``(action, reason)`` -- ``action`` is ``"run"`` or
    ``"skip"``; ``reason`` is ``None`` for ``"run"``, else a str
    explaining why.

    Ticket 003 un-skips WHEELS/STOP (real bodies land in this ticket)
    and every EMIT-driven telemetry block (``emit_telemetry()`` is
    this ticket's scope too) -- only RUN, the RUN-listing HELP vector,
    and DEBUG (robot-to-host-only, never ported at all, per this
    sprint's own scope) stay skipped, permanently."""
    kinds = set(kind for kind, _payload in block.actions)
    if "DEBUG" in kinds:
        return "skip", (
            "sendDebug()/the robot-to-host `debug` emission is outside "
            "this sprint's verb scope -- never ported (see "
            "src/core/protocol.py's own docstring)")

    in_actions = [payload for kind, payload in block.actions if kind == "IN"]
    if in_actions:
        stripped = in_actions[0].strip(" ")
        verb_text = stripped.split(" ", 1)[0] if stripped else ""
        verb_bytes = verb_text.encode("ascii")

        if verb_bytes in _OUT_OF_SPRINT_SCOPE_VERBS:
            return "skip", (
                "RUN is outside this sprint's verb scope entirely "
                "(sprint.md's 'In Scope' verb list omits it) -- never ported")
        if verb_text == "HELP" and "RUN" in block.expected_out[0].split(" "):
            return "skip", (
                "this fixture's HELP vector lists RUN because "
                "radio-robot-lib's own archetype implements 13 verbs; this "
                "sprint implements only the 12 verbs sprint.md scopes in, "
                "so HELP's correct text here has no RUN -- pinned directly "
                "by test_help_lists_every_verb_this_sprint_scopes_including_stubs "
                "below instead of via this fixture block")

    # EMIT-only blocks (no "IN" action at all) fall through to here and
    # run for real -- emit_telemetry() is ticket 003's scope.
    return "run", None


def test_golden_vector_classification_counts():
    """Pinned split so a change to _classify() (or a fixture re-sync)
    is visible as a deliberate count change, not a silent drift in how
    much of the fixture this ticket actually exercises. Ticket 002
    moved the fixture's 12 SET blocks from skip to run: 12 (ticket 001)
    + 12 (SET, ticket 002) = 24 run, 31 - 12 = 19 skip. Ticket 003 moves
    4 WHEELS blocks + 3 STOP blocks + 1 multi-frame EMIT block from skip
    to run: 24 + 8 = 32 run, 19 - 8 = 11 skip (2 DEBUG + 8 RUN + 1
    RUN-listing HELP block, all permanently skipped -- RUN/debug are
    never ported at all, per this sprint's own verb scope)."""
    run_count = sum(1 for b in _BLOCKS if _classify(b)[0] == "run")
    skip_count = sum(1 for b in _BLOCKS if _classify(b)[0] == "skip")
    assert run_count == 32
    assert skip_count == 11
    assert run_count + skip_count == len(_BLOCKS)


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
    else:
        raise ValueError(
            "SETUP key %r not recognized by this ticket's mock adapter -- "
            "if this fired for a block _classify() marked \"run\", either "
            "the classifier or the mock adapter needs to grow to match" % (key,))


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
        else:
            raise ValueError(
                "action kind %r not supported by this ticket's runner -- "
                "DEBUG blocks are always classified \"skip\"" % (kind,))
    return sink.lines()


_PARAMS = []
for _index, _block in enumerate(_BLOCKS):
    _action, _reason = _classify(_block)
    _marks = [pytest.mark.skip(reason=_reason)] if _action == "skip" else []
    _PARAMS.append(pytest.param(_index, _block, id="block%02d" % _index, marks=_marks))


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
    handler.feed(b"PING\nPING\nPING\n")
    assert adapter.now_calls == 3
    assert sink.lines() == ["pong 111"] * 3
    assert handler.malformed_count() == 0


def test_feed_block_ending_mid_line_buffers_the_remainder():
    handler, adapter, sink = _new_handler()
    adapter.now_value = 222
    handler.feed(b"PI")
    assert sink.lines() == [], "dispatched before the line completed"
    assert adapter.now_calls == 0
    handler.feed(b"NG\n")
    assert sink.lines() == ["pong 222"]
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
    handler.feed(b"PING\r\n")
    assert sink.lines() == ["pong 333"]
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
    handler.feed(b"PING\n")
    assert sink.lines() == ["pong 444"]


def test_feed_exactly_240_bytes_is_accepted():
    """Boundary companion to the overflow test above: a line whose
    TOTAL wire length (content + '\\n') is exactly 240 bytes -- Sec 2's
    own stated maximum -- must be accepted and dispatched normally, not
    discarded. Built on an unknown verb with a recoverable id (rather
    than a verb this ticket's own stub bodies don't observably act on)
    so the assertion below (a real reply) is proof the line was
    processed, not silently swallowed by the overflow path -- overflow
    never replies."""
    handler, adapter, sink = _new_handler()
    padding = b"X" * 232
    line = b"FOO " + padding + b" #7"
    assert len(line) + 1 == 240
    handler.feed(line + b"\n")
    assert handler.malformed_count() == 1
    assert sink.lines() == ["err #7 1"]


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
    handler.feed(b"PING\n")
    assert sink.lines() == ["pong 666"]


def test_all_whitespace_line_is_silently_ignored_not_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"     \n")  # spaces only, no verb at all
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    adapter.now_value = 777
    handler.feed(b"PING\n")
    assert sink.lines() == ["pong 777"]


# ---------------------------------------------------------------------------
# A run of spaces is ONE separator; leading/trailing line whitespace is
# ignored (protocol.md Sec 2).
# ---------------------------------------------------------------------------

def test_space_run_between_fields_is_one_separator():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO   1   2   3   #9\n")
    assert sink.lines() == ["err #9 1"]
    assert handler.malformed_count() == 1


def test_leading_and_trailing_line_whitespace_is_ignored():
    handler, adapter, sink = _new_handler()
    adapter.now_value = 888
    handler.feed(b"   PING   \n")
    assert sink.lines() == ["pong 888"]
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

    handler.feed(b"ok #5\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 0

    adapter.now_value = 555
    handler.feed(b"PING\n")
    assert sink.lines() == ["pong 555"]


def test_mixed_case_verb_is_unknown_not_dropped():
    handler, adapter, sink = _new_handler()
    handler.feed(b"Ping\n")  # starts uppercase, not the literal PING
    assert sink.lines() == []
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# Unknown verb / wrong arity, and the malformed-line #id recovery rule
# (protocol.md Sec 2.3): "if the line's last token is a well-formed
# nonzero #id, reply err #<id> <code> -- including unknown verbs."
# ---------------------------------------------------------------------------

def test_unknown_verb_no_reply_when_no_recoverable_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1

    handler.feed(b"FOO 1 2 3\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 2


def test_unknown_verb_with_recoverable_id_gets_err_unknown():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO 1 2 3 #42\n")
    assert sink.lines() == ["err #42 1"]
    assert handler.malformed_count() == 1
    sink.clear()

    handler.feed(b"BAR #7\n")
    assert sink.lines() == ["err #7 1"]
    assert handler.malformed_count() == 2


def test_unknown_verb_trailing_id_zero_gets_no_reply():
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO #0\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1


def test_wrong_arity_known_verb_recovers_id_too():
    handler, adapter, sink = _new_handler()
    handler.feed(b"PING #5\n")
    assert sink.lines() == ["err #5 2"]
    assert handler.malformed_count() == 1


def test_wrong_arity_rejected_no_best_effort_parse():
    handler, adapter, sink = _new_handler()
    handler.feed(b"PING extra\n")  # PING takes 0 fields
    assert sink.lines() == []
    assert handler.malformed_count() == 1

    handler.feed(b"HELLO extra\n")  # HELLO takes 0 fields too
    assert sink.lines() == []
    assert adapter.identity_calls == 0
    assert handler.malformed_count() == 2


def test_id_rejects_leading_plus_sign():
    """The id's own grammar ('#' [0-9]+) allows no sign at all, unlike
    protocol.md Sec 2's general "every wire value is ... optionally
    signed" rule for ordinary fields -- "#+5" must NOT be treated as a
    recoverable id."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"FOO #+5\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# ESTOP: no ack at all, EVER (protocol.md Sec 2.3/SUC-002) -- the one
# deliberate exception to the malformed-line #id recovery rule above.
# ---------------------------------------------------------------------------

def test_estop_produces_no_ack_at_all():
    handler, adapter, sink = _new_handler()
    handler.feed(b"ESTOP\n")
    assert sink.lines() == [], "ESTOP must never write anything to the sink"
    assert adapter.estop_calls == 1
    assert handler.malformed_count() == 0


def test_estop_wrong_arity_still_produces_no_reply():
    handler, adapter, sink = _new_handler()
    handler.feed(b"ESTOP 1\n")
    assert sink.lines() == []
    assert adapter.estop_calls == 0, "must never have reached the adapter"
    assert handler.malformed_count() == 1


def test_estop_with_trailing_id_still_never_acks():
    """The sharpest version of the ESTOP carve-out: `ESTOP #5` has a
    perfectly recoverable, well-formed nonzero id per the generic rule
    -- every OTHER verb in this suite gets an err reply in this exact
    shape (see test_wrong_arity_known_verb_recovers_id_too above).
    ESTOP must not."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"ESTOP #5\n")
    assert sink.lines() == [], "ESTOP must never ack, even with a recoverable id"
    assert adapter.estop_calls == 0
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# HELP: generated from the same dispatch table dispatch() uses
# (protocol.md Sec 4) -- cannot drift.
# ---------------------------------------------------------------------------

def test_help_text_is_generated_from_the_dispatch_table():
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELP\n")
    lines = sink.lines()
    assert len(lines) == 1
    expected_names = [
        name.decode("ascii") for name, _handler in protocol.ProtocolHandler.VERB_TABLE]
    assert lines[0] == "help " + " ".join(expected_names)


def test_help_lists_every_verb_this_sprint_scopes_including_stubs():
    """Ticket 001's own description: HELP's text must list every verb
    this sprint scopes in, GET/SET/TLM/WHEELS/STOP included, whether
    or not each one's body is a real implementation yet (GET/SET/TLM
    are real as of ticket 002; WHEELS/STOP remain stubs until ticket
    003) -- the reply text can't drift because it walks the SAME table
    dispatch() uses (see the test above), so this is really just
    pinning the expected content once, literally. Twelve verbs, no
    RUN -- this sprint's own reduced scope (see this fixture's own
    HELP block skip in _classify() above, for why the archetype's own
    13-verb HELP vector cannot be used here)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELP\n")
    assert sink.lines() == [
        "help HELLO PING ID VER STATUS HELP GET SET TLM WHEELS STOP ESTOP"
    ]


def test_help_wrong_arity_recovers_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"HELP #3\n")
    assert sink.lines() == ["err #3 2"]
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
    handler.feed(b"GET wheel_control.pid_kp\n")
    assert sink.lines() == ["get wheel_control.pid_kp 0.030000"]
    assert handler.malformed_count() == 0
    assert adapter.get_calls == ["wheel_control.pid_kp"]


def test_get_unknown_name_is_silent_not_malformed():
    """protocol.md Sec 7.1, stated explicitly: "GET with an unknown
    name is silent -- no reply, and not counted malformed." This is
    the one unknown-token case in the whole grammar that does NOT
    increment malformed_count() -- distinct from every other
    unknown-name/unknown-verb case this test module otherwise covers,
    which is exactly why the ticket calls out this case as worth its
    own test."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"GET no.such.field\n")
    assert sink.lines() == []
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
    handler.feed(b"GET\n")
    assert sink.lines() == [
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
    handler.feed(b"GET\n")
    assert sink.lines() == ["get known 1.000000"]


def test_get_wrong_arity_recovers_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"GET a b #4\n")
    assert sink.lines() == ["err #4 2"]
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
    handler.feed(b"GET weird\n")
    assert sink.lines() == ["get weird 0.000000"]


def test_get_name_that_fails_ascii_decode_is_silent_like_unknown():
    """A wire name field can be any byte except ' '/'\\n' (protocol.md
    Sec 2) -- not restricted to ASCII, even though every real
    field-table name is. A non-ASCII name can never match a real name,
    so it takes the exact same silent path as an ordinary unknown
    name, and the handler must not crash trying to decode it."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"GET \xff\xfe\n")
    assert sink.lines() == []
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
    handler.feed(b"SET wheel_control.pid_kp 1_000 #9\n")
    assert sink.lines() == ["err #9 2"]
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
    handler.feed(b"SET wheel_control.pid_kp " + value_field + b" #9\n")
    assert sink.lines() == ["err #9 2"]
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
    handler.feed(b"SET wheel_control.pid_kp     5.0 #9\n")
    assert sink.lines() == ["ok #9"]
    assert adapter.set_calls == [("wheel_control.pid_kp", 5.0, 9)]


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
    handler.feed(b"SET wheel_control.pid_kp 0x1.8p3 #9\n")
    assert sink.lines() == ["err #9 2"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_rejects_decimal_exponent_notation():
    """protocol.md Sec 2: "No exponents" -- unlike the hex-float case
    above, Python's float() DOES accept plain decimal-exponent syntax
    ("1e2" == 100.0), so this guard is genuinely load-bearing, not
    merely a pin of accidental ValueError behavior."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp 1e2 #9\n")
    assert sink.lines() == ["err #9 2"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_rejects_inf_and_nan_literal_text():
    """protocol.md Sec 2: "no NaN, no inf" -- Python's float() parses
    the literal text "inf"/"nan" successfully (no exponent, no
    underscore, no stray whitespace involved), so this is checked
    post-parse via a non-finite result, the same way the C++
    archetype's own std::isnan/std::isinf calls do."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp inf #9\n")
    assert sink.lines() == ["err #9 2"]
    handler.feed(b"SET wheel_control.pid_kp nan #8\n")
    assert sink.lines() == ["err #9 2", "err #8 2"]
    assert handler.malformed_count() == 2
    assert adapter.set_calls == []


def test_set_bad_value_with_nonzero_id_still_recovers_id():
    """The fixture's own bad-value block only exercises the id-omitted
    arm (OUT err 2, no id token) -- this covers the id-present arm the
    fixture leaves untested: a malformed VALUE with a nonzero id still
    acks against that id, same as protocol_handler.cpp's own
    idOutcome-driven reply after a parseFloatField() failure."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp notanumber #9\n")
    assert sink.lines() == ["err #9 2"]
    assert handler.malformed_count() == 1
    assert adapter.set_calls == []


def test_set_bad_value_with_id_zero_suppresses_reply():
    """"#0" suppresses every reply, success or failure alike (Sec
    8.2) -- including a handler-level value-decode failure that never
    even reaches on_set()."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET wheel_control.pid_kp notanumber #0\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
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


def test_set_wrong_arity_one_field_recovers_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"SET #4\n")
    assert sink.lines() == ["err #4 2"]
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
    handler.feed(b"SET \xff\xfe 5.0 #9\n")
    assert sink.lines() == ["err #9 1"]
    assert handler.malformed_count() == 0
    assert adapter.set_calls == []


# ---------------------------------------------------------------------------
# TLM (protocol.md Sec 6): mode decode only, no reply, no id. The
# fixture has ZERO TLM blocks at all (its own EMIT-driven telemetry
# vectors exercise emitTelemetry(), which is ticket 003's scope, not
# the TLM verb itself) -- every TLM behavior below is this ticket's own
# explicit coverage.
# ---------------------------------------------------------------------------

def test_tlm_valid_mode_persists_via_adapter_with_no_reply():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM POSE\n")
    assert sink.lines() == []
    assert adapter.tlm_calls == ["POSE"]
    assert handler.malformed_count() == 0


@pytest.mark.parametrize(
    "mode", ["OFF", "POSE", "FULL", "NOW", "AUTO", "BUFFER"])
def test_tlm_decodes_every_documented_mode(mode):
    handler, adapter, sink = _new_handler()
    handler.feed(("TLM %s\n" % mode).encode("ascii"))
    assert sink.lines() == []
    assert adapter.tlm_calls == [mode]
    assert handler.malformed_count() == 0


def test_tlm_unknown_mode_is_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM SIDEWAYS #3\n")
    assert sink.lines() == ["err #3 2"]
    assert handler.malformed_count() == 1
    assert adapter.tlm_calls == []


def test_tlm_mode_is_case_sensitive():
    """The mode table's names are the same uppercase-command spelling
    as every other wire token (protocol.md Sec 2.1) -- "pose" is not
    "POSE"."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM pose #3\n")
    assert sink.lines() == ["err #3 2"]
    assert adapter.tlm_calls == []


def test_tlm_wrong_arity_recovers_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM POSE EXTRA #3\n")
    assert sink.lines() == ["err #3 2"]
    assert handler.malformed_count() == 1
    assert adapter.tlm_calls == []


def test_tlm_invalid_mode_that_looks_like_an_id_still_recovers_it():
    """TLM's single field IS the line's own last token -- when that
    field is not a valid mode name, the generic malformed-line #id
    recovery rule (protocol.md Sec 2.3) still applies to it, exactly
    as it would to any other malformed trailing token; this is
    distinct from wrong arity (there IS exactly one field here)."""
    handler, adapter, sink = _new_handler()
    handler.feed(b"TLM #3\n")
    assert sink.lines() == ["err #3 2"]
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
    handler.feed(b"WHEELS 100 -50 1000 #5\n")
    assert sink.lines() == ["ok #5"]
    assert adapter.wheels_calls == [(100.0, -50.0, 1000.0, 5)]


def test_wheels_wrong_arity_two_fields_no_recoverable_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_wrong_arity_five_fields_recovers_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 1 2 3 4 #9\n")
    assert sink.lines() == ["err #9 2"]  # BADARG -- WHEELS is a known verb
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
    handler.feed(b"WHEELS 1_00 100 1000 #9\n")
    assert sink.lines() == ["err #9 2"]
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_rejects_hex_float_literal():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 0x1.8p3 100 1000 #9\n")
    assert sink.lines() == ["err #9 2"]
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_rejects_inf_and_nan_literal_text():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS inf 100 1000 #9\n")
    assert sink.lines() == ["err #9 2"]
    handler.feed(b"WHEELS 100 nan 1000 #8\n")
    assert sink.lines() == ["err #9 2", "err #8 2"]
    assert handler.malformed_count() == 2
    assert adapter.wheels_calls == []


def test_wheels_bad_value_with_id_omitted_acks_bare_err():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS notanumber 100 1000\n")
    assert sink.lines() == ["err 2"]
    assert handler.malformed_count() == 1
    assert adapter.wheels_calls == []


def test_wheels_bad_value_with_id_zero_suppresses_reply():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS notanumber 100 1000 #0\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
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


def test_stop_wrong_arity_two_fields_recovers_id():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP #5 #7\n")
    assert sink.lines() == ["err #7 2"]
    assert handler.malformed_count() == 1
    assert adapter.stop_calls == []


def test_stop_field_not_hash_shaped_is_malformed():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP notanid\n")
    assert sink.lines() == []
    assert handler.malformed_count() == 1
    assert adapter.stop_calls == []


def test_stop_rejected_by_adapter_still_acks_with_id():
    """STOP's id is REQUIRED, so unlike SET/WHEELS there is no
    id-0-suppresses-ack carve-out on the rejection path either -- it
    is always acked, even on rejection (protocol.md Sec 5.1)."""
    handler, adapter, sink = _new_handler()
    adapter.stop_result = protocol.Result.BUSY
    handler.feed(b"STOP #11\n")
    assert sink.lines() == ["err #11 10"]
    assert adapter.stop_calls == [11]


# ---------------------------------------------------------------------------
# The #0-legality flip (protocol.md Sec 2.2/8.2, this ticket's own
# explicit acceptance criterion): the SAME trailing token, "#0", is
# legal (silent execute) on WHEELS -- an optional-id verb -- and
# malformed on STOP -- a required-id verb. Tested side by side so the
# asymmetry is pinned as one deliberate fact, not two coincidentally
# similar tests.
# ---------------------------------------------------------------------------

def test_wheels_hash_zero_executes_silently_optional_id_verb():
    handler, adapter, sink = _new_handler()
    handler.feed(b"WHEELS 100 100 1000 #0\n")
    assert sink.lines() == [], "WHEELS #0 must execute silently, no reply"
    assert handler.malformed_count() == 0, "WHEELS #0 is well-formed, not malformed"
    assert adapter.wheels_calls == [(100.0, 100.0, 1000.0, 0)], (
        "the command must still have executed, reply_id 0")


def test_stop_hash_zero_is_malformed_required_id_verb():
    handler, adapter, sink = _new_handler()
    handler.feed(b"STOP #0\n")
    assert sink.lines() == [], "STOP #0 must never reply"
    assert handler.malformed_count() == 1, "STOP #0 is malformed, unlike WHEELS #0"
    assert adapter.stop_calls == [], "the malformed line must never reach on_stop()"


# ---------------------------------------------------------------------------
# ESTOP (protocol.md Sec 2.3/5.1/SUC-002), ticket 003's own addition:
# confirming the well-formed and malformed paths both land on "no
# reply" for the SAME underlying reason (ESTOP's own rule winning over
# the general recovery rule), not by coincidence of two different code
# paths that both happen to stay silent. The individual well-formed and
# malformed cases are each already covered above
# (test_estop_produces_no_ack_at_all / test_estop_wrong_arity_still_
# produces_no_reply / test_estop_with_trailing_id_still_never_acks,
# ticket 001) -- this test is the side-by-side confirmation ticket 003
# itself calls for.
# ---------------------------------------------------------------------------

def test_estop_wellformed_and_malformed_both_silent_for_the_same_reason():
    handler, adapter, sink = _new_handler()

    handler.feed(b"ESTOP\n")  # well-formed
    assert sink.lines() == []
    assert adapter.estop_calls == 1
    assert handler.malformed_count() == 0

    handler.feed(b"ESTOP #5\n")  # malformed: wrong arity, id-shaped extra field
    assert sink.lines() == [], (
        "ESTOP must never ack even though '#5' is a well-formed nonzero "
        "id the general recovery rule would otherwise honor")
    assert adapter.estop_calls == 1, "the malformed call must never reach the adapter"
    assert handler.malformed_count() == 1


# ---------------------------------------------------------------------------
# emit_telemetry() (protocol.md Sec 5.2/6.2), ticket 003: thdr once /
# thdr again on column-set change / t every call, and per-handler-
# instance isolation. The fixture's own multi-frame EMIT block (now
# unskipped, test_golden_vector_block above) covers the literal spec
# S6.2 worked example; these tests cover header-change detection in
# more depth than that one fixture block does.
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
        "t 2 8",
        "t 2 8",
    ]


def test_emit_telemetry_resends_thdr_when_column_count_changes():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry(_COLUMNS_A)
    handler.emit_telemetry([("seq", 3, False)])  # one column dropped
    assert sink.lines() == [
        "thdr seq flags",
        "t 1 d8",
        "thdr seq",
        "t 3",
    ]


def test_emit_telemetry_resends_thdr_when_column_name_changes():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry(_COLUMNS_A)
    handler.emit_telemetry([("seq", 3, False), ("otherflags", 1, True)])
    assert sink.lines() == [
        "thdr seq flags",
        "t 1 d8",
        "thdr seq otherflags",
        "t 3 1",
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
        "thdr seq flags",
        "t 5 d8",
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
    assert sink_a.lines() == ["thdr seq flags", "t 1 d8", "t 2 8"]

    # handler_b has never emitted before -- even though handler_a has
    # already "seen" this exact column set, handler_b's own thdr is
    # still due, proving the state is not shared module-level state.
    handler_b.emit_telemetry(_COLUMNS_A)
    assert sink_b.lines() == ["thdr seq flags", "t 1 d8"]


def test_emit_telemetry_decimal_column_formats_signed_no_hex():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry([("x", -1234, False), ("y", 892, False)])
    assert sink.lines() == ["thdr x y", "t -1234 892"]


def test_emit_telemetry_hex_column_formats_lowercase_no_prefix():
    handler, adapter, sink = _new_handler()
    handler.emit_telemetry([("flags", 4096, True)])
    assert sink.lines() == ["thdr flags", "t 1000"]
