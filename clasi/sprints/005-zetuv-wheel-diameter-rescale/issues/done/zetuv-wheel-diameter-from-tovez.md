---
status: done
sprint: '005'
tickets:
- 005-001
---

# Set zetuv's wheel size to tovez's (80.77 mm) and rescale the tour

## Description

Stakeholder (2026-08-19, at the bench): "Tovez does in fact have the
correct wheel diameter. It's probably correct. You need to set the
wheel size for this Micro:bit to be the same as Tovez's."

Implication for the sprint-004 correction: the empirically solid
number is ~975 ticks per WHEEL revolution (from the stakeholder's 270°
observation vs logged deltas). The uncertain number was circumference —
sprint 004 assumed ~145 mm; with tovez's `wheel_diameter_mm = 80.77`
(circumference ≈ 253.74 mm) now confirmed by the stakeholder:

- `TICKS_PER_MM = 975 / 253.74 ≈ 3.843` (was 6.724)
- 500 mm legs → ≈ 1922 ticks (≈ 1.97 wheel revs), was 3362
  (the current tour drives ≈ 874 mm legs — 1.75× too long)
- Pivot targets rescale by the same factor (re-derive from the track
  width the config/geometry actually specifies; sanity: old 676-tick
  pivot ≈ 100.5 mm arc ⇒ track ≈ 128 mm — keep the arc, rescale the
  ticks to ≈ 386).

Changes:
- data/zetuv.json wheels block: `wheel_diameter_mm: 80.77` (provenance:
  stakeholder-confirmed, same wheels as tovez); keep the empirical
  ticks-per-wheel-rev ≈ 975 (do NOT revert to the template
  `ticks_per_rev: 360` — sprint 004 proved it wrong on the bench).
- src/demo_square.py: recompute TICKS_PER_MM and pivot targets from the
  updated config-derived numbers; update the derivation comments.
- tests referencing the constants follow the live constant (already
  wired that way in sprint 004).
- Do NOT edit data/tovez.json (its diameter is now stakeholder-blessed;
  its own `ticks_per_rev: 360` inconsistency is a tovez-bench question
  for another day — note it, don't fix it).
- Bench re-verify on zetuv (REPL-triggered handler): leg deltas
  ≈ 1922 ticks ≈ 2 wheel revs (visibly ~50 cm legs), pivots ≈ 90°,
  clean stop-verify, device left armed for the physical A press.
- Bench log updated (including the note that sprint-004's ticks were
  right in revs but wrong in mm due to the circumference assumption).

Bench facts: zetuv UID 9906360200052820312bde85515a72e6...,
port /dev/cu.usbmodem2121202 (re-verify); getez/zavaz are relays —
never touch; docstring-stripped on-device copies (repo canonical);
segment lease refresh 400 ms mechanism from sprint 004 stays.
