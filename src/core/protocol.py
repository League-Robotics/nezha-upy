"""protocol -- v6 ASCII line-grammar handler (protocol.md Sec 2-6).

Ported from radio-robot-lib's ``src/protocol/protocol_handler.{h,cpp}``
(the C++ archetype) -- read that file's own header first if extending
this module; it documents every grammar ambiguity this port inherits
already resolved (malformed-line ``#id`` recovery firing even for an
unknown verb, ``ESTOP`` winning over that same recovery rule, the id's
own stricter digit-only grammar). This file re-derives none of those
calls; see ``docs/design/protocol.md`` (radio-robot-lib) Sec 9 for the
full resolution history and ``clasi/sprints/007-.../sprint.md``'s
Architecture section for this repo's own port-level decisions.

Grammar (protocol.md Sec 2), in one line::

    line   ::= sp? verb ( sp field )* sp? '\\n'
    sp     ::= ' '+
    verb   ::= [A-Za-z][A-Za-z0-9_]*
    field  ::= any bytes except ' ' and '\\n'
    id     ::= '#' [0-9]+        (a field in trailing position, Sec 2.3)

A run of spaces is ONE separator; leading/trailing line whitespace is
ignored; a blank/all-whitespace line is ignored SILENTLY (not
malformed). Case is direction: commands are UPPERCASE, replies are
lowercase, and verb lookup is case-sensitive -- a lowercase-led line is
another robot's reply overheard on a shared channel and is dropped
silently (Sec 2.1). Malformed-line recovery (Sec 2.3): unknown verb /
wrong arity / unparseable field -> count malformed; if the line's raw
last token is a well-formed NONZERO ``#id``, reply ``err #<id>
<code>``, else no reply. ``ESTOP`` is the one exception and wins even
when malformed: never any reply, ever.

Sprint scope (this repo's ``sprint.md``, "In Scope"): ``HELLO PING ID
VER STATUS HELP GET SET TLM WHEELS STOP ESTOP`` -- 12 verbs. The C++
archetype also implements ``RUN`` (invocation by name) and the
robot-to-host-only ``debug`` unsolicited emission; NEITHER is ported
here at all, not even deferred to a later ticket -- this sprint's own
verb-scope list omits both, so ``tests/fixtures/protocol_golden_vectors.txt``
(copied verbatim from the archetype's own fixture, which DOES cover
RUN/debug) has vectors this port will never make green; the harness
(``tests/unit/test_protocol_golden_vectors.py``) skips them by verb
instead of deleting them. One concrete consequence: the archetype's own
``HELP`` vector lists ``RUN`` as a 13th verb; this port's ``HELP`` text
(Sec 4, "generated from the same dispatch table dispatch() uses") is
only ever 12 verbs, so that one fixture vector is skipped too, even
though every OTHER session-verb vector runs for real.

Ticket 001 scope (this file, as it lands here): ``feed()``/tokenizer/
dispatch skeleton; the six session verbs (HELLO/PING/ID/VER/STATUS/
HELP) fully implemented; ``ESTOP`` fully implemented (SUC-002: never
any reply, even malformed); the generic malformed-line ``#id``-recovery
rule. ``GET``/``SET``/``TLM``/``WHEELS``/``STOP`` are registered
dispatch NAMES ONLY -- present in ``VERB_TABLE`` so an inbound line for
one of them is never treated as an unknown verb, but each one's own
handler is a deliberate no-op (no arity check, no adapter call, no
reply) until ticket 002 (GET/SET/TLM) and ticket 003 (WHEELS/STOP) give
it a real body. ``HELP``'s text already lists all of them, since it
walks this same table.

Adapter seam (protocol.md Sec 4), as far as this ticket calls it --
duck-typed, no ABC (MicroPython has no ``abc`` module):

    identity() -> (name, serial, drivetrain, profile, version)
    now() -> int [ms]
    status() -> (ready, active, conn_left, conn_right, otos, wedge,
                 flags, tlm) -- booleans, `flags` an int, `tlm` a str
    on_estop() -> None

Later tickets grow this contract (``on_wheels``/``on_stop``/``on_get``/
``on_set``/``on_tlm``/``field_count``/``field_name``, protocol.md Sec
4) as GET/SET/TLM/WHEELS/STOP get real bodies; the real adapter
(``src/hardware/protocol_adapter.py``) is ticket 005.

Design decisions this port makes, beyond a line-for-line translation:

- ``Sink.write(text)`` takes a ``str`` (the complete reply line,
  INCLUDING its trailing ``'\\n'``), not raw bytes. The C++ archetype's
  ``Sink::write(const char*, size_t)`` exists only because C++ has no
  other way to hand back a formatted line; a text-based line protocol
  maps onto Python ``str`` naturally, and the wire-byte boundary is a
  transport-layer concern this module never owns (comms.py's job,
  ticket 006).
- ``feed()`` still takes ``bytes`` (matching every transport's own
  ``read_line() -> bytes`` contract elsewhere in this repo) and still
  reassembles byte-by-byte with a bounded buffer, even though every
  live transport today already hands it one complete, pre-reassembled
  line per call -- this mirrors ``sprint.md``'s own Design Rationale
  ("port feed()'s full byte-buffering robustness... a line-only
  shortcut would fail the golden-vector fixture and would be a silent
  divergence"). A bounded buffer (not an unbounded accumulate-until-'\\n'
  loop) also matters on a memory-constrained MicroPython target: an
  overlong line without a terminator is capped and marked overflowing
  rather than growing without bound.
- No fixed-size field-token array / ``kMaxFieldTokens`` cap. That cap
  exists in the C++ archetype purely to bound a fixed C array's storage
  (RUN's own open arity, protocol_handler.h's ambiguity note #4) --
  Python lists have no equivalent fixed-capacity hazard, and RUN is not
  ported here at all, so the cap (and the separate raw-line
  "``findLastFieldToken()``" backward scan it forced the archetype to
  do BEFORE tokenizing) has no reason to exist in this port: the
  tokenized field list is never truncated, so its own last element IS
  the line's true raw last token whenever there is one.
- ``Result`` carries only ``OK``/``UNKNOWN``/``BADARG`` in this ticket
  -- the two malformed-line rejection codes ``dispatch()``/the session
  verbs' own arity checks use. The rest of protocol.md Sec 6.1's error
  code table, and any ordinal-to-wire-code mapping a concrete Adapter
  needs, is ticket 002's own stated scope ("Result-to-error-code
  table").

LANDMINE: no f-strings, no PEP 604/generic-subscript type hints, no
host-only stdlib -- must import and run unmodified under both CPython
(host tests) and MicroPython (CLAUDE.md).
"""

__all__ = [
    "ProtocolHandler",
    "Sink",
    "Result",
    "MAX_LINE_BYTES",
]

# protocol.md Sec 2: "Max line: 240 bytes including the terminator."
# One place this number is spelled -- feed()'s buffer sizes off it.
MAX_LINE_BYTES = 240


class Result(object):
    """Outcome of an Adapter call (protocol.md Sec 4) -- maps onto the
    wire's ok/err distinction. A plain class of int constants, not
    ``enum.Enum`` (MicroPython-clean: avoid assuming ``enum`` is always
    available -- see ``src/core/msgs.py``'s ``VerbEntry`` for the same
    plain-class convention elsewhere in this codebase).

    Ticket 001 scope: only ``OK``/``UNKNOWN``/``BADARG`` are defined --
    every code this ticket's own dispatch()/session-verb arity checks
    use. The remaining codes in protocol.md Sec 6.1's table (``RANGE``/
    ``FULL``/``UNIMPLEMENTED``/``NOT_READY``/``BUSY``/``DUPLICATE_ID``)
    land with ticket 002, which owns building the fuller
    "Result-to-error-code table" this ticket does not need yet."""

    OK = 0
    UNKNOWN = 1
    BADARG = 2


class Sink(object):
    """Where finished reply lines go (protocol.md Sec 3's Sink seam).
    Duck-typed, not an ABC (MicroPython has no ``abc`` module): any
    object with a ``write(text)`` method works, and ``ProtocolHandler``
    never checks ``isinstance()`` against this class. It exists only so
    the contract has one documented, importable name.

    ``write(text)``: ``text`` is one fully formatted reply line
    (``str``), INCLUDING its trailing ``'\\n'`` -- exactly one call per
    line, matching ``protocol_handler.h``'s own ``Sink::write()``
    contract."""

    def write(self, text):
        raise NotImplementedError


def _parse_id_digits(digits):
    """protocol.md Sec 2.2: the id's own grammar is ``'#' [0-9]+`` --
    STRICTER than an ordinary signed integer field (Sec 2's "every wire
    value is ... optionally signed"): no sign at all, not even a
    leading ``'+'``, so ``#+5`` must NOT parse as id 5. A dedicated
    digit-only scan (not ``int()``, which accepts a leading ``'+'``/
    ``'-'`` and this codebase's own underscore/whitespace leniency
    concerns -- see ``config.py``'s numeric-field notes) -- returns the
    parsed non-negative int, or ``None`` if ``digits`` is empty or
    contains any non-digit byte."""
    if len(digits) == 0:
        return None
    value = 0
    for b in digits:
        if b < 48 or b > 57:  # '0'-'9'
            return None
        value = value * 10 + (b - 48)
    return value


def _recover_trailing_id(token):
    """protocol.md Sec 2.3's generic malformed-line recovery: "if the
    line's last token is a well-formed nonzero ``#id``, reply ``err
    #<id> <code>``." ``token`` (bytes or ``None``) is the line's raw
    last token -- ``None`` when the line was just the verb, nothing
    after it (matching "otherwise no reply"). Returns the recovered int
    id, or ``None`` if there is nothing to recover (no token, not
    ``#``-shaped, not well-formed digits, or exactly zero -- id 0 never
    gets an err reply, Sec 2.2)."""
    if token is None or token[0:1] != b"#":
        return None
    parsed = _parse_id_digits(token[1:])
    if parsed is None or parsed == 0:
        return None
    return parsed


class ProtocolHandler(object):
    """The ASCII line-grammar codec (protocol.md Sec 2-6). The only
    class in this module that ever touches a wire byte: ``feed()``
    reassembles arbitrary byte blocks into ``'\\n'``-terminated lines,
    tokenizes each line on runs of ``' '``, dispatches to the Adapter,
    and formats the reply -- once, per verb, so the Adapter can neither
    forget a reply nor invent a shape for one.

    ``VERB_TABLE``: an ordered tuple of ``(name_bytes, handler)`` pairs
    -- the SAME table ``dispatch()`` and ``_handle_help()`` both walk,
    so ``HELP``'s reply text cannot drift from what ``dispatch()``
    actually recognizes (protocol.md Sec 4)."""

    def __init__(self, adapter, sink):
        self._adapter = adapter
        self._sink = sink
        self._line_buf = bytearray()
        self._overflowing = False
        self._malformed_count = 0

    def malformed_count(self):
        """Lines dropped as unknown verb, wrong arity, or an
        unparseable field (protocol.md Sec 2's malformed counter). A
        lowercase-led inbound verb (another robot's reply, Sec 2.1) is
        dropped silently and does NOT increment this; neither does a
        blank/all-whitespace line (Sec 2)."""
        return self._malformed_count

    # ---- feed() / line reassembly --------------------------------------

    def feed(self, data):
        """Feed an arbitrary block from the port (``bytes``) -- may
        contain zero, one, or several complete lines, and may end
        mid-line. Partial lines are buffered across calls; complete
        lines are parsed and dispatched immediately, in the order they
        complete. Must survive (protocol.md Sec 2/2.1):

        - several complete lines in one block;
        - a block ending mid-line (the remainder is buffered);
        - a block that is only a line fragment;
        - a lone ``'\\r'`` immediately before ``'\\n'`` (stripped;
          ``'\\r'`` never appears elsewhere);
        - a blank or all-whitespace line (ignored silently -- NOT
          counted malformed);
        - a line longer than the 240-byte maximum: discarded to the
          next ``'\\n'`` and counted malformed -- NEVER truncated into
          a prefix that might still parse as a command the host never
          sent."""
        for byte in data:
            self._append_byte(byte)

    def _append_byte(self, byte):
        if byte == 10:  # '\n' (0x0A) -- line terminator
            self._on_line_complete()
            return
        if self._overflowing:
            return  # discard content until the next '\n'
        if len(self._line_buf) >= MAX_LINE_BYTES - 1:
            # Storing this byte would push the line's content alone to
            # MAX_LINE_BYTES - 1, i.e. content + '\n' would exceed the
            # wire's 240-byte cap. Discard to the next '\n' rather than
            # truncate -- a truncated prefix that still parses as a
            # legal command is one the host never sent (Sec 2.1).
            self._overflowing = True
            del self._line_buf[:]
            return
        self._line_buf.append(byte)

    def _on_line_complete(self):
        if self._overflowing:
            self._overflowing = False
            del self._line_buf[:]
            self._malformed_count += 1
            return

        # A lone '\r' immediately before '\n' is a terminal artifact,
        # stripped; '\r' appears nowhere else on the wire (Sec 2).
        if len(self._line_buf) > 0 and self._line_buf[-1] == 13:  # '\r'
            del self._line_buf[-1:]
        line = bytes(self._line_buf)
        del self._line_buf[:]

        # A blank or all-whitespace line is ignored SILENTLY (Sec 2) --
        # a terminal artifact, not an error; it does NOT count
        # malformed. Only ' ' counts here, matching the grammar's own
        # "field ::= any bytes except ' ' and '\n'" -- a line of only
        # tabs is NOT blank under this rule (it tokenizes to one odd
        # "verb" token instead, and fails as an unknown verb).
        if not line.strip(b" "):
            return

        # Split on runs of ' ', dropping the empties a run produces --
        # collapses "sp ::= ' '+" into one separator and trims
        # leading/trailing line whitespace, with no allocation-bounded
        # storage cap (see this module's own docstring: unlike the C++
        # archetype, nothing here truncates the field list, so its own
        # last element IS the line's true raw last token whenever one
        # exists).
        tokens = [t for t in line.split(b" ") if t]
        verb = tokens[0]
        fields = tokens[1:]
        last_field_token = tokens[-1] if len(tokens) >= 2 else None
        self._dispatch(verb, fields, last_field_token)

    # ---- dispatch -------------------------------------------------------

    def _dispatch(self, verb, fields, last_field_token):
        # Case is direction (Sec 2.1): commands are UPPERCASE, replies
        # are lowercase, and verb lookup is case-sensitive. A verb
        # starting with a lowercase letter can never be a command this
        # table knows about -- it is another robot's reply, overheard
        # on a shared channel, and is dropped SILENTLY, not counted
        # malformed (the structural fix for the v5 DBG:-flood incident:
        # a reply can never parse as a command under this grammar).
        if 97 <= verb[0] <= 122:  # 'a' <= verb[0] <= 'z'
            return

        for name, handler in self.VERB_TABLE:
            if verb == name:
                handler(self, fields, last_field_token)
                return

        # Unknown verb: no arity is knowable, but the line's own last
        # token can still be a well-formed nonzero #id worth acking
        # against (Sec 2.3's own "including unknown verbs" framing).
        self._reject_malformed(last_field_token, Result.UNKNOWN)

    def _reject_malformed(self, last_field_token, code):
        """Malformed-line recovery (Sec 2/2.3): counts the line
        malformed, then replies ``err #<id> <code>`` IF the line's raw
        last token is a well-formed nonzero ``#id`` -- otherwise no
        reply. Used for unknown verbs and every handler's own
        wrong-arity rejection EXCEPT ``ESTOP``, which never calls
        this."""
        self._malformed_count += 1
        recovered_id = _recover_trailing_id(last_field_token)
        if recovered_id is not None:
            self._reply_err(recovered_id, code)

    # ---- reply formatting ------------------------------------------------

    def _reply_err(self, reply_id, code):
        self._write_line("err #%d %d\n" % (reply_id, code))

    def _write_line(self, text):
        self._sink.write(text)

    # ---- unsolicited emissions --------------------------------------------

    def send_banner(self):
        """Unsolicited emission (protocol.md Sec 4): ``device NEZHA2
        robot <name> <serial>``. ``HELLO``'s own reply (Sec 3.1) is
        byte-identical to this -- ``_handle_hello()`` calls this same
        method rather than duplicating the format string."""
        name, serial, _drivetrain, _profile, _version = self._adapter.identity()
        self._write_line("device NEZHA2 robot %s %s\n" % (name, serial))

    # ---- session verbs ----------------------------------------------------
    # HELLO/PING/ID/VER/STATUS/HELP all take zero fields -- any
    # trailing token at all, id-shaped or not, is wrong arity.

    def _handle_hello(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        self.send_banner()

    def _handle_ping(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        self._write_line("pong %d\n" % self._adapter.now())

    def _handle_id(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        _name, _serial, drivetrain, profile, version = self._adapter.identity()
        self._write_line("id %s %s %s\n" % (drivetrain, profile, version))

    def _handle_ver(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        _name, _serial, _drivetrain, _profile, version = self._adapter.identity()
        self._write_line("ver %s\n" % version)

    def _handle_status(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        (ready, active, conn_left, conn_right, otos, wedge, flags,
         tlm) = self._adapter.status()
        self._write_line(
            "status ready=%d active=%d connL=%d connR=%d otos=%d "
            "wedge=%d flags=%x tlm=%s\n"
            % (1 if ready else 0, 1 if active else 0,
               1 if conn_left else 0, 1 if conn_right else 0,
               1 if otos else 0, 1 if wedge else 0, flags, tlm))

    def _handle_help(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        # "Generated by walking the verb table at runtime, so it cannot
        # drift from the dispatcher" (protocol.md Sec 4) -- VERB_TABLE
        # is the SAME table _dispatch() looks verbs up in.
        names = [name.decode("ascii") for name, _handler in self.VERB_TABLE]
        self._write_line("help " + " ".join(names) + "\n")

    def _handle_estop(self, fields, last_field_token):
        if len(fields) != 0:
            # ESTOP is NEVER acked, not even on wrong arity (protocol.md
            # Sec 2.3/SUC-002) -- this verb's own rule wins over the
            # generic malformed-line #id-recovery rule every other
            # handler uses. Deliberately does NOT call
            # _reject_malformed() (which would call _reply_err()).
            self._malformed_count += 1
            return
        self._adapter.on_estop()
        # No reply, ever.

    def _handle_unimplemented_this_ticket(self, fields, last_field_token):
        """GET/SET/TLM/WHEELS/STOP: registered dispatch NAMES only in
        this ticket. An inbound line for one of them is recognized (so
        it never falls into the generic "unknown verb" malformed path)
        but is otherwise a deliberate no-op -- no arity check, no
        Adapter call, no reply, no malformed-count change -- until
        ticket 002 (GET/SET/TLM) or ticket 003 (WHEELS/STOP) gives it a
        real body. See this module's own docstring."""
        pass

    VERB_TABLE = (
        (b"HELLO", _handle_hello),
        (b"PING", _handle_ping),
        (b"ID", _handle_id),
        (b"VER", _handle_ver),
        (b"STATUS", _handle_status),
        (b"HELP", _handle_help),
        (b"GET", _handle_unimplemented_this_ticket),
        (b"SET", _handle_unimplemented_this_ticket),
        (b"TLM", _handle_unimplemented_this_ticket),
        (b"WHEELS", _handle_unimplemented_this_ticket),
        (b"STOP", _handle_unimplemented_this_ticket),
        (b"ESTOP", _handle_estop),
    )
