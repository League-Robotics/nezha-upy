# nezha-upy — agent orientation

Read [PLAN.md](PLAN.md) first: it is the execution plan (milestones
M0–M7, each with a command-shaped gate), the architecture, and the
paid-for landmine ledger from the prior MicroPython exploration. Work
the milestones in order; **M1 is the highest-risk milestone and nothing
proceeds until its gate scores.**

## Ground rules

- `vendor/` is SYNCED from radio-robot (`src/scripts/sync_upy.py`
  there) and is never edited here. If the kernel or leaf needs a
  change, it happens in radio-robot, gated by its own tests, then
  re-synced. The vendored copy is the reference for the native module.
- PLAN.md's file paths of the form `src/...` / `src/firm/...` /
  `.worktrees/...` refer to the **radio-robot** repo (and its old
  MicroPython worktree) unless the plan's "Repository layout (new
  repo)" section says otherwise. What this repo needs from those
  sources is either already vendored here or arrives with the forked
  build machinery.
- The build machinery (`build.sh`, `codal_overlay.json`, `patches/`,
  plus the modrobot/wifi_stdio pattern references) forks from the old
  exploration worktree — if it is not yet present in this repo, that
  copy is still pending; do offline-verifiable work first (M2's wire
  codec against `tests/fixtures/wire_golden_vectors.txt` is fully
  self-contained) rather than re-deriving the build from scratch.
- Everything hardware-facing in PLAN.md's verification section assumes
  the bench conventions of radio-robot (deploy by UID, `--clean`
  builds, ~5 s post-flash settle, power-cycle the WiFi module). Do not
  drive hardware without those.
- No secrets in the repo: `wifi_secrets.json` is gitignored and
  provided locally.

## Style

Python: straightforward MicroPython-clean code (no f-string debugging
left behind, no host-only stdlib). C/C++: Google style as adapted in
radio-robot (`lowerCamelCase` functions, `UpperCamelCase` types, units
in `// [unit]` trailing comments, never in identifiers).
