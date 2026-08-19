// device_types.h -- the narrow slice of radio-robot's Hal:: value-type
// contract that vendor/nezha_motor.{h,cpp} and vendor/motor_armor.h
// actually reference.
//
// NOT a vendor/ sync. radio-robot's own src/firm/hal/device_types.h is a
// live, evolving file; the vendored vendor/nezha_motor.h in this repo is a
// frozen snapshot from whatever commit sync_upy.py last ran against, and
// the two have already diverged (radio-robot-elite's current motor.h still
// declares applyTravelCalib(), which vendor/motor_armor.h's own comment
// says was already deleted at sync time -- confirmed 2026-08-19 while
// implementing this ticket). Copying radio-robot's CURRENT hal/*.h would
// not even compile against the vendored snapshot. This header instead
// reverse-engineers the exact narrow contract vendor/nezha_motor.h and
// vendor/motor_armor.h need, authored fresh in native/ (never in vendor/),
// so the vendored leaf compiles unedited. See native/README.md.
#pragma once

#include <cstdint>

namespace Hal {

// Coast vs brake. vendor/nezha_motor.cpp's setNeutral() takes this by
// value and stores it, but never actually branches on Coast vs Brake --
// the Nezha brick maps both to the same 0x60 speed-0 write (see
// nezha_motor.h's own setNeutral() doc comment). Kept as a real enum
// (not folded away) because it is part of vendor/nezha_motor.h's
// unmodifiable override signature.
enum class Neutral : uint8_t {
  Coast,
  Brake,
};

}  // namespace Hal
