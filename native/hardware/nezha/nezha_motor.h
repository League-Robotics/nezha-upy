// nezha_motor.h -- router, not a copy. vendor/nezha_motor.cpp (never
// edited -- see CLAUDE.md) opens with
// `#include "hardware/nezha/nezha_motor.h"`, the include path it had in
// radio-robot's src/firm tree. This repo's vendor/ is flat (no
// hardware/nezha/ subdirectory), so this one-line redirect satisfies that
// literal include path without touching the vendored .cpp. Add
// -Inative to the diffdrive build's include flags so the quote-form
// `#include "hardware/nezha/nezha_motor.h"` resolves here.
#pragma once
#include "../../../vendor/nezha_motor.h"
