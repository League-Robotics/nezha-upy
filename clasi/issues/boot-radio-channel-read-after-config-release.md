---
status: pending
---

# boot.py reads radio_channel after releasing robot_config — always uses default channel 7

Found during sprint 007 ticket 006 (the v6 cutover), pre-existing —
not introduced by the cutover.

`src/core/boot.py`'s `run()` releases the parsed config document
(`result.robot_config = None`, the deliberate ~6.9 KB heap reclaim,
step 3) **before** the radio bring-up reads
`config.radio_channel(result.robot_config)`. The guard is
`if result.robot_config is not None:` — which is now always false —
so every boot silently falls to `DEFAULT_RADIO_CHANNEL = 7`,
regardless of the robot JSON's `connection.radio_channel` (tovez's is
3 per `data/tovez.json` and the bench fixture in
`docs/bench-acceptance-procedures.md` §A.2).

## Why it has not bitten visibly yet

Every radio bench session so far either used the spike/relay tooling
pinned to its own channel or didn't exercise the fleet-channel
convention; the WiFi and USB planes don't touch it. The first
`rogo`-convention radio session against a robot whose JSON says
channel 3 will simply hear nothing.

## Fix shape

Extract the channel scalar BEFORE the release (alongside the other
scalars boot already extracts — identity strings, diffdrive kwargs),
then release. One-line move; needs a boot-sequence unit test asserting
the configured channel actually reaches `radio_shim.RadioLink`.

## Related

Recorded in ticket 006's completion notes
(`clasi/sprints/007-.../tickets/done/006-...md`).
