"""M5 gate: `manifest.py` (repo root) lists every `src/*.py` module --
nothing is silently left on the filesystem-only path (spec Sec 7.4).
See `clasi/sprints/001-python-first-firmware-image-m0-m6/tickets/
007-python-firmware-layer-config-telemetry-motion-otos-line-m5.md`'s
acceptance criterion this file encodes."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.py"
SRC_DIR = REPO_ROOT / "src"


def _actual_src_modules():
    return sorted(p.name for p in SRC_DIR.glob("*.py"))


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
