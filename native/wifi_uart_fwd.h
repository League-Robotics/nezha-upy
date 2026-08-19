// wifi_uart_fwd.h -- forward declarations for the WiFi UARTE1 byte-pipe
// shim + stdio TCP-REPL mirror hook (ticket 006, M4), WITHOUT pulling in
// any CODAL type.
//
// Mirrors native/codal_fwd.h's own established pattern and its own
// documented reason: native/*.cpp compiles under codal_port's plain
// Makefile (MicroPython's own build), which does NOT carry CODAL's
// library include directories -- those exist only on the separate
// CMake-driven build that compiles codal_app/*.cpp. The REAL
// implementation of every function declared here lives in
// native/codal_app/wifi_uart_pipe.cpp + wifi_stdio_hook.cpp, copied by
// build.sh's --with-wifi step into
// micropython-microbit-v2/src/codal_app/ (see that step's own comment)
// -- resolved at LINK time, same as codal_fwd.h's fiber-scheduler
// declarations.
//
// This header is included from BOTH sides of that link-time boundary:
// native/modwifiuart.cpp (the MicroPython glue, codal_port build) calls
// these; native/codal_app/wifi_uart_pipe.cpp and wifi_stdio_hook.cpp
// (copied into codal_app/, the CODAL build) DEFINE them -- one file is
// the single source of truth for the signatures on both sides of the
// link.
//
// Split of responsibility (spec Sec 3/5/8; this ticket's own module
// docstring in src/wifi_at.py has the full rationale): this shim is a
// byte pipe plus a tiny stdin/stdout mirror ring, nothing more. ALL AT
// dialogue (join, CIPMUX, CIPSERVER, CIPSTART, +IPD framing, datagram
// coalescing, the >=50ms TLM throttle, READY-on-new-peer) is Python
// (src/wifi_at.py), driven from the scheduled pump -- single-context
// module access, per spec Sec 8.
#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// -- Raw UARTE1 byte pipe (native/codal_app/wifi_uart_pipe.cpp) --------
//
// The stock micropython-microbit-v2 port never exposes the second
// UARTE, and microbit.uart.init(tx,rx) retargets the ONE stdio UART --
// so the WiFi module's UART needs this distinct shim. Fixed to the
// bench's WiFi jack (TX=P8, RX=P1, matching
// reference/modrobot/wifi_stdio.cpp's own default jack) -- see
// wifi_uart_pipe.cpp's own header for why a runtime-selectable jack is
// out of scope here. Every call is non-blocking: this is a byte pipe,
// not an AT-aware sender -- no busy-wait, no schedule() anywhere in
// this file's call graph, safe to call only from main context (the
// scheduled pump), never from a VM/GC hook.

// Idempotent: a second call after the first is a no-op.
void wifiUartInit(uint32_t baudRateHz);

// Queues up to `len` bytes for transmission; returns the number
// actually accepted (may be less than `len` if the UARTE's own TX
// buffer is momentarily full -- the caller, wifi_at.py's AT dialogue,
// retries the remainder on its next pump tick).
size_t wifiUartWrite(const uint8_t* data, size_t len);

// Bytes currently available to wifiUartRead().
size_t wifiUartAny(void);

// Reads up to `cap` bytes into `out`; returns the number actually read
// (0 if none available). Never blocks.
size_t wifiUartRead(uint8_t* out, size_t cap);

// -- stdio TCP-REPL mirror hook (native/codal_app/wifi_stdio_hook.cpp) -
//
// A tiny bridge between MicroPython's actual stdin/stdout (which only
// this port's C HAL functions -- mp_hal_stdin_rx_chr/
// mp_hal_stdout_tx_strn/mp_hal_stdio_poll, patched by build.sh's
// --with-wifi step -- can intercept) and wifi_at.py's own byte demuxing
// of the AT link's +IPD-framed TCP REPL client data. wifi_at.py owns
// ALL AT/IPD parsing and pushes/pulls through this ring-buffer surface
// once per pump tick; this file never parses AT replies or IPD frames
// itself. Reuses reference/modrobot/wifi_stdio.cpp's own coalescing-
// ring pattern (drop-oldest on overflow) for both directions.

// Enable/disable the mirror -- wifi_at.py sets this once its AT state
// machine has parsed a "<link>,CONNECT" status line for the TCP REPL
// link (and clears it on CLOSED/restart).
void wifiStdioSetActive(int active);
int wifiStdioActive(void);

// wifi_at.py pushes REPL-bound bytes (demuxed from the TCP REPL link's
// +IPD payload) here; returns the number actually accepted (the ring
// may be momentarily full). Drained by the patched
// mp_hal_stdin_rx_chr().
size_t wifiStdioStdinPush(const uint8_t* data, size_t len);

// wifi_at.py drains MicroPython's captured stdout bytes here once per
// pump tick, then frames+coalesces+CIPSENDs them as ONE send (spec Sec
// 3/8: never per-character). Returns the number actually read.
size_t wifiStdioStdoutPull(uint8_t* out, size_t cap);

// -- called from patched mphalport.cpp only ----------------------------
int wifiStdioStdinReadable(void);
int wifiStdioStdinReadChr(void);  // -1 if empty
void wifiStdioCaptureStdout(const char* str, size_t len);  // no-op unless active()

#ifdef __cplusplus
}
#endif
