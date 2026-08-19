// moddiffdrive.cpp -- MicroPython C++ module: diffdrive + robotio.
//
// diffdrive wraps the vendored DiffDrive::DifferentialDrive kernel
// (vendor/differential_drive.{h,cpp}, compiled unedited) over this
// platform's four ports (native/platform_ports.h, native/nezha_leaf.h),
// plus this ticket's own safety additions the kernel does not provide by
// itself: a pre-VM boot zero-write, a VM-hook zero-only starvation
// watchdog (native/watchdog.h), and a 5000 ms binding-level lease
// ceiling (tighter than and independent of the kernel's own 3,600,000 ms
// kLeaseMax -- see driveWithLeaseCeiling() below).
//
// robotio.i2c_xfer() exposes the SAME I2cBroker instance the kernel
// leaves use (native/i2c_broker.h), so Python sensor traffic and the
// kernel's own Nezha traffic share one clearance ledger -- spec Section 5
// "One I2C ledger."
//
// API (per this ticket): diffdrive.configure/begin/start/drive/
// driveDuty/neutral/estop/output/lastError/cycleOverrunCount,
// robotio.i2c_xfer. See native/README.md for the full contract.
//
// Deliberately returns STATUS VALUES (strings) rather than raising
// mp_raise_* from C++ logic for expected refusal paths -- reference/
// vevov-micropython-spike-handoff.md's Challenge 2 documents this C++/MP
// NLR interaction as fragile in this exact binding shape ("success-path
// returns were much safer than exception-path exits"); mp_arg_parse's own
// OWN exceptions (stock MP C code, not ours) still apply for malformed
// calls.

extern "C" {
#include "py/obj.h"
#include "py/runtime.h"
}

#include <cstring>
#include <new>

#include "../vendor/differential_drive.h"
#include "hal/device_config.h"
#include "i2c_broker.h"
#include "nezha_leaf.h"
#include "nezha_wire.h"
#include "platform_ports.h"
#include "watchdog.h"

namespace {

// 5000 ms binding-level lease ceiling (spec Sections 3/5/8; PLAN.md's
// landmine ledger L4: a units slip once ran wheels 8+ minutes
// unsupervised). Independent of and far tighter than the kernel's own
// DiffDrive::DifferentialDrive::kLeaseMax (3,600,000 ms) -- this ticket's
// binding REJECTS a longer lease outright rather than clamping it, so a
// caller's bug is visible (a refused command), not silently truncated
// into something that looks like it worked.
constexpr uint32_t kBindingLeaseMaxMs = 5000;

// Platform ports -- module-lifetime singletons, constructed once at
// static-init time (all three are trivially default-constructible; none
// of them touch hardware in their constructors).
Native::PlatformClock g_clock;
Native::PlatformSleeper g_sleeper;
Native::PlatformFiberLauncher g_launcher;

// The kernel's two Motor leaves and the DifferentialDrive object itself
// cannot be default-constructed (see native/nezha_leaf.h /
// vendor/differential_drive.h -- both constructors require real
// references/config supplied at configure() time, which is a runtime
// Python call, not a compile-time constant). Placement-new into static
// storage is the standard embedded-C++ way to defer construction of a
// non-default-constructible object without heap allocation/exceptions
// (this build is -fno-exceptions) -- see configure() below.
//
// SCOPE NOTE for ticket 007: configure() is designed to be called ONCE
// per boot. A second call re-placement-news over the same storage
// (equivalent to "reconfigure resets everything"), which is a reasonable
// M1 behavior but not a live reconfigure -- extending this to a real
// guarded reconfigure() (mirroring Hal::Motor::reconfigure()'s own
// at-rest guard) is left to whichever ticket wires the full per-robot
// config surface.
alignas(Native::NezhaLeaf) unsigned char g_leftLeafStorage[sizeof(Native::NezhaLeaf)];
alignas(Native::NezhaLeaf) unsigned char g_rightLeafStorage[sizeof(Native::NezhaLeaf)];
alignas(DiffDrive::DifferentialDrive) unsigned char
    g_kernelStorage[sizeof(DiffDrive::DifferentialDrive)];
alignas(Native::Watchdog) unsigned char g_watchdogStorage[sizeof(Native::Watchdog)];

Native::NezhaLeaf* g_leftLeaf = nullptr;
Native::NezhaLeaf* g_rightLeaf = nullptr;
DiffDrive::DifferentialDrive* g_kernel = nullptr;
Native::Watchdog* g_watchdog = nullptr;

const char* statusToStr(DiffDrive::DifferentialDrive::Status status) {
  using Status = DiffDrive::DifferentialDrive::Status;
  switch (status) {
    case Status::kOk:
      return "ok";
    case Status::kRefusedUnconfigured:
      return "refused_unconfigured";
    case Status::kRefusedNotBegun:
      return "refused_not_begun";
    case Status::kRefusedEstopped:
      return "refused_estopped";
    case Status::kRefusedNonFinite:
      return "refused_non_finite";
    case Status::kCadencePreserved:
      return "cadence_preserved";
  }
  return "refused_unknown";
}

mp_obj_t statusObj(DiffDrive::DifferentialDrive::Status status) {
  const char* s = statusToStr(status);
  return mp_obj_new_str(s, strlen(s));
}

}  // namespace

// ---------------------------------------------------------------------
// Boot zero-write -- called from main.c BEFORE gc_init()/mp_init(), i.e.
// before the VM exists at all. Spec Section 5 / this ticket's acceptance
// criteria: the Nezha brick latches its last commanded speed across an
// nRF52 reset, so a reset mid-drive must be silenced immediately, before
// any Python (including a student's own boot code) can run. The exact
// wiring is not yet known this early (Python has not called configure()
// yet), so this defensively sweeps every physically possible port
// (1-4) rather than only the two a robot happens to use.
// ---------------------------------------------------------------------
extern "C" void moddiffdrive_boot_zero_write(void) {
  Native::I2cBroker& broker = Native::I2cBroker::instance();
  for (uint32_t port = 1; port <= 4; ++port) {
    Native::writeNezhaZeroDuty(broker, port);
  }
}

// ---------------------------------------------------------------------
// VM-hook starvation watchdog entry point -- called from
// MICROPY_VM_HOOK_POLL (mpconfigport.h, patched by build.sh's
// --with-diffdrive step). See native/watchdog.h for the full safety
// argument (never yields; cheap on every call except the rare fault
// path). No-ops before configure() has run (g_watchdog is null).
// ---------------------------------------------------------------------
extern "C" void moddiffdrive_vm_hook(void) {
  if (g_watchdog != nullptr) {
    g_watchdog->poll();
  }
}

// ---------------------------------------------------------------------
// diffdrive.configure(left_port, right_port, fwd_sign_left=1,
//                      fwd_sign_right=1, max_duty=0.0,
//                      full_duty_velocity=0.0, cycle_period_ms=24)
//
// Binds the two physical wheel ports/signs and the kernel's core
// authority fields. Every default is fail-closed (max_duty=0.0,
// full_duty_velocity=0.0), matching DiffDrive::Config's own
// "EVERY DEFAULT IS FAIL-CLOSED" contract (differential_drive.h) rather
// than substituting a convenience non-zero default that would undermine
// it. The remaining Hal::MotorConfig write-shaping fields (slew rate,
// reversal dwell, output deadband) take this codebase's established
// bench defaults (reference/modrobot/modrobot.cpp's
// kDefaultSlewRate/kDefaultReversalDwell/kDefaultDeadband) until ticket
// 007 wires the full per-robot JSON.
// ---------------------------------------------------------------------
extern "C" mp_obj_t diffdrive_configure_fn(size_t n_args, const mp_obj_t* pos_args,
                                            mp_map_t* kw_args) {
  enum {
    kArgLeftPort,
    kArgRightPort,
    kArgFwdSignLeft,
    kArgFwdSignRight,
    kArgMaxDuty,
    kArgFullDutyVelocity,
    kArgCyclePeriodMs,
  };
  static const mp_arg_t allowed[] = {
      {MP_QSTR_left_port, MP_ARG_INT | MP_ARG_REQUIRED, {.u_int = 0}},
      {MP_QSTR_right_port, MP_ARG_INT | MP_ARG_REQUIRED, {.u_int = 0}},
      {MP_QSTR_fwd_sign_left, MP_ARG_INT, {.u_int = 1}},
      {MP_QSTR_fwd_sign_right, MP_ARG_INT, {.u_int = 1}},
      {MP_QSTR_max_duty, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_full_duty_velocity, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_cycle_period_ms, MP_ARG_INT, {.u_int = 24}},
  };
  mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
  mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);

  Hal::MotorConfig leftConfig;
  leftConfig.port = static_cast<uint32_t>(args[kArgLeftPort].u_int);
  leftConfig.fwdSign = args[kArgFwdSignLeft].u_int;
  leftConfig.slewRate = 0.0f;          // NezhaMotor substitutes its own
                                        // kDefaultSlewRate for <= 0.
  leftConfig.reversalDwell = 100.0f;   // [ms]
  leftConfig.outputDeadband = 0.03f;   // [-1, 1]
  leftConfig.writeThrottle = 0.0f;     // disabled

  Hal::MotorConfig rightConfig = leftConfig;
  rightConfig.port = static_cast<uint32_t>(args[kArgRightPort].u_int);
  rightConfig.fwdSign = args[kArgFwdSignRight].u_int;

  Native::I2cBroker& broker = Native::I2cBroker::instance();

  g_leftLeaf = new (g_leftLeafStorage) Native::NezhaLeaf(broker, leftConfig);
  g_rightLeaf = new (g_rightLeafStorage) Native::NezhaLeaf(broker, rightConfig);
  g_kernel = new (g_kernelStorage) DiffDrive::DifferentialDrive(
      *g_leftLeaf, *g_rightLeaf, g_clock, g_sleeper, g_launcher);

  DiffDrive::DifferentialDrive::Config cfg = g_kernel->config();
  cfg.maxDuty = mp_obj_get_float(args[kArgMaxDuty].u_obj);
  cfg.fullDutyVelocity = mp_obj_get_float(args[kArgFullDutyVelocity].u_obj);
  cfg.cyclePeriod = static_cast<uint32_t>(args[kArgCyclePeriodMs].u_int);
  const DiffDrive::DifferentialDrive::Status status = g_kernel->setConfig(cfg);

  g_watchdog = new (g_watchdogStorage) Native::Watchdog(*g_kernel, broker);
  g_watchdog->setPorts(leftConfig.port, rightConfig.port);

  return statusObj(status);
}

extern "C" mp_obj_t diffdrive_begin_fn(void) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  return statusObj(g_kernel->begin());
}

extern "C" mp_obj_t diffdrive_start_fn(void) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  return statusObj(g_kernel->start());
}

extern "C" mp_obj_t diffdrive_drive_fn(mp_obj_t velocityObj, mp_obj_t twistObj,
                                        mp_obj_t leaseObj) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  const mp_int_t leaseMs = mp_obj_get_int(leaseObj);
  if (leaseMs < 0 || static_cast<uint32_t>(leaseMs) > kBindingLeaseMaxMs) {
    // REJECT, never clamp -- see kBindingLeaseMaxMs's own comment.
    return mp_obj_new_str("refused_lease_ceiling", strlen("refused_lease_ceiling"));
  }
  const float velocity = mp_obj_get_float(velocityObj);
  const float twist = mp_obj_get_float(twistObj);
  return statusObj(g_kernel->drive(velocity, twist, static_cast<uint32_t>(leaseMs)));
}

extern "C" mp_obj_t diffdrive_driveDuty_fn(mp_obj_t dutyLeftObj, mp_obj_t dutyRightObj,
                                            mp_obj_t leaseObj) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  const mp_int_t leaseMs = mp_obj_get_int(leaseObj);
  if (leaseMs < 0 || static_cast<uint32_t>(leaseMs) > kBindingLeaseMaxMs) {
    return mp_obj_new_str("refused_lease_ceiling", strlen("refused_lease_ceiling"));
  }
  const float dutyLeft = mp_obj_get_float(dutyLeftObj);
  const float dutyRight = mp_obj_get_float(dutyRightObj);
  return statusObj(
      g_kernel->driveDuty(dutyLeft, dutyRight, static_cast<uint32_t>(leaseMs)));
}

extern "C" mp_obj_t diffdrive_neutral_fn(void) {
  if (g_kernel != nullptr) {
    g_kernel->neutral();
  }
  return mp_const_none;
}

extern "C" mp_obj_t diffdrive_estop_fn(void) {
  if (g_kernel != nullptr) {
    g_kernel->estop();
  }
  return mp_const_none;
}

extern "C" mp_obj_t diffdrive_output_fn(void) {
  mp_obj_t dict = mp_obj_new_dict(20);
  if (g_kernel == nullptr) {
    return dict;
  }
  const DiffDrive::DifferentialDrive::Output out = g_kernel->output();

  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_cycleCount),
                     mp_obj_new_int_from_uint(out.cycleCount));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_cycleOverrunCount),
                     mp_obj_new_int_from_uint(out.cycleOverrunCount));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_cycleBusy),
                     mp_obj_new_int_from_uint(out.cycleBusy));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_cyclePeriodMeasured),
                     mp_obj_new_int_from_uint(out.cyclePeriodMeasured));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_positionLeft),
                     mp_obj_new_float(out.positionLeft));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_positionRight),
                     mp_obj_new_float(out.positionRight));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_velocityLeft),
                     mp_obj_new_float(out.velocityLeft));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_velocityRight),
                     mp_obj_new_float(out.velocityRight));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_velocity),
                     mp_obj_new_float(out.velocity));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_twist), mp_obj_new_float(out.twist));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_appliedDutyLeft),
                     mp_obj_new_float(out.appliedDutyLeft));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_appliedDutyRight),
                     mp_obj_new_float(out.appliedDutyRight));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_ready), mp_obj_new_bool(out.ready));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_estopped),
                     mp_obj_new_bool(out.estopped));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_leaseExpired),
                     mp_obj_new_bool(out.leaseExpired));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_stallHalted),
                     mp_obj_new_bool(out.stallHalted));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_connectedLeft),
                     mp_obj_new_bool(out.connectedLeft));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_connectedRight),
                     mp_obj_new_bool(out.connectedRight));

  // The watchdog's own state -- NOT part of vendor/'s Output (a vendor/
  // struct this repo never edits): this is this ticket's own visible-
  // fault addition, spec Section 7.2.
  const bool fault = g_watchdog != nullptr && g_watchdog->faultLatched();
  const uint32_t tripCount = g_watchdog != nullptr ? g_watchdog->tripCount() : 0;
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_watchdogFault),
                     mp_obj_new_bool(fault));
  mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_watchdogTripCount),
                     mp_obj_new_int_from_uint(tripCount));
  return dict;
}

extern "C" mp_obj_t diffdrive_lastError_fn(void) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  return statusObj(g_kernel->lastError());
}

// Raw accessor required by this ticket's acceptance criteria ("at minimum
// via a raw accessor on the diffdrive module") -- redundant with
// output()'s own cycleOverrunCount field, kept as a direct, single-value
// call so a bench script does not need to build/parse a dict just to read
// this one counter.
extern "C" mp_obj_t diffdrive_cycleOverrunCount_fn(void) {
  if (g_kernel == nullptr) {
    return mp_obj_new_int_from_uint(0);
  }
  return mp_obj_new_int_from_uint(g_kernel->output().cycleOverrunCount);
}

// ---------------------------------------------------------------------
// robotio.i2c_xfer(address, write_data=b'', read_len=0, repeated=False,
//                   pre_clear=0, post_clear=0)
//
// -> int status                 when read_len == 0 (write-only)
// -> (int status, bytes data)   when read_len > 0 (write [if any] then
//                                read, both through the SAME I2cBroker
//                                instance the kernel leaves use)
//
// The one shared I2C ledger's Python-facing door -- spec Section 5.
// ---------------------------------------------------------------------
extern "C" mp_obj_t robotio_i2c_xfer_fn(size_t n_args, const mp_obj_t* pos_args,
                                         mp_map_t* kw_args) {
  enum {
    kArgAddress,
    kArgWriteData,
    kArgReadLen,
    kArgRepeated,
    kArgPreClear,
    kArgPostClear,
  };
  static const mp_arg_t allowed[] = {
      {MP_QSTR_address, MP_ARG_INT | MP_ARG_REQUIRED, {.u_int = 0}},
      {MP_QSTR_write_data, MP_ARG_OBJ, {.u_obj = mp_const_none}},
      {MP_QSTR_read_len, MP_ARG_INT, {.u_int = 0}},
      {MP_QSTR_repeated, MP_ARG_BOOL, {.u_bool = false}},
      {MP_QSTR_pre_clear, MP_ARG_INT, {.u_int = 0}},
      {MP_QSTR_post_clear, MP_ARG_INT, {.u_int = 0}},
  };
  mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
  mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);

  const uint16_t address = static_cast<uint16_t>(args[kArgAddress].u_int);
  const bool repeated = args[kArgRepeated].u_bool;
  const uint32_t preClear = static_cast<uint32_t>(args[kArgPreClear].u_int);
  const uint32_t postClear = static_cast<uint32_t>(args[kArgPostClear].u_int);
  const mp_int_t readLen = args[kArgReadLen].u_int;

  Native::I2cBroker& broker = Native::I2cBroker::instance();

  int writeStatus = 0;
  if (args[kArgWriteData].u_obj != mp_const_none) {
    mp_buffer_info_t bufinfo;
    mp_get_buffer_raise(args[kArgWriteData].u_obj, &bufinfo, MP_BUFFER_READ);
    writeStatus = broker.write(address, static_cast<uint8_t*>(bufinfo.buf),
                                static_cast<int>(bufinfo.len), repeated, preClear,
                                readLen > 0 ? 0 : postClear);
  }

  if (readLen <= 0) {
    return mp_obj_new_int(writeStatus);
  }

  // Bounded: this is a Nezha/OTOS/line/color-class sensor bus, not a bulk
  // transfer -- reject anything that would risk this VM-hook-adjacent
  // stack frame's headroom.
  constexpr mp_int_t kMaxReadLen = 64;
  if (readLen > kMaxReadLen) {
    mp_raise_ValueError(MP_ERROR_TEXT("read_len too large"));
  }
  uint8_t buf[kMaxReadLen] = {};
  const int readStatus =
      broker.read(address, buf, static_cast<int>(readLen), repeated, preClear, postClear);
  const int status = (writeStatus != 0) ? writeStatus : readStatus;

  mp_obj_t result[2] = {mp_obj_new_int(status),
                         mp_obj_new_bytes(buf, static_cast<size_t>(readLen))};
  return mp_obj_new_tuple(2, result);
}
