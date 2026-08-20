"""Offline M0 gate: verify ./build.sh --clean produced a valid image.

This does NOT run the build itself -- run `./build.sh --clean` first, then:

    python3 -m pytest tests/test_build_gate.py

All checks are static inspection of the build's output artifacts (the
produced hex, the linker map, and the patched source/config files). No
hardware, no flashing, no REPL.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MP_DIR = REPO_ROOT / "micropython-microbit-v2"
HEX_PATH = MP_DIR / "src" / "MICROBIT.hex"
MAP_PATH = MP_DIR / "lib" / "codal" / "build" / "MICROBIT.map"
MPCONFIGPORT_PATH = MP_DIR / "src" / "codal_port" / "mpconfigport.h"
CODAL_JSON_PATH = MP_DIR / "src" / "codal_app" / "codal.json"
OVERLAY_JSON_PATH = REPO_ROOT / "codal_overlay.json"

# The non-negotiable M0 gate value. If this ever legitimately moves,
# update it here alongside the change that moved it -- do not silently
# loosen the check.
EXPECTED_FS_START = 0x6D000

# Same symbol set + page-size arithmetic as addlayouttable.py (the tool
# that builds the flash layout table baked into the hex) -- recomputes
# flash-end independently from the map file, not from its stdout.
NRF_PAGE_SIZE_LOG2 = 12
NRF_PAGE_SIZE = 1 << NRF_PAGE_SIZE_LOG2

MAP_SYMBOLS = (
    "__isr_vector",
    "__etext",
    "__data_start__",
    "__data_end__",
    "_fs_start",
    "_fs_end",
    "microbit_version_string",
)


def _require(path: Path, hint: str) -> Path:
    if not path.exists():
        pytest.fail(
            f"{path.relative_to(REPO_ROOT)} not found -- {hint}",
            pytrace=False,
        )
    return path


def _parse_map_symbols(map_path: Path) -> dict[str, int | None]:
    """Port of addlayouttable.py's parse_map_file: same symbol table, same
    line-matching rule (0x00.../0x20... rows under the "Linker script and
    memory map" section)."""
    symbols: dict[str, int | None] = {key: None for key in MAP_SYMBOLS}
    parse_symbols = False
    with map_path.open() as f:
        for line in f:
            line = line.strip()
            if line == "Linker script and memory map":
                parse_symbols = True
            elif parse_symbols and (line.startswith("0x00") or line.startswith("0x20")):
                parts = line.split()
                if len(parts) >= 2 and parts[1] in symbols:
                    symbols[parts[1]] = int(parts[0], 16)
    return symbols


@pytest.fixture(scope="module")
def map_symbols() -> dict[str, int | None]:
    _require(
        MAP_PATH,
        "run `./build.sh --clean` first (produces the .map alongside the hex)",
    )
    return _parse_map_symbols(MAP_PATH)


def test_hex_produced():
    """`./build.sh --clean` must produce
    micropython-microbit-v2/src/MICROBIT.hex."""
    _require(HEX_PATH, "run `./build.sh --clean` first")
    assert HEX_PATH.stat().st_size > 0, "MICROBIT.hex exists but is empty"


def test_flash_end_below_fs_start(map_symbols):
    """Flash-end address (from the .map) must be < _fs_start.

    Recomputes the same layout-table placement addlayouttable.py uses
    (mp_end -> next-page-aligned layout_addr -> layout end), independent
    of build.sh's own stdout.
    """
    missing = [k for k, v in map_symbols.items() if v is None and k != "microbit_version_string"]
    assert not missing, f"symbols missing from {MAP_PATH.name}: {missing}"

    fs_start = map_symbols["_fs_start"]
    fs_end = map_symbols["_fs_end"]
    assert fs_start == EXPECTED_FS_START, (
        f"_fs_start moved to {hex(fs_start)}, expected {hex(EXPECTED_FS_START)} "
        "-- this is the M0 gate's non-negotiable boundary; if it legitimately "
        "moved, update EXPECTED_FS_START here and document why in the ticket"
    )
    assert fs_end > fs_start, "_fs_end must be after _fs_start"

    mp_start = map_symbols["__isr_vector"]
    data_len = map_symbols["__data_end__"] - map_symbols["__data_start__"]
    mp_end = map_symbols["__etext"] + data_len

    # Layout table placement mirrors addlayouttable.py: highest
    # 16-byte-aligned table that fits in mp_end's page, else next page.
    # Real table size here is ~32 bytes; a generous 64-byte placeholder
    # is fine since flash_end is bounded above regardless of exact size.
    layout_addr = ((mp_end >> NRF_PAGE_SIZE_LOG2) << NRF_PAGE_SIZE_LOG2) + NRF_PAGE_SIZE - 64
    if layout_addr < mp_end:
        layout_addr += NRF_PAGE_SIZE
    flash_end = layout_addr + NRF_PAGE_SIZE  # end of the page the layout table occupies

    assert mp_start >= 0, "MicroPython region must start at/after 0x0"
    assert flash_end < fs_start, (
        f"flash end (0x{flash_end:x}, page containing layout table at "
        f"0x{layout_addr:x}) is not below _fs_start (0x{fs_start:x})"
    )


def test_version_string_present(map_symbols):
    """Version string must be present in the built image."""
    addr = map_symbols["microbit_version_string"]
    assert addr is not None, (
        "microbit_version_string symbol not found in MICROBIT.map -- "
        "addlayouttable.py requires this symbol to build the layout table's "
        "hash-pointer region; its absence means the hex could not have been "
        "produced correctly"
    )
    assert addr > 0


def test_micropy_nlr_setjmp_is_1():
    """MICROPY_NLR_SETJMP must be 1 in the patched mpconfigport.h --
    without it, any exception HardFaults under GCC15 (v1.18
    nlr_thumb.c miscompile)."""
    _require(MPCONFIGPORT_PATH, "run `./build.sh --clean` first (patches this file)")
    text = MPCONFIGPORT_PATH.read_text()
    match = re.search(r"#define\s+MICROPY_NLR_SETJMP\s+\(?(\d+)\)?", text)
    assert match, "MICROPY_NLR_SETJMP is not defined in mpconfigport.h"
    assert match.group(1) == "1", (
        f"MICROPY_NLR_SETJMP is {match.group(1)}, expected 1 -- any exception "
        "will HardFault under GCC 15 without this"
    )


def test_codal_overlay_keys_merged():
    """codal_overlay.json's keys must be present, unmodified, in
    codal_app/codal.json after patches/apply_overlay.py runs."""
    _require(OVERLAY_JSON_PATH, "codal_overlay.json should be checked into the repo root")
    _require(CODAL_JSON_PATH, "run `./build.sh --clean` first (patches this file)")

    overlay = json.loads(OVERLAY_JSON_PATH.read_text())
    target = json.loads(CODAL_JSON_PATH.read_text())
    target_config = target.get("config", {})

    overlay_keys = {k: v for k, v in overlay.get("config", {}).items() if not k.startswith("_")}
    assert overlay_keys, "codal_overlay.json has no non-comment config keys to check"

    missing = {k: v for k, v in overlay_keys.items() if k not in target_config}
    assert not missing, f"overlay keys missing from codal.json: {missing}"

    mismatched = {
        k: (v, target_config[k]) for k, v in overlay_keys.items() if target_config[k] != v
    }
    assert not mismatched, f"overlay keys present but mismatched (expected, actual): {mismatched}"
