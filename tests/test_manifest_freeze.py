"""M5 gate: `manifest.py` lists every FRAMEWORK `src/*.py` module --
nothing is silently left on the filesystem-only path.

`_BENCH_ONLY_MODULES` excludes files that must never be frozen.
`main.py` is the
on-device student-code slot -- a FROZEN module literally named `main`
would never be found by `mp_main()`'s filesystem-only `main.py` probe
(confirmed against `codal_port/main.c`), so it must stay off the
freeze list by construction, not convention. Neither exclusion weakens
the invariant for framework modules (config.py, motion.py, ...), which
must still be frozen and still fail this test if they drift out of
manifest.py."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.py"
SRC_DIR = REPO_ROOT / "src"

# Never frozen -- see module docstring.
_USER_PROGRAMS = {"main.py", "demo_square.py", "demo_util.py"}
# Never frozen -- see module docstring. `main.py` is structural
# (mp_main() probes the FILESYSTEM for it, so a frozen `main` is
# unreachable); the demos are user programs deployed as .mpy by
# tools/deploy.py.
_BENCH_ONLY_MODULES = _USER_PROGRAMS


def _actual_src_modules():
    """Every .py under src/, as a path relative to src/ with forward
    slashes -- RECURSIVE, so package modules count. Before the src/
    split this globbed "*.py"; after it, a non-recursive glob would see
    only boot.py and main.py and this test would pass vacuously while
    blind to every module in core/, hardware/, devices/ and demos/."""
    return sorted(
        p.relative_to(SRC_DIR).as_posix()
        for p in SRC_DIR.rglob("*.py")
        if p.relative_to(SRC_DIR).as_posix() not in _BENCH_ONLY_MODULES
    )


def _manifest_listed_modules():
    lines = MANIFEST_PATH.read_text().splitlines()
    # Drop comment lines -- manifest.py's header quotes an example
    # freeze() call that would otherwise be mistaken for the real one.
    code_text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    start = code_text.index("freeze(") + len("freeze(")
    end = code_text.rindex(")")
    call_args = code_text[start:end]
    # Slashes matter: entries are package-relative paths like
    # "core/comms.py". A pattern without "/" silently matches only the
    # root-level entries and makes this whole test vacuous.
    return sorted(re.findall(r'"([A-Za-z_][A-Za-z0-9_/]*\.py)"', call_args))


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
