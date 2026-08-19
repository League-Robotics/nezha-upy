#!/usr/bin/env python3
"""Apply the yield + GC-hook patches to micropython-microbit-v2 source."""
import sys
import os

base = os.path.join(os.path.dirname(__file__), "..", "micropython-microbit-v2", "src")

# --- microbithal.cpp: yield patch DELIBERATELY NOT APPLIED ---
# schedule() in background_processing ran from the VM hook and (worse) the
# GC hook; fiber switches from those contexts corrupted the heap -- raising
# any exception HardFaulted (gopiv 2026-08-14). The kernel fiber the yield
# served does not exist in this build. Wi-Fi service/flush now live in
# main-context call sites in mphalport.cpp instead.
print("microbithal.cpp: yield patch intentionally skipped")
# --- mpconfigport.h: GC hook DELIBERATELY NOT APPLIED ---
# The hook ran background processing (CODAL event + schedule() fiber switch)
# mid-GC-sweep and corrupted the heap: raising any exception HardFaulted in
# mp_obj_exception_add_traceback (gopiv 2026-08-14, USB and Wi-Fi alike) --
# the vevov handoff's "exception paths wedge the REPL". No kernel fiber runs
# in this build, so the hook bought nothing.
print("mpconfigport.h: GC hook intentionally skipped (heap-corruption fix)")
