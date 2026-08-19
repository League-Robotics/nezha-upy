#pragma once

#include <cstddef>
#include <cstdint>

namespace RobotWifi {

void service();

// Flush coalesced outbound bytes. MAIN CONTEXT ONLY (blocks, may
// schedule()): stdin wait loop, v5 loop, stdio poll -- never the GC hook
// or background processing.
void flushOutput();

bool connected();
bool readable();
size_t read(uint8_t* out, size_t cap);

bool writeToSocket(const uint8_t* data, size_t len);
void debugStatus(char* out, size_t cap);

// -- v5 UDP plane -------------------------------------------------------
//
// A SECOND, independent socket (ESP-AT link 4) carrying the real
// protocol-v5 wire that rogo/the host tools speak, running simultaneously
// with the TCP REPL above. Bring-up is automatic, folded into service()'s
// existing state machine (opened right after the TCP CIPSERVER step
// succeeds) -- nothing here starts it and there is no separate enable call.

// Drain bytes received on the v5 UDP link into `out`. MAIN CONTEXT ONLY,
// same contract as flushOutput(): called from robot_v5_service()
// (modrobot.cpp), which itself only runs from main-context call sites
// (mphalport.cpp's stdin wait loop and mp_hal_stdio_poll, and
// microbit_hal_background_processing() -- safe there only because
// robot_v5_service() carries its own reentrancy guard).
size_t readV5(uint8_t* out, size_t cap);

// True once a datagram has been heard from a v5 peer within the last 60s
// (kPeerSilenceMs, mirrors Hardware::WifiLink::kPeerSilence -- see
// src/firm/hardware/planetx/wifi_link.h). Lazily forgets a peer that has
// gone quiet the moment it is asked, so a caller that polls this before
// every TLM push naturally stops streaming to a peer that vanished.
bool v5PeerKnown();

// Sends ONE UDP datagram to the current v5 peer
// (AT+CIPSEND=4,<len>,"<ip>",<port>). MAIN CONTEXT ONLY (blocks on the
// module, busy-polls, never schedule()s -- same contract as
// writeToSocket()/flushOutput()). Returns false with no peer known or on
// any module failure; the caller drops the reply rather than retrying,
// the same policy writeToSocket() already applies to the TCP path.
bool sendV5Datagram(const uint8_t* data, size_t len);

}  // namespace RobotWifi
