"""_protocol_mock_adapter -- test doubles for
``tests/unit/test_protocol_golden_vectors.py``, driving
``src/core/protocol.py``'s ``ProtocolHandler`` through the duck-typed
Adapter/Sink seams that module defines (protocol.md Sec 3/4).

Shape ported from radio-robot-lib's ``tests/protocol/mock_adapter.h``
(canned answers as plain public attributes, set by a test before
``feed()``ing a line; call counts recorded for assertions) -- not its
C++ specifics (no out-params, no ``const``-correctness, no fixed-size
recording arrays: Python attributes and lists do that job for free).

Ticket 001 scope: only the methods session verbs + ESTOP call --
``identity()``/``now()``/``status()``/``on_estop()``. Ticket 002 adds
the GET/SET/TLM canned answers (``get_overrides``/``field_names`` for
``on_get()``/``field_count()``/``field_name()``, ``set_result`` for
``on_set()``, ``tlm_calls`` for ``on_tlm()``). Ticket 003 (WHEELS/STOP)
extends this SAME class further -- this file is purely additive across
the sprint, same as ``protocol.py`` itself. This file is CPython-only
test scaffolding; nothing under ``src/`` imports it.
"""

from core import protocol

__all__ = ["MockAdapter", "RecordingSink"]


class MockAdapter(object):
    """Canned answers are plain public attributes, set by a test before
    feed()ing a line."""

    def __init__(self):
        # ---- canned identity/status responses ----
        self.name = "testbot"
        self.serial = "SN001"
        self.drivetrain = "differential"
        self.profile = "tovez"
        self.version = "6.0.0"
        self.now_value = 0
        self.status_ready = False
        self.status_active = False
        self.status_conn_left = False
        self.status_conn_right = False
        self.status_otos = False
        self.status_wedge = False
        self.status_flags = 0
        self.status_tlm = "off"

        # ---- call counts (ticket 001 scope) ----
        self.identity_calls = 0
        self.now_calls = 0
        self.status_calls = 0
        self.estop_calls = 0

        # ---- GET/SET/TLM canned answers (ticket 002 scope) ----
        # GET: name -> float, the adapter's own name/value store; a
        # name with no entry here is "unknown" (protocol.md Sec 7.1:
        # GET pure-delegates, no field table lives in the handler).
        self.get_overrides = {}
        self.get_calls = []
        # Bare GET's enumeration order (protocol.md Sec 6:
        # "one get line per field, entirely the adapter's business").
        self.field_names = []
        # SET: one canned Result for every on_set() call in a test
        # (mirrors mock_adapter.h's "canned answers as plain public
        # attributes" convention -- the golden-vector fixture's own
        # "SETUP setresult <ordinal>" arms this per block). Defaults to
        # OK so a test that never sets it still gets a successful SET.
        self.set_result = protocol.Result.OK
        self.set_calls = []
        # TLM carries no Result back to the wire at all (Sec 6), so
        # there is nothing to arm here beyond recording the calls.
        self.tlm_calls = []

    def identity(self):
        self.identity_calls += 1
        return (self.name, self.serial, self.drivetrain, self.profile,
                self.version)

    def now(self):
        self.now_calls += 1
        return self.now_value

    def status(self):
        self.status_calls += 1
        return (self.status_ready, self.status_active,
                self.status_conn_left, self.status_conn_right,
                self.status_otos, self.status_wedge, self.status_flags,
                self.status_tlm)

    def on_estop(self):
        self.estop_calls += 1

    def on_get(self, name):
        self.get_calls.append(name)
        return self.get_overrides.get(name)

    def field_count(self):
        return len(self.field_names)

    def field_name(self, index):
        return self.field_names[index]

    def on_set(self, name, value, reply_id):
        self.set_calls.append((name, value, reply_id))
        return self.set_result

    def on_tlm(self, mode):
        self.tlm_calls.append(mode)
        return protocol.Result.OK


class RecordingSink(protocol.Sink):
    """protocol.py's Sink seam: one write() per formatted line,
    INCLUDING the trailing '\\n' (protocol.md Sec 3). Records every
    line written, in order, as a single accumulated str. Subclasses
    ``protocol.Sink`` for documentation value only -- ``ProtocolHandler``
    itself never checks ``isinstance()`` against it (duck-typed)."""

    def __init__(self):
        self.written = ""

    def write(self, text):
        self.written += text

    def lines(self):
        """Everything written so far, as a list of lines with the
        trailing '\\n' stripped -- mirrors
        test_protocol_harness.py's own ``_sink_lines()`` helper."""
        if self.written == "":
            return []
        parts = self.written.split("\n")
        assert parts[-1] == "", (
            "sink output not newline-terminated: %r" % (self.written,))
        return parts[:-1]

    def clear(self):
        self.written = ""
