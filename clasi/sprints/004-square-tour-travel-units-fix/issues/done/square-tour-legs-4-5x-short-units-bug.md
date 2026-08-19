---
status: done
sprint: '004'
tickets:
- 004-001
---

# Square tour legs run ~4–5× short — travel-units bug

## Description

Stakeholder observed the button-A square tour live on zetuv
(2026-08-19): each "500 mm" leg turns the wheels only ~270° — less
than one revolution. A Nezha wheel (~145 mm circumference) needs
~3.3–3.6 revolutions for 500 mm, so legs are ~4–5× short. "I think you
got some unit problems here."

Golden measurement from the stakeholder: current leg ≈ 270° of wheel
rotation. Sprint-002 run-1 logged leg encoder deltas of ~650–811
counts, so counts-per-revolution is empirically ≈ 870–1080 — compare
against what data/zetuv.json (template-derived from tovez_nocal.json)
and src/demo_square.py's counts-per-mm math assume.

Likely root cause: demo_square.py derives encoder targets from
template travel-calibration values that were never measured (zetuv.json
is wiring-verified only), and/or mixes the counts-native vs mm-based
conventions of the rebaked kernel (see S001-004's finding that the
vendored leaf is the 2026-08-15 counts-native rebake).

Fix expectations:
- Audit the counts↔mm↔degrees math end to end (demo_square.py,
  data/zetuv.json wheel/encoder fields, what diffdrive output()
  actually reports — counts vs mm).
- Correct using the best available reference: data/tovez.json carries
  REAL travel calibration for the same Nezha kit hardware — borrowing
  it for zetuv is acceptable with an explicit provenance note
  (uniform kit), cross-checked against the empirical
  counts-per-rev ≈ 870–1080 above. If they disagree, the empirical
  bench number wins.
- Re-verify on the bench (REPL-triggered handler run): leg deltas
  should scale to ~3.3+ wheel revolutions each (counts ≈ 4–5× the old
  650–811), pivots proportionally sane, stop-verify clean.
- Update the bench log; correct the sprint-002 bench-log claim of
  "500 mm legs" with a pointer to this fix.
- Leave the device armed (main.py idle prompt) for the stakeholder to
  press A and hear the full-length tour.

Bench facts: zetuv UID 9906360200052820312bde85515a72e6000000006e052820,
port /dev/cu.usbmodem2121202; getez/zavaz are relays — never touch;
on-device copies are docstring-stripped (repo sources are canonical).
