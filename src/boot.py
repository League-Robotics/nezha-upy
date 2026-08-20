"""Boot entry point. Real logic lives in `core/boot.py`.

LANDMINE: this shim must stay at `src/` root and keep the module name
`boot`. `build.sh`'s "Wire the frozen boot module" step patches
`main.c` to call `mp_import_name(MP_QSTR_boot, mp_const_empty_tuple,
0)` at power-on. An empty fromlist makes a dotted import return the
top-level package, so importing `core.boot` that way would hand back
`core` -- whose `run()` does not exist -- and the board would appear
bricked. Keeping `boot` importable by that exact name avoids patching
C for a source reorganisation.
"""

from core.boot import run  # noqa: F401  -- main.c calls boot.run()
