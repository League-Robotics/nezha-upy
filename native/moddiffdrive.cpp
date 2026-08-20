// moddiffdrive.cpp -- MicroPython C++ module: diffdrive + robotio.
//
// diffdrive wraps the vendored DiffDrive::DifferentialDrive kernel over
// this platform's four ports, plus safety additions the kernel doesn't
// provide itself: a pre-VM boot zero-write, a VM-hook starvation
// watchdog (native/watchdog.h), and a 5000 ms binding-level lease
// ceiling, tighter than the kernel's own 3,600,000 ms kLeaseMax (see
// kBindingLeaseMaxMs below).
//
// robotio.i2c_xfer() shares the same I2cBroker instance the kernel
// leaves use, so Python and kernel I2C traffic share one clearance
// ledger (spec Section 5). See native/README.md for the full contract.
//
// Two mutually exclusive execution modes, latched by whichever of
// start()/step() is called first (see Mode below): fiber mode (kernel on
// its own CODAL fiber) and step mode (host drives one kernel cycle per
// step() call, inline, at main context -- no fiber, no fiber switch).
//
// Returns status strings rather than raising from C++ logic on expected
// refusal paths -- C++/MP NLR interaction is fragile here; mp_arg_parse's
// own exceptions still apply for malformed calls. Mode-latch and
// reentrancy violations are host-usage-contract errors, not expected
// refusals, and raise directly (mp_raise_msg).

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

// 5000 ms binding-level lease ceiling (PLAN.md landmine L4: a units
// slip once ran wheels 8+ minutes unsupervised). Rejects a longer lease
// outright rather than clamping it, so a caller's bug is visible, not
// silently truncated.
constexpr uint32_t kBindingLeaseMaxMs = 5000;

// Module-lifetime singletons, constructed once at static-init time.
Native::PlatformClock g_clock;
Native::PlatformSleeper g_sleeper;
Native::PlatformFiberLauncher g_launcher;

// Mode latch: whichever of start()/step() is called first wins for the
// rest of the boot; the other then raises (vendor/differential_drive.h's
// FiberLauncher contract, :86-89). No reset -- start() is itself
// irreversible (no stop(), run() never returns), so the latch is
// boot-scoped by construction.
enum class Mode { kUnlatched, kFiber, kStep };
Mode g_mode = Mode::kUnlatched;

// step() reentrancy guard -- a scheduled callback firing during the
// settle delay's mp_hal_delay_ms() (step mode only) could otherwise
// re-enter step(). Same shape as robot_v5_service()'s inProgress guard,
// reference/modrobot/modrobot.cpp:1478-1487.
bool g_stepInFlight = false;

// The kernel's two Motor leaves and the DifferentialDrive object cannot
// be default-constructed (real references/config only exist at
// configure() time). Placement-new into static storage defers
// construction without heap allocation/exceptions (-fno-exceptions).
//
// configure() is designed to be called once per boot; a second call
// re-placement-news over the same storage (reconfigure resets
// everything) rather than a guarded live reconfigure.
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

// Boot zero-write -- called from main.c before gc_init()/mp_init(), i.e.
// before the VM exists. The Nezha brick latches its last commanded speed
// across an nRF52 reset, so a reset mid-drive must be silenced before any
// Python runs. Wiring is unknown this early, so this sweeps every
// physically possible port (1-4).
extern "C" void moddiffdrive_boot_zero_write(void) {
  Native::I2cBroker& broker = Native::I2cBroker::instance();
  for (uint32_t port = 1; port <= 4; ++port) {
    Native::writeNezhaZeroDuty(broker, port);
  }
}

// VM-hook starvation watchdog entry point, called from
// MICROPY_VM_HOOK_POLL. See native/watchdog.h for the safety argument.
// No-ops before configure() has run (g_watchdog is null).
extern "C" void moddiffdrive_vm_hook(void) {
  if (g_watchdog != nullptr) {
    g_watchdog->poll();
  }
}

// diffdrive.configure(left_port, right_port, fwd_sign_left=1,
//                      fwd_sign_right=1, max_duty=0.0,
//                      full_duty_velocity=0.0, cycle_period_ms=24)
//
// Every default is fail-closed (max_duty=0.0, full_duty_velocity=0.0),
// matching DiffDrive::Config's own contract. Write-shaping fields (slew
// rate, reversal dwell, output deadband) take this codebase's bench
// defaults until a future ticket wires the full per-robot JSON.
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
    // Velocity-PID + wheel-control fields (DiffDrive::Config). Defaults
    // 0 = kernel defaults; omitting them reproduces pre-PID behavior.
    kArgVMin,
    kArgBiasMax,
    kArgTauAdapt,
    kArgASteady,
    kArgDeficitThreshold,
    kArgDeficitWindow,
    kArgPidKp,
    kArgPidKi,
    kArgPidIMax,
    kArgPidKaff,
    kArgPidMax,
    kArgPosErrMax,
    kArgStallSpeed,
    kArgStallDemand,
    kArgStallWindow,
    // Per-wheel feedforward correction (Config.wheelGain/wheelIntercept,
    // applied to both accel/decel slots). Defaults 1/0 = neutral.
    kArgWheelGainLeft,
    kArgWheelGainRight,
    kArgWheelInterceptLeft,
    kArgWheelInterceptRight,
  };
  static const mp_arg_t allowed[] = {
      {MP_QSTR_left_port, MP_ARG_INT | MP_ARG_REQUIRED, {.u_int = 0}},
      {MP_QSTR_right_port, MP_ARG_INT | MP_ARG_REQUIRED, {.u_int = 0}},
      {MP_QSTR_fwd_sign_left, MP_ARG_INT, {.u_int = 1}},
      {MP_QSTR_fwd_sign_right, MP_ARG_INT, {.u_int = 1}},
      {MP_QSTR_max_duty, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_full_duty_velocity, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_cycle_period_ms, MP_ARG_INT, {.u_int = 24}},
      {MP_QSTR_v_min, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_bias_max, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_tau_adapt, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_a_steady, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_deficit_threshold, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_deficit_window, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_pid_kp, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_pid_ki, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_pid_i_max, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_pid_kaff, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_pid_max, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_pos_err_max, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_stall_speed, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_stall_demand, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_stall_window, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_wheel_gain_left, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(1)}},
      {MP_QSTR_wheel_gain_right, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(1)}},
      {MP_QSTR_wheel_intercept_left, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
      {MP_QSTR_wheel_intercept_right, MP_ARG_OBJ, {.u_obj = MP_OBJ_NEW_SMALL_INT(0)}},
  };
  mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
  mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);

  Hal::MotorConfig leftConfig;
  leftConfig.port = static_cast<uint32_t>(args[kArgLeftPort].u_int);
  leftConfig.fwdSign = args[kArgFwdSignLeft].u_int;
  leftConfig.slewRate = 0.0f;          // <= 0 -> NezhaMotor's own default
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
  cfg.vMin = mp_obj_get_float(args[kArgVMin].u_obj);
  cfg.biasMax = mp_obj_get_float(args[kArgBiasMax].u_obj);
  cfg.tauAdapt = mp_obj_get_float(args[kArgTauAdapt].u_obj);
  cfg.aSteady = mp_obj_get_float(args[kArgASteady].u_obj);
  cfg.deficitThreshold = mp_obj_get_float(args[kArgDeficitThreshold].u_obj);
  cfg.deficitWindow = mp_obj_get_float(args[kArgDeficitWindow].u_obj);
  cfg.kp = mp_obj_get_float(args[kArgPidKp].u_obj);
  cfg.ki = mp_obj_get_float(args[kArgPidKi].u_obj);
  cfg.iMax = mp_obj_get_float(args[kArgPidIMax].u_obj);
  cfg.kaff = mp_obj_get_float(args[kArgPidKaff].u_obj);
  cfg.pidMax = mp_obj_get_float(args[kArgPidMax].u_obj);
  cfg.posErrMax = mp_obj_get_float(args[kArgPosErrMax].u_obj);
  cfg.stallSpeed = mp_obj_get_float(args[kArgStallSpeed].u_obj);
  cfg.stallDemand = mp_obj_get_float(args[kArgStallDemand].u_obj);
  cfg.stallWindow = mp_obj_get_float(args[kArgStallWindow].u_obj);
  const float wheelGainLeft = mp_obj_get_float(args[kArgWheelGainLeft].u_obj);
  const float wheelGainRight = mp_obj_get_float(args[kArgWheelGainRight].u_obj);
  const float wheelInterceptLeft = mp_obj_get_float(args[kArgWheelInterceptLeft].u_obj);
  const float wheelInterceptRight = mp_obj_get_float(args[kArgWheelInterceptRight].u_obj);
  cfg.wheelGain[0][0] = wheelGainLeft;
  cfg.wheelGain[0][1] = wheelGainLeft;
  cfg.wheelGain[1][0] = wheelGainRight;
  cfg.wheelGain[1][1] = wheelGainRight;
  cfg.wheelIntercept[0][0] = wheelInterceptLeft;
  cfg.wheelIntercept[0][1] = wheelInterceptLeft;
  cfg.wheelIntercept[1][0] = wheelInterceptRight;
  cfg.wheelIntercept[1][1] = wheelInterceptRight;
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
  if (g_mode == Mode::kStep) {
    mp_raise_msg(&mp_type_RuntimeError,
                 MP_ERROR_TEXT("start() refused: step() already latched step mode this boot"));
  }
  if (g_mode == Mode::kUnlatched) {
    g_mode = Mode::kFiber;
    g_sleeper.setStepMode(false);
  }
  return statusObj(g_kernel->start());
}

// diffdrive.step() -- one full kernel cycle inline in the caller's
// context (vendor/differential_drive.h:344-351); no fiber, no fiber
// switch. Latches step mode on first call (see Mode above). Blocks
// ~9-10 ms per call (two 4 ms encoder settles via the mode-aware
// Sleeper) -- accepted cost for a cooperative teaching mode, paced by
// the caller against cyclePeriod().
extern "C" mp_obj_t diffdrive_step_fn(void) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  if (g_mode == Mode::kFiber) {
    mp_raise_msg(&mp_type_RuntimeError,
                 MP_ERROR_TEXT("step() refused: start() already latched fiber mode this boot"));
  }
  if (g_stepInFlight) {
    mp_raise_msg(&mp_type_RuntimeError,
                 MP_ERROR_TEXT("step() re-entered while a step is already in flight"));
  }
  if (g_mode == Mode::kUnlatched) {
    g_mode = Mode::kStep;
    g_sleeper.setStepMode(true);
  }
  g_stepInFlight = true;
  g_kernel->step();
  g_stepInFlight = false;
  return mp_const_none;
}

extern "C" mp_obj_t diffdrive_drive_fn(mp_obj_t velocityObj, mp_obj_t twistObj,
                                        mp_obj_t leaseObj) {
  if (g_kernel == nullptr) {
    return statusObj(DiffDrive::DifferentialDrive::Status::kRefusedUnconfigured);
  }
  const mp_int_t leaseMs = mp_obj_get_int(leaseObj);
  if (leaseMs < 0 || static_cast<uint32_t>(leaseMs) > kBindingLeaseMaxMs) {
    // Reject, never clamp -- see kBindingLeaseMaxMs's own comment.
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

  // Watchdog state -- not part of vendor/'s Output struct.
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

// Redundant with output()'s cycleOverrunCount field -- a direct,
// single-value call so a bench script needn't parse a dict for one
// counter.
extern "C" mp_obj_t diffdrive_cycleOverrunCount_fn(void) {
  if (g_kernel == nullptr) {
    return mp_obj_new_int_from_uint(0);
  }
  return mp_obj_new_int_from_uint(g_kernel->output().cycleOverrunCount);
}

// Read-only: the kernel's actual configured cycle period [ms], frozen at
// begin() (vendor/differential_drive.cpp:331-336, setConfig()'s
// post-begin re-clamp at :294-298). Lets a step-mode caller pace against
// the real value instead of a duplicated constant.
extern "C" mp_obj_t diffdrive_cyclePeriod_fn(void) {
  if (g_kernel == nullptr) {
    return mp_obj_new_int_from_uint(0);
  }
  return mp_obj_new_int_from_uint(g_kernel->config().cyclePeriod);
}

// robotio.i2c_xfer(address, write_data=b'', read_len=0, repeated=False,
//                   pre_clear=0, post_clear=0)
// -> int status when read_len == 0; (int status, bytes data) otherwise,
// both through the same I2cBroker instance the kernel leaves use.
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

  // Bounded: a sensor bus, not bulk transfer -- protects this stack
  // frame's headroom.
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
