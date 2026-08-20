// modwifiuart.cpp -- MicroPython C++ module: wifiuart.
//
// UARTE1 byte-pipe shim + stdio TCP-REPL mirror hook: the stock
// micropython-microbit-v2 port only exposes one UART (microbit.uart
// retargets it), so WiFi needs its own shim. This file is MicroPython
// glue only -- raw byte-pipe I/O and the mirror ring's push/pull
// surface. All AT-command logic lives in src/wifi_at.py.
//
// The actual UARTE1/NRF52Serial access lives in
// native/codal_app/wifi_uart_pipe.cpp + wifi_stdio_hook.cpp, copied by
// build.sh's --with-wifi step into the CODAL build; this file compiles
// under codal_port's plain Makefile (no CODAL headers -- see
// native/codal_fwd.h), so it only calls the extern "C" surface declared
// in wifi_uart_fwd.h, resolved at link time.
//
// Returns plain ints/bytes rather than raising on a short write/read --
// every call here is non-blocking by construction, so a short result is
// expected, not an error.

extern "C" {
#include "py/obj.h"
#include "py/runtime.h"
}

#include "wifi_uart_fwd.h"

namespace {
// Bounds a single read()/stdout_pull() call -- generous relative to
// both ring sizes and one v5/REPL datagram.
constexpr size_t kMaxChunk = 512;
}  // namespace

extern "C" mp_obj_t wifiuart_init_fn(size_t n_args, const mp_obj_t* pos_args,
                                      mp_map_t* kw_args) {
  enum { kArgBaudrate };
  static const mp_arg_t allowed[] = {
      {MP_QSTR_baudrate, MP_ARG_INT, {.u_int = 115200}},
  };
  mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
  mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);
  wifiUartInit(static_cast<uint32_t>(args[kArgBaudrate].u_int));
  return mp_const_none;
}

extern "C" mp_obj_t wifiuart_write_fn(mp_obj_t dataObj) {
  mp_buffer_info_t bufinfo;
  mp_get_buffer_raise(dataObj, &bufinfo, MP_BUFFER_READ);
  const size_t n =
      wifiUartWrite(static_cast<const uint8_t*>(bufinfo.buf), bufinfo.len);
  return mp_obj_new_int_from_uint(n);
}

extern "C" mp_obj_t wifiuart_any_fn(void) {
  return mp_obj_new_int_from_uint(wifiUartAny());
}

extern "C" mp_obj_t wifiuart_read_fn(mp_obj_t nObj) {
  mp_int_t n = mp_obj_get_int(nObj);
  if (n < 0) {
    n = 0;
  } else if (static_cast<size_t>(n) > kMaxChunk) {
    n = kMaxChunk;
  }
  uint8_t buf[kMaxChunk];
  const size_t got = wifiUartRead(buf, static_cast<size_t>(n));
  return mp_obj_new_bytes(buf, got);
}

extern "C" mp_obj_t wifiuart_repl_active_fn(mp_obj_t flagObj) {
  wifiStdioSetActive(mp_obj_is_true(flagObj) ? 1 : 0);
  return mp_const_none;
}

extern "C" mp_obj_t wifiuart_stdin_push_fn(mp_obj_t dataObj) {
  mp_buffer_info_t bufinfo;
  mp_get_buffer_raise(dataObj, &bufinfo, MP_BUFFER_READ);
  const size_t n =
      wifiStdioStdinPush(static_cast<const uint8_t*>(bufinfo.buf), bufinfo.len);
  return mp_obj_new_int_from_uint(n);
}

extern "C" mp_obj_t wifiuart_stdout_pull_fn(mp_obj_t nObj) {
  mp_int_t n = mp_obj_get_int(nObj);
  if (n < 0) {
    n = 0;
  } else if (static_cast<size_t>(n) > kMaxChunk) {
    n = kMaxChunk;
  }
  uint8_t buf[kMaxChunk];
  const size_t got = wifiStdioStdoutPull(buf, static_cast<size_t>(n));
  return mp_obj_new_bytes(buf, got);
}
