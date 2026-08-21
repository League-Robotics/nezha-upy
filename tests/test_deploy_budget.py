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


# --- identity guard: the check that would have caught the 3.3x error ---
#
# Per-robot wheel calibration is selected by identity, and the configs
# differ by 3.70x in ticks_per_mm (zetuv 3.4484, tovez 12.7602). Commit
# 6c5f57c records a commanded 500 mm driving ~150 mm -- an error of
# exactly that character. Two boards on this bench have announced the
# same name, so "the port I plugged into" is not an identity.
#
# See clasi/issues/done/robot-identity-collision-and-stale-device-map.md.

def test_matching_identity_is_a_match():
    assert deploy.identity_verdict("tovez", "tovez") == deploy.IDENT_MATCH


def test_different_identity_is_a_mismatch():
    assert deploy.identity_verdict("zetuv", "tovez") == deploy.IDENT_MISMATCH


def test_device_without_a_config_is_fresh_not_a_match():
    """A freshly-flashed board has no robot.json. That must be
    distinguishable from a confirmed match -- deploying is fine, but
    reporting it as confirmed would be a lie."""
    assert deploy.identity_verdict("<none>", "tovez") == deploy.IDENT_FRESH


def test_failed_probe_is_unreadable_not_a_match():
    """An empty probe result means the exec failed, NOT that the device
    agreed. This is the case a naive `if ident and ident != robot` check
    passes silently."""
    assert deploy.identity_verdict("", "tovez") == deploy.IDENT_UNREADABLE


def test_every_verdict_is_distinct():
    """Four outcomes, four values -- so main() can report each one
    differently instead of collapsing three of them into 'ok'."""
    verdicts = {deploy.IDENT_MATCH, deploy.IDENT_MISMATCH,
                deploy.IDENT_FRESH, deploy.IDENT_UNREADABLE}
    assert len(verdicts) == 4


def test_mismatch_has_an_override_flag_that_exists():
    """The refusal message names --force-identity. It used to name
    --port, which resolve_port() honours but the guard ignores, so the
    documented escape hatch did nothing."""
    src = (REPO_ROOT / "tools" / "deploy.py").read_text()
    assert '"--force-identity"' in src
    assert "force_identity" in src


def test_port_field_is_never_used_to_resolve_a_target():
    """config/devices.json's `port` entries go stale on every replug --
    they were wrong for all three robots on 2026-08-20. resolve_port()
    must match on UID and read the live bus instead."""
    src = (REPO_ROOT / "tools" / "deploy.py").read_text()
    body = src[src.index("def resolve_port"):src.index("IDENT_MATCH =")]
    assert 'entry.get("board_name")' in body
    assert '"port"' not in body, "resolve_port must not read the stale port field"


def test_active_robot_points_at_a_file_that_exists():
    """Copied from radio-robot-elite, where the configs lived in
    data/robots/. Here they are flat in data/, so the pointer dangled --
    a stale identity pointer is precisely this issue's failure mode."""
    doc = json.loads((REPO_ROOT / "data" / "active_robot.json").read_text())
    target = REPO_ROOT / doc["path"]
    assert target.is_file(), "active_robot.json points at missing %s" % doc["path"]


def test_devices_registry_agrees_with_itself():
    """Each entry is keyed by UID; the key and the `uid` field must
    match, and board_name/device_name must agree. A registry that
    disagrees with itself cannot arbitrate an identity collision."""
    devices = json.loads((REPO_ROOT / "config" / "devices.json").read_text())
    assert devices, "config/devices.json is empty"
    for uid, entry in devices.items():
        assert entry["uid"] == uid, "key %s != uid field %s" % (uid, entry["uid"])
        assert entry["board_name"] == entry["device_name"], (
            "%s: board_name %r != device_name %r"
            % (uid, entry["board_name"], entry["device_name"]))


def test_robot_names_are_unique_in_the_registry():
    """Two boards claiming one name is the collision this issue is about.
    The registry itself must at least never encode one."""
    devices = json.loads((REPO_ROOT / "config" / "devices.json").read_text())
    names = [e["board_name"] for e in devices.values()]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, "config/devices.json maps these names to >1 board: %s" % dupes
