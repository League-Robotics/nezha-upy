"""_protocol_fixture -- generic SETUP/IN|EMIT|DEBUG/OUT block parser for
``tests/fixtures/protocol_golden_vectors.txt`` (radio-robot-lib's own
``tests/protocol/golden_vectors.txt``, copied verbatim -- see that
file's own header comment for the format and provenance of every
vector).

Ported from radio-robot-lib's ``tests/protocol/test_protocol_harness.py``
own ``_parse_golden_vectors()`` -- same block shape, same action kinds
(SETUP/IN/EMIT/DEBUG) plus OUT/``OUT NONE``. Deliberately STRUCTURAL
only: this module does not know what a SETUP key means, or which verb
an IN line names, or which blocks this sprint's reduced verb scope can
actually run -- that is ``test_protocol_golden_vectors.py``'s job. Kept
structural-only so this ticket's own acceptance criterion ("parses
every block... independent of whether the handler exists yet") holds
even before ``src/core/protocol.py`` had a single verb wired up.

This file is CPython-only test scaffolding; nothing under ``src/``
imports it.
"""

__all__ = ["Block", "parse_golden_vectors"]


class Block(object):
    """One parsed SETUP/action/OUT block.

    ``setup``: list of ``(key, tokens)`` pairs, ``tokens`` a list of
    str.
    ``actions``: list of ``(kind, payload)`` pairs -- ``kind`` is
    ``"IN"``, ``"EMIT"``, or ``"DEBUG"``; ``payload`` is a str
    (IN/DEBUG) or a list of str tokens (EMIT).
    ``expected_out``: list of str, the expected reply lines in order
    (an empty list means "OUT NONE" -- the sink must stay empty after
    every action in the block runs)."""

    def __init__(self, setup, actions, expected_out):
        self.setup = setup
        self.actions = actions
        self.expected_out = expected_out


def parse_golden_vectors(text):
    """Parse a whole fixture file's text into a list of ``Block``.
    Blocks are separated by one or more blank lines; ``'#'``-prefixed
    lines are comments (the fixture's own format, invented there, not
    by this harness -- see golden_vectors.txt's header)."""
    blocks = []
    setup = []
    actions = []
    expected_out = []
    saw_out_none = False

    def flush():
        nonlocal setup, actions, expected_out, saw_out_none
        if actions:
            blocks.append(Block(setup, actions, expected_out))
        setup = []
        actions = []
        expected_out = []
        saw_out_none = False

    for raw_line in text.splitlines():
        if raw_line.strip() == "":
            flush()
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("SETUP "):
            rest = raw_line[len("SETUP "):]
            key, _, tail = rest.partition(" ")
            setup.append((key, tail.split(" ")))
        elif raw_line.startswith("IN "):
            actions.append(("IN", raw_line[len("IN "):]))
        elif raw_line.startswith("EMIT "):
            actions.append(("EMIT", raw_line[len("EMIT "):].split(" ")))
        elif raw_line == "DEBUG" or raw_line.startswith("DEBUG "):
            text_part = raw_line[len("DEBUG"):]
            actions.append(
                ("DEBUG", text_part[1:] if text_part.startswith(" ") else ""))
        elif raw_line.startswith("OUT "):
            value = raw_line[len("OUT "):]
            if value == "NONE":
                if expected_out:
                    raise ValueError(
                        "OUT NONE must be the only OUT line: %r" % (raw_line,))
                saw_out_none = True
            else:
                if saw_out_none:
                    raise ValueError(
                        "OUT NONE must be the only OUT line: %r" % (raw_line,))
                expected_out.append(value)
        else:
            raise ValueError("unrecognized golden-vector line: %r" % (raw_line,))
    flush()
    return blocks
