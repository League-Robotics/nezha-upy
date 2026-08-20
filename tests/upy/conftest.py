"""Keep pytest out of this directory.

These scripts are MicroPython programs, not pytest tests -- they call
`report()` at module scope, which raises SystemExit. If pytest imports
them during collection that SystemExit aborts the whole run with
INTERNALERROR and NO tests execute, in any file.

They are run deliberately, under the MicroPython interpreter, by
tests/test_upy_semantics.py.
"""

collect_ignore_glob = ["*.py"]
