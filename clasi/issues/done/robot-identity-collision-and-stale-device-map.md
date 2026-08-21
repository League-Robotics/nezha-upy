---
status: done
---

# Two boards announce the same robot identity; device map is stale

Two physically distinct micro:bits on the bench both identify as
`tovez`, and `config/devices.json` no longer matches reality. Bench
work cannot reliably tell which robot it is driving, and per-robot
wheel calibration is selected by that identity.

## Evidence (bench, 2026-08-20)

Connected boards, by DAPLink UID:

| UID (prefix) | devices.json says | Board actually says |
| --- | --- | --- |
| `...a8fdb5e413abb276` | tovez | on-device `robot.json`: `"robot_name":"tovez"` |
| `...b8e12372c44f4f67` | vevov | v5 `ID` verb: `ID:diffdrive:tovez:1.0.0` |
| `...17449eac613c0332` | getez (relay) | — |
| `...e9d16c3809a44554` | zavaz (relay) | — |

- Two boards claim `tovez`.
- zetuv's registered UID `...312bde85515a72e6` did not appear in any
  enumeration during the session, though the stakeholder reports zetuv
  is the robot on the bench — consistent with the bench robot having
  been flashed or configured with another robot's identity.
- `config/devices.json` `port` fields are stale (it lists tovez at
  `2121102` and vevov at `2121202`; neither matched). Port numbers churn
  across replug, so only the UIDs carry meaning — and the table above
  shows at least one UID mapping is also wrong.
- `data/active_robot.json` points at `data/robots/tovez.json`, but the
  configs live at `data/tovez.json`. That path does not resolve.

## Why this is more than cosmetic

Per-robot wheel calibration is selected by identity:

| config | ticks_per_rev | ticks_per_mm |
| --- | ---: | ---: |
| `data/zetuv.json` | 975 | 3.4484 |
| `data/tovez.json` | 3600 | 12.7602 |

The ratio is 3.70. Commit `6c5f57c` records commanded 500 mm driving
~150 mm — a 3.3x error of exactly this character. That commit's message
and its bench log (`docs/bench-log-zetuv-2026-08-19.md`) describe zetuv,
but the file it actually changed is `data/tovez.json`. A robot driving
one robot's config while carrying another's encoders reproduces this
class of failure, and it will recur silently on the next calibration
session.

Also: `data/vevov.json` does not exist at all, so a board mapped to
vevov has no config to load.

## Proposed work

1. Establish ground truth per board: read the on-device identity
   (`robot.json` over the filesystem, or the `ID` verb over serial)
   rather than trusting `config/devices.json`. This is the only check
   that proved reliable this session.
2. Resolve the collision: decide which physical chassis is zetuv and
   which is tovez, and re-deploy the correct `robot.json` to each.
3. Regenerate `config/devices.json` from live enumeration plus
   on-device identity. Consider dropping the `port` field entirely, or
   marking it advisory, since it is guaranteed to go stale.
4. Fix `data/active_robot.json`'s path, or the loader that reads it.
5. Guard rail: refuse to run a calibration or bench procedure when the
   on-device identity does not match the config file being applied.

Item 5 is the one that would have prevented the 3.3x error.

Related: [[tlm-stream-ignores-tlm-off]] — the telemetry flood is what
prevented identifying these boards by name in the first place.

---

## Resolution

Four of the five proposed items are done. Item 2 needs a board that is
not on the bench and is split out as
[[reflash-the-vevov-spike-board-off-tovez-identity]].

### The collision is explained, not mysterious

The board announcing `ID:diffdrive:tovez:1.0.0` on UID
`...b8e12372c44f4f67` is the **vevov MicroPython spike**.
`reference/vevov-micropython-spike-handoff.md` line 8 records that exact
UID, and line 418 records the protocol it speaks
(`PING -> PONG  # cleartext verbs + binary TLM: push frames`). It is a
deliberately retained reference artifact running a different codebase.

That also resolves the sibling issue
[[tlm-stream-ignores-tlm-off]] — same board, same firmware, and this
repo emits neither a 3-field `TLM:` line nor an `ID:diffdrive:...`
reply anywhere (grep-verified).

So there is no identity collision *within the deployed fleet*. There is
one board carrying a name that is not its own. `mbdeploy list` today:

| UID (prefix) | name | connected |
| --- | --- | --- |
| `...a8fdb5e413abb276` | tovez | yes, `/dev/cu.usbmodem2121202` |
| `...17449eac613c0332` | getez (relay) | yes |
| `...e9d16c3809a44554` | zavaz (relay) | yes |
| `...312bde85515a72e6` | zetuv | no |
| `...b8e12372c44f4f67` | vevov | no |

### Item 5 (the one that would have prevented the 3.3x error) — done

`tools/deploy.py` reads the device's own `robot.json` and refuses to
write when it names a different robot. **Verified on hardware, both
directions**, this session:

```
$ deploy.py tovez
  target tovez on /dev/cu.usbmodem2121202
  device identity: tovez (confirmed)          -> deployed

$ deploy.py zetuv --port /dev/cu.usbmodem2121202
device identifies as 'tovez', not 'zetuv' -- refusing to deploy.
  exit 1, device filesystem unchanged
```

Two defects in that guard were found while testing it and fixed:

- **The documented escape hatch did nothing.** The refusal said "Pass
  `--port` explicitly if this is deliberate" — but `--port` is consumed
  by `resolve_port()`, and the guard runs afterwards regardless. There
  was no way to override it. Added a real `--force-identity` flag; the
  message now names it, and a test asserts the flag it names exists.
- **An unreadable probe passed silently.** `if ident and ident != robot`
  treats a *failed* exec exactly like a confirmed match. Split into four
  distinct verdicts — match / mismatch / fresh (no `robot.json` yet) /
  unreadable — each reported differently, so "confirmed" is only ever
  printed when the device actually agreed.

Five offline tests cover the rule in `tests/test_deploy_budget.py`.

### Item 3 — the `port` field is already dead, and now pinned that way

`resolve_port()` matches on **UID** and reads the live USB bus; it never
reads `port`. Demonstrated rather than asserted: `config/devices.json`
still lists tovez at `2121102`, and today's successful deploy resolved
it to `2121202`. A test now fails if `resolve_port()` ever starts
reading that field, plus two registry-consistency tests (key == `uid`
field, `board_name` == `device_name`, and no name mapped to two boards).

Left the `port` field in place: `config/devices.json` is `mbdeploy`'s
registry, not this repo's to reshape.

### Item 4 — the dangling pointer is fixed

`data/active_robot.json` pointed at `data/robots/tovez.json`. It was
copied from radio-robot-elite, where configs live under `data/robots/`;
here they are flat in `data/`, so the path never resolved. Nothing in
the repo reads the file — only tests that enumerate `data/*.json` — so
it was inert *and* wrong, which is the worse combination: a stale
identity pointer, in an issue about stale identity pointers.

Repointed to `data/tovez.json`, with a test that the path resolves.

### Item 1 — ground truth

Confirmed the method works. On the one connected robot, the on-device
filesystem holds exactly the deploy set (`robot.json`, `main.mpy`,
`demo_square.mpy`, `demo_util.mpy`, `tour_state.csv`) and nothing
foreign. Reading on-device identity is now a one-liner
(`mpremote connect <port> fs ls`, or deploy.py's own probe) rather than
the improvised procedure it was when this issue was written.

### Note on `data/vevov.json`

Still absent, as the issue says. Deliberately left absent: the vevov
board is a spike artifact, not a fleet robot, and creating a config for
it would imply otherwise. Recorded in the split-out issue instead.
