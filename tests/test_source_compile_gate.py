"""Offline compile gate for `src/core/` and `src/hardware/` (ticket 004's
own acceptance criterion: "`mpy-cross` compiles `src/core/protocol.py`
cleanly as part of the offline gate").

Two checks per module, both offline (no hardware, no `./build.sh`
build artifacts needed):

1. `python3 -m py_compile` -- always available under CPython, so this
   half of the gate is never skipped. Catches plain syntax errors and,
   incidentally, some of this repo's own MicroPython-clean landmine
   list (CLAUDE.md: no f-strings, no PEP 604/generic-subscript type
   hints, no host-only stdlib) to the extent CPython itself rejects
   them -- it does NOT catch a construct CPython accepts but
   MicroPython's parser does not; that gap is exactly what check 2
   below closes.
2. `mpy-cross` -- the MicroPython cross-compiler itself, actually
   parsing each module as MicroPython source. Skipped (not failed) when
   the binary has not been built at this checkout, matching
   `tests/test_deploy_budget.py`'s own `mpy-cross`-availability
   convention for the very same tool -- a checkout that has not run
   `./build.sh` yet must stay green.

Modules are enumerated by glob, not a hardcoded file list -- mirrors
`tests/test_manifest_freeze.py`'s own `_actual_src_modules()` -- over
the two packages this sprint's protocol port touches end to end
(`sprint.md`'s "New" component list): `src/core/` (now holding
`protocol.py` alongside the retiring v5 modules) and `src/hardware/`
(currently just `motion.py`; ticket 005 adds `protocol_adapter.py`
here). A later module dropped into either package is picked up by this
gate automatically, with no edit to this file -- ticket 004's own
explicit instruction, since ticket 005 lands immediately after it.

This is intentionally NOT a repo-wide gate: `src/*.py` at the root
(`boot.py`, `main.py`, `demo_square.py`, `demo_util.py`) and
`src/devices/` already have their own established conventions
elsewhere (`tests/test_manifest_freeze.py`'s freeze-list diff;
`tests/test_deploy_budget.py`'s `mpy-cross`-on-the-user-tier check for
the never-frozen demo/main modules) -- duplicating those here would be
a second, potentially drifting copy of the same check, not new
coverage.

Run with::

    python3 -m pytest tests/test_source_compile_gate.py -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
MPY_CROSS = (
    REPO_ROOT / "micropython-microbit-v2" / "lib" / "micropython"
    / "mpy-cross" / "mpy-cross"
)

# The two packages this sprint's protocol port touches end to end
# (sprint.md's own "New" component list) -- see module docstring for
# why this is deliberately not a repo-wide glob.
_GATED_PACKAGES = ("core", "hardware")


def _gated_modules():
    modules = []
    for package in _GATED_PACKAGES:
        modules.extend(sorted((SRC_DIR / package).glob("*.py")))
    return modules


_MODULES = _gated_modules()
_MODULE_IDS = [p.relative_to(SRC_DIR).as_posix() for p in _MODULES]


def test_gate_is_not_empty():
    """A glob that silently discovers nothing is worse than no gate at
    all -- mirrors tests/test_upy_semantics.py's own
    test_suite_is_not_empty for the same reason."""
    assert _MODULES, (
        "no .py files found under src/core/ or src/hardware/ -- the "
        "glob pattern or _GATED_PACKAGES broke")


def test_protocol_py_is_covered_by_the_glob():
    """Ticket 004's own named module -- pinned explicitly so a glob
    pattern that quietly stopped matching it (e.g. an extension typo)
    fails loudly here rather than this whole gate passing vacuously."""
    assert (SRC_DIR / "core" / "protocol.py") in _MODULES


@pytest.mark.parametrize("module", _MODULES, ids=_MODULE_IDS)
def test_py_compile_clean(module):
    """`python3 -m py_compile` -- the CPython half of the gate, always
    run, never skipped."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(module)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "py_compile failed on %s:\n%s" % (module, result.stderr))


@pytest.mark.skipif(
    not MPY_CROSS.exists(),
    reason=(
        "mpy-cross not built at %s -- run ./build.sh first (same "
        "skip-don't-fail convention tests/test_deploy_budget.py's own "
        "mpy-cross check already uses for this exact binary)"
        % MPY_CROSS
    ),
)
@pytest.mark.parametrize("module", _MODULES, ids=_MODULE_IDS)
def test_mpy_cross_compiles_clean(module, tmp_path):
    """The MicroPython-specific half of the gate: `mpy-cross` actually
    parses this module as MicroPython source, not just as CPython --
    the two grammars are not identical (this repo's own
    MicroPython-clean convention, CLAUDE.md, exists because of that
    gap), so a module that passes `py_compile` above is not yet proven
    to load on-device.

    (`mpy-cross` compiling clean is a LINT, not a load-path proof --
    this build does not define `MICROPY_PERSISTENT_CODE_LOAD`, so the
    board cannot import a `.mpy` from the filesystem at all; every
    module the firmware actually ships is frozen source, compiled at
    build time. See docs/design/specification.md's own
    "mpy-cross-is-lint" framing. That does not weaken this gate's
    value: it still catches every syntax construct MicroPython's
    parser rejects that CPython's does not.)"""
    out = tmp_path / (module.stem + ".mpy")
    result = subprocess.run(
        [str(MPY_CROSS), "-o", str(out), str(module)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "mpy-cross failed on %s:\n%s" % (module, result.stderr))
