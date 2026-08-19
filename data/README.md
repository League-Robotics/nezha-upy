# Robot Configuration Data

## Provenance

Copied **once** from
`/Volumes/Proj/proj/RobotProjects/radio-robot-elite/data/robots/` on
**2026-08-19** (sprint 001, ticket 002):

- `robot_config.schema.json`
- `tovez.json`
- `tovez_nocal.json`
- `gopiv.json`
- `togov.json`
- `active_robot.json`

**This is NOT a synced or vendored directory** — unlike `vendor/`
(which is synced from radio-robot via `src/scripts/sync_upy.py` there
and never edited here), `data/` is normal tracked source in this repo,
free to diverge and evolve independently. See sprint 001's
`clasi/sprints/001-python-first-firmware-image-m0-m6/sprint.md`
("Design Rationale" → "Decision: robot config data is copied once, not
vendored/synced") for the full rationale: radio-robot-elite has no
export tooling for this purpose, building one is out-of-scope
radio-robot-side work, and this repo's `config.py` (ticket 007) is
expected to evolve the schema/validation independently — which
conflicts with a never-edit vendor convention. Nothing here
auto-updates; a future re-copy from radio-robot-elite would need to be
a deliberate, reviewed action, not an automated sync.

## Deviations applied from the source at copy time

### `gopiv.json` — wiring fix added (was missing in source)

`docs/design/specification.md` §8 states "gopiv true wiring:
`left_port: 2, right_port: 1, fwd_sign_left: +1, fwd_sign_right: -1`
(per gopiv.json `_port_note`)". **Verified, not assumed:** the source
`gopiv.json` in radio-robot-elite has no `left_port`, `right_port`, or
`_port_note` fields at all in its `motors` group (confirmed by
inspection and by a `grep -n port` pass across the whole source
directory). `fwd_sign_left: 1` / `fwd_sign_right: -1` were already
present in the source and already match the spec's stated wiring.

This repo's copy adds `left_port: 2` and `right_port: 1` to
`data/gopiv.json`'s `motors` group, plus a `_port_note` documenting
that the fields were added here rather than carried over, per
`docs/design/specification.md` §8 and sprint 001's Architecture Design
Rationale ("the gopiv wiring-fix landing (M1)"). This is this repo's
copy-time application of an already-made decision, not a fresh
derivation from gopiv-specific bench data — unlike `tovez.json`'s own
`_port_note`, which documents an actual measured A/B on that robot.

### `tovez.json` — radio channel: no change needed

The bench convention (issue
`test-on-microbit-tovez-radio-channel-3.md`) is tovez on radio channel
3. **Verified, not assumed:** the source `tovez.json`'s
`connection.radio_channel` was already `3`. No change was applied;
this is recorded here only so a future maintainer doesn't wonder
whether it was silently patched.

## Known gap: per-robot JSON does not yet fully validate against the schema

`robot_config.schema.json`'s own top-level `description` field already
says this: "`data/robots/*.json` does not yet validate against this
document -- the JSON reshape migration is sprint 132 ticket 017,
scheduled last by explicit stakeholder direction." Confirmed here with
`jsonschema.validate()`: every one of the four per-robot files fails
schema validation as a whole document, because the schema's
`additionalProperties: false` (at the top level and within several
groups) rejects fields the files still carry that the schema hasn't
caught up to yet — extra top-level groups (`schema_version`, `wheels`,
`encoders`, `gripper`, `peripherals`, and per-robot extras like
`gopiv.json`'s `_provenance_note` or `togov.json`'s
`_mecanum_geometry`), plus free-text `_note`-style documentation
fields embedded inside otherwise-modeled groups (e.g. `tovez.json`
motors' own `_port_note`).

`tests/test_robot_config_data.py` therefore validates the schema's
field-level type/range constraints per group, for whichever fields are
actually present, instead of a whole-document `jsonschema.validate()`
— this is the "hand-rolled required-key check" alternative ticket 002's
acceptance criteria explicitly allow. This is expected to change once
ticket 007's `config.py` and the schema evolve together; this data
copy does not attempt to pre-empt that reshape.

## On-device filesystem size (sprint 002 ticket 001 finding)

A fully-annotated robot JSON from this directory does **not** fit the
built image's on-device filesystem (`0x6d000..0x73000`, 24,576 bytes
before per-file overhead — see `micropython-microbit-v2/src/MICROBIT.hex`'s
own build-time layout table). `data/tovez.json` alone is ~59 KB; even the
smaller `data/tovez_nocal.json` (~14 KB) and this sprint's own
`data/zetuv.json` (~20 KB) exceeded free space when copied verbatim to a
real device as `/robot.json` (`docs/bench-log-zetuv-2026-08-19.md` §5).
Every `_`-prefixed key in these files is free-text documentation
`config.py`'s field validation already ignores by convention (see "Known
gap" below), so stripping them before copying to a device is
behavior-preserving. **Do this whenever flashing any of this directory's
robot JSON onto real hardware** — the checked-in files here stay the full
documented source; only the on-device copy needs stripping.

## Secrets check

Checked at copy time (`grep -n -i` across all six source files for
`password`, `ssid`, `psk`, `secret`, `wifi_pass`, `api_key`, `token`):
no matches. No WiFi credentials were found in any of the copied files.
`tovez.json` and `gopiv.json` carry a `connection.wifi_ip` field (a
LAN IP address, not a credential) — left as-is.
