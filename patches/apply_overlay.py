#!/usr/bin/env python3
"""apply_overlay.py -- Merge config keys from an overlay JSON into a target JSON.

Usage:
    python3 apply_overlay.py target.json overlay.json

Reads overlay["config"] and merges each key into target["config"], skipping
keys that start with "_" (comments). Writes the result back to target.json.
"""
import json
import sys

target_path = sys.argv[1]
overlay_path = sys.argv[2]

with open(target_path) as f:
    target = json.load(f)
with open(overlay_path) as f:
    overlay = json.load(f)

if "config" not in target:
    target["config"] = {}

for key, val in overlay.get("config", {}).items():
    if key.startswith("_"):
        continue  # comment key
    target["config"][key] = val
    print(f"  {key} = {val}")

with open(target_path, "w") as f:
    json.dump(target, f, indent=4)
    f.write("\n")

print(f"Applied overlay to {target_path}")
