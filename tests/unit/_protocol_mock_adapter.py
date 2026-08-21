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
``identity()``/``now()``/``status()``/``on_estop()``. Later tickets
(002: GET/SET/TLM: 003: WHEELS/STOP) extend this SAME class with the
remaining canned answers (a wheel-control field table, wheels/stop/set/
tlm results) as those verb bodies land in ``src/core/protocol.py`` --
this file is purely additive across the sprint, same as ``protocol.py``
itself. This file is CPython-only test scaffolding; nothing under
``src/`` imports it.
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
