"""M5 gate: `manifest.py` (repo root) lists every FRAMEWORK `src/*.py`
module -- nothing is silently left on the filesystem-only path (spec
Sec 7.4). See `clasi/sprints/001-python-first-firmware-image-m0-m6/
tickets/007-python-firmware-layer-config-telemetry-motion-otos-line-
m5.md`'s acceptance criterion this file encodes.

`_BENCH_ONLY_MODULES` (sprint 002 ticket 002) carves out a narrow,
named exception for demo/bench SCRIPTS that are deliberately never
frozen -- `src/demo_square.py` is the first: it is a bench demo
script, not a framework module, run via `mpremote run` (source upload
+ execute) or, on-device, imported explicitly by `src/main.py`'s own
`run_tour()`/`run_straight_drive()` (sprint 006 ticket 001: a bare
`import demo_square` no longer auto-runs anything by itself -- see
that module's own docstring's "Auto-run trigger" section). It stays
off the freeze list regardless: freezing would need a full
rebuild+reflash unrelated to any single ticket's own scope. This does
not weaken the invariant for FRAMEWORK modules (config.py, motion.py,
comms.py, ...), which must still be frozen and still fail this test if
they drift out of manifest.py.

`src/main.py` (sprint 003 ticket 001, renamed to its current filename
in sprint 006 ticket 001) is the second entry: it is the
version-controlled copy of zetuv's on-device `main.py` (the
filesystem student-code slot -- `src/boot.py`'s own module docstring
confirms, directly against `codal_port/main.c`, that a FROZEN module
literally named `main` would never be found by
`mp_main()`'s filesystem-only `main.py` probe, so this file must stay
off the freeze list by construction, not merely by convention)."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.py"
SRC_DIR = REPO_ROOT / "src"

# Bench/demo scripts and on-device-main.py copies, never frozen -- see
# this module's own docstring.
_BENCH_ONLY_MODULES = {"main.py"}


def _actual_src_modules():
    return sorted(
        p.name for p in SRC_DIR.glob("*.py") if p.name not in _BENCH_ONLY_MODULES
    )


def _manifest_listed_modules():
    lines = MANIFEST_PATH.read_text().splitlines()
    # Drop `#`-comment lines first -- the module's own header comment
    # quotes a `freeze("modules", "neopixel.py", opt=3)` EXAMPLE (the
    # stock default it deliberately does NOT carry forward) which would
    # otherwise be mistaken for the real, executable freeze() call below.
    code_text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    start = code_text.index("freeze(") + len("freeze(")
    end = code_text.rindex(")")
    call_args = code_text[start:end]
    return sorted(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*\.py)"', call_args))


def test_manifest_file_exists():
    assert MANIFEST_PATH.is_file()


def test_manifest_lists_exactly_the_src_py_modules():
    actual = _actual_src_modules()
    listed = _manifest_listed_modules()
    assert listed == actual, (
        "manifest.py's freeze() list has drifted from src/*.py's actual "
        "contents -- a module is either missing from the freeze (left on "
        "the filesystem-only path) or the manifest lists a file that no "
        "longer exists.\n  src/*.py:        %r\n  manifest.py lists: %r"
        % (actual, listed)
    )


def test_manifest_calls_freeze_with_src_relative_path():
    text = MANIFEST_PATH.read_text()
    assert 'freeze(\n    "../../../src"' in text or 'freeze("../../../src"' in text
