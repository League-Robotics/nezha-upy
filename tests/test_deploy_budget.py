"""The user-program tier must fit the device filesystem.

Before this test the only thing that enforced the budget was the bench:
`mpremote: cp: robot.json: No space left on device`, discovered with a
robot on the desk. The region is 24576 B, but microbitfs.c reserves a
page and carves the rest into 160 chunks of 126 usable bytes -- 20160 B
is the real payload ceiling, and checking against 24576 would let a
deploy pass here and fail on hardware.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import deploy  # noqa: E402


def _robots():
    return sorted(p.stem for p in (REPO_ROOT / "data").glob("*.json")
                  if p.stem not in {"robot_config.schema", "active_robot"})


def test_budget_matches_the_device_geometry():
    """160 chunks x 126 usable bytes, not the 24576 B region size."""
    assert deploy.FS_PAYLOAD_BUDGET == 20160


@pytest.mark.parametrize("robot", _robots())
def test_stripped_config_is_deployable(robot):
    """Every robot config must survive stripping and fit on its own."""
    doc = json.loads((REPO_ROOT / "data" / ("%s.json" % robot)).read_text())
    compact = json.dumps(deploy.strip_config(doc), separators=(",", ":"))
    size = len(compact.encode())
    assert size < deploy.FS_PAYLOAD_BUDGET, (
        "%s.json strips to %d B, over the %d B filesystem budget"
        % (robot, size, deploy.FS_PAYLOAD_BUDGET))
    # Stripping must not damage the document: identity has to survive.
    assert json.loads(compact)["identity"]["robot_name"]


def test_strip_removes_underscore_keys_recursively():
    doc = {"a": 1, "_note": "x", "g": {"b": 2, "_why": "y", "h": {"_z": 1, "c": 3}}}
    assert deploy.strip_config(doc) == {"a": 1, "g": {"b": 2, "h": {"c": 3}}}


def test_user_programs_are_not_frozen():
    """The deploy set and the freeze list must not overlap -- a module in
    both would have its frozen copy silently shadowed, or worse, drift."""
    manifest = (REPO_ROOT / "manifest.py").read_text()
    frozen = manifest[manifest.index("freeze("):]
    for name in deploy.USER_PROGRAMS:
        assert '"%s"' % name not in frozen, (
            "%s is a user program but still in manifest.py's freeze list" % name)


@pytest.mark.skipif(not Path(deploy.MPY_CROSS).exists(),
                    reason="mpy-cross not built (run ./build.sh)")
def test_whole_user_tier_fits(tmp_path):
    """Config + every compiled user program, together, against the budget."""
    artifacts = deploy.build_artifacts("tovez", str(tmp_path))
    total = sum(a[4] for a in artifacts)
    assert total < deploy.FS_PAYLOAD_BUDGET, (
        "user tier is %d B, over the %d B budget: %s"
        % (total, deploy.FS_PAYLOAD_BUDGET,
           ", ".join("%s=%dB" % (a[0], a[4]) for a in artifacts)))
