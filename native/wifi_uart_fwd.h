// wifi_uart_fwd.h -- forward declarations for the WiFi UARTE1 byte-pipe
// shim + stdio TCP-REPL mirror hook, without pulling in any CODAL type
// (native/*.cpp builds under codal_port's plain Makefile, which lacks
// CODAL's includes -- see native/codal_fwd.h). Real implementations
// live in native/codal_app/wifi_uart_pipe.cpp + wifi_stdio_hook.cpp,
// copied into codal_app/ by build.sh's --with-wifi step.
//
// Byte pipe + mirror ring only -- AT dialogue is Python (src/wifi_at.py).
#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// -- Raw UARTE1 byte pipe (wifi_uart_pipe.cpp) -- TX=P8, RX=P1.
// Non-blocking; main context only, never a VM/GC hook.

// Idempotent.
void wifiUartInit(uint32_t baudRateHz);

// Returns bytes accepted; caller retries any remainder next pump tick.
size_t wifiUartWrite(const uint8_t* data, size_t len);

// Bytes available to wifiUartRead().
size_t wifiUartAny(void);

// Returns bytes read (0 if none). Never blocks.
size_t wifiUartRead(uint8_t* out, size_t cap);

// -- stdio TCP-REPL mirror hook (wifi_stdio_hook.cpp) -- bridges
// MicroPython's stdin/stdout and wifi_at.py's demuxed TCP REPL bytes.

// wifi_at.py sets this on TCP-REPL CONNECT; clears on CLOSED/restart.
void wifiStdioSetActive(int active);
int wifiStdioActive(void);

// Accepted bytes; drained by the patched mp_hal_stdin_rx_chr().
size_t wifiStdioStdinPush(const uint8_t* data, size_t len);

// Drained once per pump tick, then framed+coalesced+CIPSENT as one send.
size_t wifiStdioStdoutPull(uint8_t* out, size_t cap);

// -- called from patched mphalport.cpp only ----------------------------
int wifiStdioStdinReadable(void);
int wifiStdioStdinReadChr(void);  // -1 if empty
void wifiStdioCaptureStdout(const char* str, size_t len);  // no-op unless active()

#ifdef __cplusplus
}
#endif
