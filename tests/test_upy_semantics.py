"""Runs the MicroPython semantics suite (`tests/upy/`) under the
MicroPython interpreter and reports each script as a pytest test.

Why this exists: some firmware behaviour depends on runtime semantics
CPython does not share, so a CPython-only suite cannot express it. The
motivating case is sprint 006 ticket 009 -- `motion.drive()`'s `finally`
does not run on `break` under MicroPython but does under CPython. The
pytest suite asserted that path via `gen.close()`, passed, and the
wheels kept turning on real hardware.

SKIPS (does not fail) when the interpreter is absent, so a checkout
without it stays green. See tests/upy/README.md to build it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPY_DIR = REPO_ROOT / "tests" / "upy"
INTERPRETER = (
    REPO_ROOT / "micropython-microbit-v2" / "lib" / "micropython"
    / "ports" / "unix" / "micropython"
)

_SCRIPTS = sorted(p.name for p in UPY_DIR.glob("test_*.py"))

_MISSING = (
    "MicroPython unix interpreter not built at %s -- see tests/upy/README.md. "
    "This suite is skipped, not failed, so a checkout without it stays green."
    % INTERPRETER.relative_to(REPO_ROOT)
)


def test_interpreter_is_micropython():
    """Guard against the wrapper silently running CPython instead."""
    if not INTERPRETER.exists():
        pytest.skip(_MISSING)
    out = subprocess.run(
        [str(INTERPRETER), "-c", "import sys; print(sys.implementation.name)"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "micropython", (
        "interpreter at %s reports %r, not 'micropython'"
        % (INTERPRETER, out.stdout.strip())
    )


@pytest.mark.parametrize("script", _SCRIPTS)
def test_upy_script(script):
    """Each tests/upy/test_*.py runs under MicroPython; non-zero exit fails."""
    if not INTERPRETER.exists():
        pytest.skip(_MISSING)
    out = subprocess.run(
        [str(INTERPRETER), script],
        cwd=str(UPY_DIR), capture_output=True, text=True, timeout=120,
    )
    sys.stdout.write(out.stdout)
    sys.stdout.write(out.stderr)
    assert out.returncode == 0, (
        "%s failed under MicroPython (exit %d)\n%s%s"
        % (script, out.returncode, out.stdout, out.stderr)
    )


def test_suite_is_not_empty():
    """A wrapper that silently discovers nothing is worse than no wrapper."""
    assert _SCRIPTS, "no test_*.py found in tests/upy/ -- wrapper would pass vacuously"
