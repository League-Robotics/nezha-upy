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

_DEFERRED_VERBS = (b"GET", b"SET", b"TLM", b"WHEELS", b"STOP")
_OUT_OF_SPRINT_SCOPE_VERBS = (b"RUN",)


def _classify(block):
    """Returns ``(action, reason)`` -- ``action`` is ``"run"`` or
    ``"skip"``; ``reason`` is ``None`` for ``"run"``, else a str
    explaining why."""
    kinds = set(kind for kind, _payload in block.actions)
    if "EMIT" in kinds:
        return "skip", "telemetry emission (thdr/t) is ticket 003's scope"
    if "DEBUG" in kinds:
        return "skip", (
            "sendDebug()/the robot-to-host `debug` emission is outside "
            "this sprint's verb scope -- never ported (see "
            "src/core/protocol.py's own docstring)")

    first_in = next(payload for kind, payload in block.actions if kind == "IN")
    stripped = first_in.strip(" ")
    verb_text = stripped.split(" ", 1)[0] if stripped else ""
    verb_bytes = verb_text.encode("ascii")

    if verb_bytes in _DEFERRED_VERBS:
        return "skip", (
            "%s's real body lands in ticket 002 or 003 -- ticket 001 "
            "dispatches it as a recognized-but-stub verb name" % verb_text)
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

    return "run", None


def test_golden_vector_classification_counts():
    """Pinned split so a change to _classify() (or a fixture re-sync)
    is visible as a deliberate count change, not a silent drift in how
    much of the fixture this ticket actually exercises."""
    run_count = sum(1 for b in _BLOCKS if _classify(b)[0] == "run")
    skip_count = sum(1 for b in _BLOCKS if _classify(b)[0] == "skip")
    assert run_count == 12
    assert skip_count == 31
    assert run_count + skip_count == len(_BLOCKS)


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
    else:
        raise ValueError(
            "SETUP key %r not recognized by this ticket's mock adapter -- "
            "if this fired for a block _classify() marked \"run\", either "
            "the classifier or the mock adapter needs to grow to match" % (key,))


def _run_block(block):
    handler, adapter, sink = _new_handler()
    for key, tokens in block.setup:
        _apply_setup(adapter, key, tokens)
    for kind, payload in block.actions:
        if kind == "IN":
            handler.feed((payload + "\n").encode("ascii"))
        else:
            raise ValueError(
                "action kind %r not supported by this ticket's runner -- "
                "EMIT/DEBUG blocks are always classified \"skip\"" % (kind,))
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
    """This ticket's own description: HELP's text must list GET/SET/
    TLM/WHEELS/STOP even though their bodies are stubs in this ticket
    -- the reply text can't drift because it walks the SAME table
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
