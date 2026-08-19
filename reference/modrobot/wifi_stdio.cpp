#include "wifi_stdio.h"

#include <cstdio>
#include <cstring>

#include "main.h"
#include "wifi_stdio_config.h"

namespace RobotWifi {
namespace {

constexpr uint32_t kGuardTimeMs = 1100;
// The module answers AT late (>250ms) when it is busy auto-rejoining its
// saved AP at boot; a tight window misclassifies a live module as absent
// and loops probe->backoff for minutes (observed on gopiv 2026-08-14).
constexpr uint32_t kProbeWindowMs = 1000;
constexpr uint8_t kProbeAttempts = 3;
constexpr uint8_t kJoinQueryAttempts = 6;  // ~9s of AT+CWJAP? polling
constexpr size_t kTxBuffer = 512;
constexpr uint32_t kCommandTimeoutMs = 4000;
constexpr uint32_t kJoinTimeoutMs = 15000;
constexpr uint32_t kBackoffDelayMs = 5000;
constexpr size_t kStageBuffer = 128;
constexpr size_t kRxBuffer = 512;
constexpr size_t kLineBuffer = 96;
constexpr size_t kCommandBuffer = 160;
constexpr size_t kMaxChunk = 128;
constexpr size_t kTraceCommand = 48;
constexpr size_t kTraceReply = 72;

// -- v5 UDP plane ------------------------------------------------------
constexpr int kV5Link = 4;                    // ESP-AT link id, fixed
constexpr size_t kV5RxBuffer = 512;
// The host's fixed local port (robot_radio.io.udp_link.DEFAULT_LOCAL_PORT)
// -- the address the robot's UDP socket broadcasts to until a real peer
// answers. See serviceServer()'s AT+CIPSTART=4 step.
constexpr uint16_t kV5DiscoveryPort = 7655;
// Mirrors Hardware::WifiLink::kPeerSilence (src/firm/hardware/planetx/
// wifi_link.h): a host that only WATCHES telemetry sends nothing itself,
// but robot_radio.io.udp_link.UdpLink keepalives well inside this window
// (every 15s), so only a peer that is genuinely gone trips it.
constexpr uint32_t kPeerSilenceMs = 60000;


struct JackPins {
  uint8_t txPin;
  uint8_t rxPin;
};

constexpr JackPins kJacks[] = {
    {8, 1},
    {12, 2},
    {14, 13},
    {16, 15},
};

struct WifiConfig {
  char ssid[33] = {};
  char password[64] = {};
  char ip[16] = {};
  char gateway[16] = {};
  char netmask[16] = {};
  uint16_t port = 0;
  uint8_t channel = 0;
  uint32_t baud = 115200;
};

NRF52Pin* pinFor(uint8_t pinNumber) {
  switch (pinNumber) {
    case 1: return &uBit.io.P1;
    case 2: return &uBit.io.P2;
    case 8: return &uBit.io.P8;
    case 12: return &uBit.io.P12;
    case 13: return &uBit.io.P13;
    case 14: return &uBit.io.P14;
    case 15: return &uBit.io.P15;
    case 16: return &uBit.io.P16;
    default: return nullptr;
  }
}

class Matcher {
 public:
  void reset(const char* token) {
    token_ = token;
    matched_ = 0;
  }

  bool feed(char c) {
    if (token_ == nullptr || token_[0] == '\0') return false;
    if (c == token_[matched_]) {
      ++matched_;
      if (token_[matched_] == '\0') {
        matched_ = 0;
        return true;
      }
      return false;
    }
    matched_ = (c == token_[0]) ? 1 : 0;
    return false;
  }

 private:
  const char* token_ = nullptr;
  uint8_t matched_ = 0;
};

// Parses `+IPD,<link>,<len>:` (CIPDINFO=0) AND `+IPD,<link>,<len>,"<ip>",
// <port>:` (CIPDINFO=1 -- required for the v5 UDP plane to learn its peer;
// see the AT+CIPDINFO=1 step in serviceConfigure()). Both forms must parse:
// TCP client links never needed the sender address and CIPDINFO used to be
// off for them, so the parser has to keep accepting the bare form too.
class IpdParser {
 public:
  void reset() {
    stage_ = Stage::kTag;
    tag_.reset("+IPD,");
    link_ = -1;
    len_ = 0;
    sawDigit_ = false;
    ip_[0] = '\0';
    ipLen_ = 0;
    port_ = 0;
    portSeenDigit_ = false;
  }

  bool feed(char c) {
    switch (stage_) {
      case Stage::kTag:
        if (tag_.feed(c)) {
          stage_ = Stage::kLink;
          link_ = 0;
          sawDigit_ = false;
        }
        return false;
      case Stage::kLink:
        if (c >= '0' && c <= '9') {
          link_ = link_ * 10 + (c - '0');
          sawDigit_ = true;
          return false;
        }
        if (c == ',' && sawDigit_) {
          stage_ = Stage::kLen;
          len_ = 0;
          sawDigit_ = false;
          return false;
        }
        reset();
        return false;
      case Stage::kLen:
        if (c >= '0' && c <= '9') {
          len_ = len_ * 10u + static_cast<size_t>(c - '0');
          sawDigit_ = true;
          return false;
        }
        if (c == ':' && sawDigit_) {
          stage_ = Stage::kDone;
          return true;
        }
        if (c == ',' && sawDigit_) {
          // Extended (CIPDINFO=1) form: <len> is followed by "<ip>",<port>
          // instead of terminating on ':' directly.
          stage_ = Stage::kToQuote;
          return false;
        }
        reset();
        return false;
      case Stage::kToQuote:
        if (c == '"') {
          stage_ = Stage::kIp;
          ipLen_ = 0;
          return false;
        }
        reset();
        return false;
      case Stage::kIp:
        if (c == '"') {
          ip_[ipLen_] = '\0';
          stage_ = Stage::kToPort;
          return false;
        }
        if (ipLen_ + 1 < sizeof(ip_)) {
          ip_[ipLen_++] = c;
          return false;
        }
        reset();  // address too long -- resynchronize
        return false;
      case Stage::kToPort:
        if (c == ',') {
          stage_ = Stage::kPort;
          port_ = 0;
          portSeenDigit_ = false;
          return false;
        }
        reset();
        return false;
      case Stage::kPort:
        if (c >= '0' && c <= '9') {
          port_ = static_cast<uint16_t>(port_ * 10 + (c - '0'));
          portSeenDigit_ = true;
          return false;
        }
        if (c == ':' && portSeenDigit_) {
          stage_ = Stage::kDone;
          return true;
        }
        reset();
        return false;
      case Stage::kDone:
        return false;
    }
    return false;
  }

  int link() const { return link_; }
  size_t len() const { return len_; }
  const char* ip() const { return ip_; }
  uint16_t port() const { return port_; }

 private:
  enum class Stage : uint8_t {
    kTag, kLink, kLen, kToQuote, kIp, kToPort, kPort, kDone
  };

  Stage stage_ = Stage::kTag;
  Matcher tag_;
  int link_ = -1;
  size_t len_ = 0;
  bool sawDigit_ = false;
  char ip_[16] = {};
  uint8_t ipLen_ = 0;
  uint16_t port_ = 0;
  bool portSeenDigit_ = false;
};

class WifiTcpStdio {
 public:
  void service() {
    ensureStarted();
    switch (state_) {
      case State::kDisabled:
        return;
      case State::kExitPassthrough:
        serviceExitPassthrough();
        return;
      case State::kProbe:
        serviceProbe();
        return;
      case State::kConfigure:
        serviceConfigure();
        return;
      case State::kJoin:
        serviceJoin();
        return;
      case State::kAddress:
        serviceAddress();
        return;
      case State::kQueryIp:
        serviceQueryIp();
        return;
      case State::kServer:
        serviceServer();
        return;
      case State::kReady:
        // NO flushing here: service() also runs from the GC hook and idle
        // paths, and flushTx() -> writeChunk() blocks and calls schedule()
        // -- a fiber switch from inside GC bricks the VM. Flushing happens
        // only from main-context call sites via flushPending().
        pumpIncoming();
        return;
      case State::kBackoff:
        serviceBackoff();
        return;
    }
  }

  bool connected() const {
    return state_ == State::kReady && clientLink_ >= 0;
  }

  bool readable() {
    pumpIncoming();
    return rxCount_ != 0;
  }

  size_t read(uint8_t* out, size_t cap) {
    if (cap == 0) return 0;
    pumpIncoming();
    size_t n = 0;
    while (n < cap && rxCount_ > 0) {
      out[n++] = rx_[rxTail_];
      rxTail_ = (rxTail_ + 1) % kRxBuffer;
      --rxCount_;
    }
    return n;
  }

  // -- v5 UDP plane --------------------------------------------------

  size_t readV5(uint8_t* out, size_t cap) {
    if (cap == 0) return 0;
    pumpIncoming();
    size_t n = 0;
    while (n < cap && v5RxCount_ > 0) {
      out[n++] = v5Rx_[v5RxTail_];
      v5RxTail_ = (v5RxTail_ + 1) % kV5RxBuffer;
      --v5RxCount_;
    }
    return n;
  }

  // Lazily forgets a peer that has gone silent for kPeerSilenceMs -- checked
  // here rather than on a timer so a caller that never asks pays nothing,
  // and a caller that asks every tick (robot_v5_service) gets it forgotten
  // the moment silence crosses the budget.
  bool v5PeerKnown() {
    if (!v5PeerKnown_) return false;
    if (static_cast<int32_t>(nowMillis() - (lastV5Heard_ + kPeerSilenceMs)) >= 0) {
      v5PeerKnown_ = false;
      v5PeerIp_[0] = '\0';
      v5PeerPort_ = 0;
    }
    return v5PeerKnown_;
  }

  // One UDP datagram, explicitly addressed (AT+CIPSEND=<link>,<len>,"<ip>",
  // <port>) rather than routed through the fixed-peer TCP tx_ coalescer --
  // a v5 reply is exactly one datagram, sent now, never batched.
  bool sendV5Datagram(const uint8_t* data, size_t len) {
    if (state_ != State::kReady) return false;
    if (!v5PeerKnown()) return false;
    char command[kCommandBuffer];
    const int n = std::snprintf(command, sizeof(command),
                                "AT+CIPSEND=%d,%u,\"%s\",%u\r\n", kV5Link,
                                static_cast<unsigned>(len), v5PeerIp_,
                                static_cast<unsigned>(v5PeerPort_));
    if (n <= 0 || static_cast<size_t>(n) >= sizeof(command)) return false;
    if (!sendRaw(reinterpret_cast<const uint8_t*>(command),
                 static_cast<size_t>(n), kCommandTimeoutMs)) {
      return false;
    }
    if (!waitFor(">", kCommandTimeoutMs)) return false;
    if (!sendRaw(data, len, kCommandTimeoutMs)) return false;
    return waitFor("SEND OK", kCommandTimeoutMs);
  }

  // Outbound bytes are COALESCED, not sent per call. MicroPython emits
  // stdout in many tiny pieces (per echoed keystroke; a traceback is 10+
  // writes back-to-back), and one AT+CIPSEND handshake per piece both
  // floods the module into "busy p..." rejections and costs ~30ms each.
  // Appends flush when the buffer is full or ~20ms after the last append
  // (from service(), which every stdio path already pumps).
  bool writeToSocket(const uint8_t* data, size_t len) {
    ensureStarted();
    if (!connected()) return false;
    size_t pos = 0;
    while (pos < len) {
      if (txLen_ >= sizeof(tx_)) {
        if (!flushTx()) return false;
      }
      const size_t space = sizeof(tx_) - txLen_;
      const size_t take = (len - pos > space) ? space : (len - pos);
      std::memcpy(tx_ + txLen_, data + pos, take);
      txLen_ += take;
      pos += take;
    }
    txLastAppend_ = nowMillis();
    return true;
  }

  // Main-context-only flush entry: called from the stdin wait loop (where
  // the REPL sits exactly when its output burst is complete, so echo +
  // result + prompt leave as ONE coalesced send), the v5 loop, and stdio
  // poll. Never from service().
  void flushPending() {
    if (state_ == State::kReady && txLen_ != 0) flushTx();
  }

  bool flushTx() {
    if (txLen_ == 0) return true;
    if (!connected()) {
      txLen_ = 0;
      return false;
    }
    size_t pos = 0;
    bool ok = true;
    while (pos < txLen_) {
      const size_t chunk =
          (txLen_ - pos > kMaxChunk) ? kMaxChunk : (txLen_ - pos);
      if (!writeChunk(tx_ + pos, chunk)) {
        ok = false;
        break;
      }
      pos += chunk;
    }
    txLen_ = 0;  // drop on failure: a REPL byte is not worth a wedge
    return ok;
  }


  void debugStatus(char* out, size_t cap) {
    ensureStarted();
    if (cap == 0) return;
    std::snprintf(out, cap,
                  "state=%s step=%u probe=%u awaiting=%d client=%d payload=%d rx=%u ip=%s cmd=%s reply=%s",
                  stateName(), static_cast<unsigned>(step_),
                  static_cast<unsigned>(probeChannel_), awaiting_ ? 1 : 0,
                  clientLink_, payloadLink_, static_cast<unsigned>(rxCount_),
                  currentIp_, lastCommand_, lastReply_);
  }

 private:
  const char* stateName() const {
    switch (state_) {
      case State::kDisabled:
        return "disabled";
      case State::kExitPassthrough:
        return "exit_passthrough";
      case State::kProbe:
        return "probe";
      case State::kConfigure:
        return "configure";
      case State::kJoin:
        return "join";
      case State::kAddress:
        return "address";
      case State::kQueryIp:
        return "query_ip";
      case State::kServer:
        return "server";
      case State::kReady:
        return "ready";
      case State::kBackoff:
        return "backoff";
    }
    return "unknown";
  }

 private:
  enum class State : uint8_t {
    kDisabled,
    kExitPassthrough,
    kProbe,
    kConfigure,
    kJoin,
    kAddress,
    kQueryIp,
    kServer,
    kReady,
    kBackoff,
  };

  enum class AwaitResult : uint8_t { kPending, kMatched, kRejected, kTimedOut };

  void ensureStarted() {
    if (started_) return;
    started_ = true;
    std::memcpy(config_.ssid, kWifiStdioSsid, sizeof(config_.ssid));
    std::memcpy(config_.password, kWifiStdioPassword, sizeof(config_.password));
    std::memcpy(config_.ip, kWifiStdioIp, sizeof(config_.ip));
    std::memcpy(config_.gateway, kWifiStdioGateway, sizeof(config_.gateway));
    std::memcpy(config_.netmask, kWifiStdioNetmask, sizeof(config_.netmask));
    config_.port = kWifiStdioPort;
    config_.channel = kWifiStdioChannel;
    config_.baud = kWifiStdioBaud;
    if (config_.ssid[0] == '\0') {
      state_ = State::kDisabled;
      return;
    }
    std::snprintf(expectJoined_, sizeof(expectJoined_), "+CWJAP:\"%s\"",
                  config_.ssid);
    uart_.setRxBufferSize(250);
    uart_.setTxBufferSize(250);
    uart_.setBaudrate(config_.baud);
    probeChannel_ = 1;
    enterState(State::kExitPassthrough);
  }

  uint32_t nowMillis() const { return system_timer_current_time(); }

  void traceReply(char c) {
    if (lastReplyLen_ + 1 >= kTraceReply) return;
    lastReply_[lastReplyLen_++] = (c >= 0x20 && c < 0x7F) ? c : '.';
    lastReply_[lastReplyLen_] = '\0';
  }

  void enterState(State next) {
    state_ = next;
    step_ = 0;
    awaiting_ = false;
    awaitMatched_ = false;
    awaitRejected_ = false;
    ipd_.reset();
    lineLen_ = 0;
    payloadRemaining_ = 0;
  }

  void restart() {
    clientLink_ = -1;
    // Flush any buffered client bytes: they belong to a session that did not
    // survive bring-up, and stale rx_ content wedges the stdin wait loop.
    rxHead_ = 0;
    rxTail_ = 0;
    rxCount_ = 0;
    payloadLink_ = -1;
    // Same policy for the v5 UDP plane: a restart tears the link 4 socket
    // down (the next bring-up reissues AT+RST, which wipes every ESP-AT
    // socket), so the peer relationship and any buffered v5 bytes are
    // equally stale.
    v5RxHead_ = 0;
    v5RxTail_ = 0;
    v5RxCount_ = 0;
    v5PeerKnown_ = false;
    v5PeerIp_[0] = '\0';
    v5PeerPort_ = 0;
    deadline_ = nowMillis() + kBackoffDelayMs;
    enterState(State::kBackoff);
  }

  int nextByte() {
    if (stagePos_ >= stageLen_) {
      const int n = uart_.read(stage_, static_cast<int>(kStageBuffer), ASYNC);
      stageLen_ = n > 0 ? static_cast<uint16_t>(n) : 0;
      stagePos_ = 0;
      if (stageLen_ == 0) return -1;
    }
    return static_cast<int>(stage_[stagePos_++]);
  }

  bool sendRaw(const uint8_t* data, size_t len, uint32_t timeoutMs) {
    const uint32_t until = nowMillis() + timeoutMs;
    while (static_cast<int32_t>(nowMillis() - until) < 0) {
      if (250 - uart_.txBufferedSize() >= static_cast<int>(len)) {
        uart_.send(const_cast<uint8_t*>(data), static_cast<int>(len), ASYNC);
        return true;
      }
      // Busy-poll, NEVER schedule(): a fiber switch from deep inside the
      // MicroPython VM's C stack corrupts the heap (caught on gopiv
      // 2026-08-14 as a HardFault inside mp_obj_exception_add_traceback
      // with 0x8a20xxxx garbage pointers -- and it is the likely mechanism
      // behind the vevov spike's documented exception-path wedges). UARTE
      // TX/RX are DMA+IRQ driven; they drain and fill without fibers.
      pumpIncoming();
    }
    return false;
  }

  bool sendCommand(const char* command, const char* expect, uint32_t timeoutMs) {
    char line[kCommandBuffer];
    const int n = std::snprintf(line, sizeof(line), "%s\r\n", command);
    if (n <= 0 || static_cast<size_t>(n) >= sizeof(line)) return false;
    // Drain pending UART bytes THROUGH the parser instead of discarding
    // them. clearRxBuffer() here destroyed live +IPD client data whenever a
    // command was sent in kReady -- and every echoed character sends an
    // AT+CIPSEND, so echoing char N of a pasted line nuked chars N+1..
    // still in the DMA ring (observed on gopiv 2026-08-14: "print" arrived
    // as "pint").
    pumpIncoming();
    if (!sendRaw(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n),
                 timeoutMs)) {
      return false;
    }
    size_t i = 0;
    for (; command[i] != '\0' && i + 1 < sizeof(lastCommand_); ++i) {
      lastCommand_[i] = command[i];
    }
    lastCommand_[i] = '\0';
    lastReply_[0] = '\0';
    lastReplyLen_ = 0;
    expect_.reset(expect);
    rejectError_.reset("ERROR");
    rejectFail_.reset("FAIL");
    rejectBusy_.reset("busy");
    deadline_ = nowMillis() + timeoutMs;
    awaiting_ = true;
    awaitMatched_ = false;
    awaitRejected_ = false;
    return true;
  }

  AwaitResult awaitReply() {
    // Nothing armed = terminal, NOT pending: writeChunk's while(true) loops
    // treat kPending as "keep waiting", so returning kPending with no await
    // armed spun those loops forever -- a hard REPL wedge that even Ctrl-C
    // cannot interrupt (the VM never returns to bytecode). Seen on gopiv
    // 2026-08-14 as mpremote "could not enter raw repl" with b''.
    if (!awaiting_) return AwaitResult::kTimedOut;
    // Check the flags BEFORE pulling new bytes: pumpIncoming() -- called at
    // high frequency from readable() while the REPL idles in its stdin wait
    // loop -- consumes reply bytes and sets awaitMatched_/awaitRejected_
    // itself. The old shape only looked at the flags after feeding a NEW
    // byte, so a reply the pump had already eaten was silently discarded and
    // the await timed out. Observed on gopiv 2026-08-14: the state machine
    // progressed only while Python code was executing (pump quiet) and
    // looped probe->backoff forever whenever the REPL sat at its prompt --
    // i.e. exactly when running headless.
    int c = 0;
    while (!awaitMatched_ && !awaitRejected_ && (c = nextByte()) >= 0) {
      feedIncoming(static_cast<char>(c));
    }
    if (awaitMatched_) {
      awaitMatched_ = false;
      awaiting_ = false;
      return AwaitResult::kMatched;
    }
    if (awaitRejected_) {
      awaitRejected_ = false;
      awaiting_ = false;
      return AwaitResult::kRejected;
    }
    if (static_cast<int32_t>(nowMillis() - deadline_) >= 0) {
      awaiting_ = false;
      return AwaitResult::kTimedOut;
    }
    return AwaitResult::kPending;
  }

  void feedIncoming(char ch) {
    if (payloadRemaining_ > 0) {
      pushRx(static_cast<uint8_t>(ch));
      --payloadRemaining_;
      return;
    }
    if (ipd_.feed(ch)) {
      payloadRemaining_ = ipd_.len();
      payloadLink_ = ipd_.link();
      if (payloadLink_ == kV5Link) {
        // The v5 peer is learned/refreshed off the HEADER alone, not the
        // payload -- so an empty datagram (a bare-newline keepalive is 1
        // byte, but this covers a genuinely empty one too) still counts as
        // being heard from, exactly like every other byte on this link.
        std::memcpy(v5PeerIp_, ipd_.ip(), sizeof(v5PeerIp_));
        v5PeerPort_ = ipd_.port();
        lastV5Heard_ = nowMillis();
        v5PeerKnown_ = true;
      }
      ipd_.reset();
      return;
    }
    feedStatusByte(ch);
    if (awaiting_) {
      traceReply(ch);
      if (expect_.feed(ch)) {
        awaitMatched_ = true;
      }
      if (rejectError_.feed(ch) || rejectFail_.feed(ch) ||
          rejectBusy_.feed(ch)) {
        awaitRejected_ = true;
      }
    }
  }

  void feedStatusByte(char ch) {
    if (ch == '\r') return;
    if (ch == '\n') {
      line_[lineLen_] = '\0';
      handleStatusLine(line_);
      lineLen_ = 0;
      return;
    }
    if (lineLen_ + 1 < sizeof(line_)) {
      line_[lineLen_++] = ch;
    } else {
      lineLen_ = 0;
    }
  }

  void handleStatusLine(const char* line) {
    int link = -1;
    char status[16] = {};
    if (std::sscanf(line, "%d,%15s", &link, status) == 2) {
      // The v5 UDP socket is not a TCP client. ESP-AT's mux-mode CIPSTART
      // reports a CONNECT/CLOSED lifecycle for a UDP link the same as a TCP
      // one; without this guard a "4,CONNECT" would set clientLink_ = 4 and
      // connected() would then start routing REPL output at the v5 socket
      // instead of a real client.
      if (link == kV5Link) return;
      if (std::strcmp(status, "CONNECT") == 0) {
        // Newest client wins. A stale abandoned session otherwise shadows
        // the fresh one: its link id stays active, and the new client's
        // +IPD payload is silently discarded by pushRx's link filter.
        if (clientLink_ != link) {
          rxHead_ = 0;
          rxTail_ = 0;
          rxCount_ = 0;
        }
        clientLink_ = link;
      } else if (std::strcmp(status, "CLOSED") == 0 && clientLink_ == link) {
        clientLink_ = -1;
      }
    }
  }

  void pushRx(uint8_t ch) {
    // link 4 is the v5 UDP plane, never the TCP REPL -- route it to its own
    // ring and skip every TCP-client concern below (clientLink_ matching,
    // the kReady gate, etc).
    if (payloadLink_ == kV5Link) {
      pushV5Rx(ch);
      return;
    }
    // Only buffer client payload once the bridge itself is ready. The module
    // accepts TCP clients on its own (its server persists across nRF resets),
    // and +IPD payload from those not-yet-real sessions otherwise lands in
    // rx_, making readable() true with no connected client -- which spins
    // the stdin wait loop and freezes the state machine mid-bring-up.
    if (state_ != State::kReady) return;
    if (payloadLink_ >= 0) {
      if (clientLink_ < 0) {
        clientLink_ = payloadLink_;
      } else if (clientLink_ != payloadLink_) {
        return;
      }
    }
    if (rxCount_ >= kRxBuffer) {
      rxTail_ = (rxTail_ + 1) % kRxBuffer;
      --rxCount_;
    }
    rx_[rxHead_] = ch;
    rxHead_ = (rxHead_ + 1) % kRxBuffer;
    ++rxCount_;
  }

  void pushV5Rx(uint8_t ch) {
    // Drop oldest on overflow -- same policy as pushRx()'s rx_ ring.
    if (v5RxCount_ >= kV5RxBuffer) {
      v5RxTail_ = (v5RxTail_ + 1) % kV5RxBuffer;
      --v5RxCount_;
    }
    v5Rx_[v5RxHead_] = ch;
    v5RxHead_ = (v5RxHead_ + 1) % kV5RxBuffer;
    ++v5RxCount_;
  }

  void pumpIncoming() {
    ensureStarted();
    if (state_ == State::kDisabled) return;
    int c = 0;
    while ((c = nextByte()) >= 0) {
      feedIncoming(static_cast<char>(c));
    }
  }

  // Self-contained wait: LOCAL matchers, LOCAL deadline. writeChunk used to
  // ride the shared expect_/awaiting_/deadline_ that the bring-up state
  // machine and every pump path also touch, and cross-context interleaving
  // corrupted the await (lost SEND OKs, storms of 4s timeouts, one hard
  // wedge). Bytes seen here still flow through feedIncoming(), which with
  // awaiting_ false routes +IPD payload and status lines and nothing else.
  bool waitFor(const char* token, uint32_t timeoutMs) {
    Matcher want;
    Matcher err;
    Matcher fail;
    Matcher busy;
    want.reset(token);
    err.reset("ERROR");
    fail.reset("FAIL");
    busy.reset("busy");
    const uint32_t until = nowMillis() + timeoutMs;
    while (static_cast<int32_t>(nowMillis() - until) < 0) {
      const int c = nextByte();
      if (c < 0) {
        continue;  // busy-poll; see sendRaw() for why schedule() is banned here
      }
      const char ch = static_cast<char>(c);
      feedIncoming(ch);
      if (want.feed(ch)) return true;
      if (err.feed(ch) || fail.feed(ch) || busy.feed(ch)) return false;
    }
    return false;
  }

  bool writeChunk(const uint8_t* data, size_t len) {
    if (!connected()) return false;
    char command[kCommandBuffer];
    const int n = std::snprintf(command, sizeof(command), "AT+CIPSEND=%d,%u\r\n",
                                clientLink_, static_cast<unsigned>(len));
    if (n <= 0 || static_cast<size_t>(n) >= sizeof(command)) return false;
    if (!sendRaw(reinterpret_cast<const uint8_t*>(command),
                 static_cast<size_t>(n), kCommandTimeoutMs)) {
      return false;
    }
    if (!waitFor(">", kCommandTimeoutMs)) return false;
    if (!sendRaw(data, len, kCommandTimeoutMs)) return false;
    return waitFor("SEND OK", kCommandTimeoutMs);
  }

  void serviceExitPassthrough() {
    switch (step_) {
      case 0:
        deadline_ = nowMillis() + kGuardTimeMs;
        step_ = 1;
        return;
      case 1:
        if (static_cast<int32_t>(nowMillis() - deadline_) < 0) return;
        if (!sendRaw(reinterpret_cast<const uint8_t*>("+++"), 3, kCommandTimeoutMs)) {
          restart();
          return;
        }
        deadline_ = nowMillis() + kGuardTimeMs;
        step_ = 2;
        return;
      case 2:
        if (static_cast<int32_t>(nowMillis() - deadline_) < 0) return;
        if (!awaiting_) {
          if (!sendCommand("AT+CIPCLOSE", "OK", kCommandTimeoutMs)) {
            restart();
          }
          return;
        }
        switch (awaitReply()) {
          case AwaitResult::kPending:
            return;
          default:
            clientLink_ = -1;
            enterState(State::kProbe);
            return;
        }
      default:
        enterState(State::kProbe);
        return;
    }
  }

  void serviceProbe() {
    if (!awaiting_) {
      const JackPins& jack = kJacks[probeChannel_ - 1];
      NRF52Pin* tx = pinFor(jack.txPin);
      NRF52Pin* rx = pinFor(jack.rxPin);
      if (tx == nullptr || rx == nullptr) {
        restart();
        return;
      }
      uart_.redirect(*tx, *rx);
      if (!sendCommand("AT", "OK", kProbeWindowMs)) restart();
      return;
    }
    switch (awaitReply()) {
      case AwaitResult::kMatched:
        probeAttempt_ = 0;
        enterState(State::kConfigure);
        return;
      case AwaitResult::kPending:
        return;
      default:
        // Retry the same jack a few times before giving up on it -- the
        // module answers late when busy auto-rejoining (same policy as
        // Hardware::WifiLink's kProbeAttempts).
        if (++probeAttempt_ < kProbeAttempts) {
          awaiting_ = false;
          return;
        }
        probeAttempt_ = 0;
        if (config_.channel != 0) {
          restart();
          return;
        }
        if (++probeChannel_ > 4) {
          probeChannel_ = 1;
          restart();
        } else {
          awaiting_ = false;
        }
        return;
    }
  }

  void serviceConfigure() {
    struct Step {
      const char* command;
      const char* expect;
      uint32_t timeoutMs;
      bool tolerant;
    };
    // The module is RJ11-powered: it keeps its server, client links, mux
    // mode, and lease across an nRF reset. Inheriting that state is how we
    // got a FALSE READY on gopiv 2026-08-14: a stale server kept accepting
    // TCP connections but never reported them to the nRF (no CONNECT, no
    // +IPD -- "connects but only echoes"), while our own CIPSERVER=1 said
    // ERROR and was tolerated. So: reboot the module first (AT+RST). That
    // makes every bring-up start from the module's clean boot state --
    // no zombie links, no stale server -- at the cost of a real (~2-8s)
    // AP rejoin, which kJoinTimeoutMs already covers.
    static const Step kSteps[] = {
        {"AT+RST", "ready", 6000, true},
        {"AT", "OK", 2000, true},  // absorb boot-banner stragglers
        {"ATE0", "OK", kCommandTimeoutMs, true},
        {"AT+CIPMODE=0", "OK", kCommandTimeoutMs, true},
        {"AT+CIPSERVER=0", "OK", kCommandTimeoutMs, true},
        {"AT+CIPCLOSE=5", "OK", kCommandTimeoutMs, true},
        {"AT+CIPCLOSE", "OK", kCommandTimeoutMs, true},
        {"AT+CWMODE=1", "OK", kCommandTimeoutMs, false},
        {"AT+CIPMUX=1", "OK", kCommandTimeoutMs, false},
        // =1: +IPD now carries the sender's ip/port inline -- required so
        // the v5 UDP socket (link kV5Link, opened in serviceServer()) can
        // learn its peer. TCP client +IPD headers grow the same optional
        // fields; IpdParser above accepts both forms.
        {"AT+CIPDINFO=1", "OK", kCommandTimeoutMs, true},
    };
    if (step_ >= sizeof(kSteps) / sizeof(kSteps[0])) {
      enterState(State::kJoin);
      return;
    }
    if (!awaiting_) {
      if (!sendCommand(kSteps[step_].command, kSteps[step_].expect,
                       kSteps[step_].timeoutMs)) {
        restart();
      }
      return;
    }
    const AwaitResult result = awaitReply();
    if (result == AwaitResult::kPending) return;
    if (result != AwaitResult::kMatched && !kSteps[step_].tolerant) {
      restart();
      return;
    }
    ++step_;
    awaiting_ = false;
  }

  void serviceJoin() {
    // After AT+RST the module auto-rejoins its saved AP by itself, and an
    // explicit CWJAP fired into that in-progress join answers busy/ERROR --
    // observed on gopiv 2026-08-14 as minutes of join->backoff->RST
    // near-livelock. So step 0 polls AT+CWJAP? for the auto-join to land
    // (matched = already on our SSID -> done); only if it never lands does
    // step 1 issue the explicit join.
    if (step_ == 0) {
      if (!awaiting_) {
        if (!sendCommand("AT+CWJAP?", expectJoined_, 1500)) restart();
        return;
      }
      switch (awaitReply()) {
        case AwaitResult::kMatched:
          joinQueryAttempt_ = 0;
          enterState(State::kAddress);
          return;
        case AwaitResult::kPending:
          return;
        default:
          if (++joinQueryAttempt_ < kJoinQueryAttempts) {
            awaiting_ = false;  // re-query; auto-join takes a few seconds
            return;
          }
          joinQueryAttempt_ = 0;
          step_ = 1;
          awaiting_ = false;
          return;
      }
    }
    if (!awaiting_) {
      char command[kCommandBuffer];
      std::snprintf(command, sizeof(command), "AT+CWJAP=\"%s\",\"%s\"",
                    config_.ssid, config_.password);
      if (!sendCommand(command, "OK", kJoinTimeoutMs)) restart();
      return;
    }
    switch (awaitReply()) {
      case AwaitResult::kMatched:
        enterState(State::kAddress);
        return;
      case AwaitResult::kPending:
        return;
      default:
        restart();
        return;
    }
  }

  void serviceAddress() {
    if (!awaiting_) {
      char command[kCommandBuffer];
      if (config_.ip[0] != '\0' && config_.gateway[0] != '\0' &&
          config_.netmask[0] != '\0') {
        // Explicit three-argument form. Bare AT+CIPSTA="<ip>" derives a
        // classful /24 netmask (and a phantom gateway) from the address
        // alone, which broke a static 192.168.4.x address on the flat
        // 192.168.0.0/21 bench LAN (2026-08-14). Mirrors
        // Hardware::WifiLink::serviceAddress (src/firm/hardware/planetx/
        // wifi_link.cpp).
        std::snprintf(command, sizeof(command), "AT+CIPSTA=\"%s\",\"%s\",\"%s\"",
                      config_.ip, config_.gateway, config_.netmask);
      } else if (config_.ip[0] != '\0') {
        std::snprintf(command, sizeof(command), "AT+CIPSTA=\"%s\"", config_.ip);
      } else {
        std::snprintf(command, sizeof(command), "AT+CWDHCP=1,1");
      }
      if (!sendCommand(command, "OK", kCommandTimeoutMs)) restart();
      return;
    }
    switch (awaitReply()) {
      case AwaitResult::kMatched:
      case AwaitResult::kRejected:
      case AwaitResult::kTimedOut:
        enterState(State::kQueryIp);
        return;
      case AwaitResult::kPending:
        return;
    }
  }

  void captureIpFromReply() {
    const char* p = lastReply_;
    while (*p != '\0') {
      if ((*p >= '0' && *p <= '9')) {
        char candidate[16] = {};
        size_t i = 0;
        int dots = 0;
        while (((*p >= '0' && *p <= '9') || *p == '.') && i + 1 < sizeof(candidate)) {
          if (*p == '.') ++dots;
          candidate[i++] = *p++;
        }
        candidate[i] = '\0';
        if (dots == 3) {
          std::memcpy(currentIp_, candidate, sizeof(currentIp_));
          return;
        }
        continue;
      }
      ++p;
    }
  }

  void serviceQueryIp() {
    if (!awaiting_) {
      if (!sendCommand("AT+CIPSTA?", "OK", kCommandTimeoutMs)) restart();
      return;
    }
    switch (awaitReply()) {
      case AwaitResult::kMatched:
        captureIpFromReply();
        enterState(State::kServer);
        return;
      case AwaitResult::kPending:
        return;
      default:
        enterState(State::kServer);
        return;
    }
  }

  void serviceServer() {
    if (step_ == 0) {
      if (!awaiting_) {
        char command[kCommandBuffer];
        std::snprintf(command, sizeof(command), "AT+CIPSERVER=1,%u",
                      static_cast<unsigned>(config_.port));
        if (!sendCommand(command, "OK", kCommandTimeoutMs)) restart();
        return;
      }
      const AwaitResult result = awaitReply();
      if (result == AwaitResult::kPending) return;
      if (result == AwaitResult::kMatched) {
        step_ = 1;
        awaiting_ = false;
        return;
      }
      // ERROR used to be tolerated as "already created" -- which produced a
      // ready state fronted by a stale server that accepted connections and
      // reported none of them. After the AT+RST in configure the create must
      // genuinely succeed; anything else is a failed bring-up.
      restart();
      return;
    }
    if (step_ == 1) {
      // The v5 UDP plane: a SECOND, independent socket on link kV5Link,
      // brought up right after the TCP REPL server so both planes come
      // alive together (a caller checking connected()/ready needs both, not
      // one first). Remote "255.255.255.255",kV5DiscoveryPort with mode 2
      // ("remote resets to the last sender") means no peer needs to be
      // known yet -- exactly the broadcast-first discovery
      // robot_radio.io.udp_link.UdpLink does on the host side: it broadcasts
      // until this robot answers, and the FIRST datagram we hear teaches us
      // the real peer (captured in feedIncoming() above). Local port is
      // config_.port (7654), the module's own well-known listening port.
      // Treated as a failed bring-up on ERROR, same policy as CIPSERVER
      // just above: a module that will not open this socket is not a link
      // worth calling ready.
      if (!awaiting_) {
        char command[kCommandBuffer];
        std::snprintf(command, sizeof(command),
                      "AT+CIPSTART=%d,\"UDP\",\"255.255.255.255\",%u,%u,2",
                      kV5Link, static_cast<unsigned>(kV5DiscoveryPort),
                      static_cast<unsigned>(config_.port));
        if (!sendCommand(command, "OK", kCommandTimeoutMs)) restart();
        return;
      }
      const AwaitResult result = awaitReply();
      if (result == AwaitResult::kPending) return;
      if (result == AwaitResult::kMatched) {
        enterState(State::kReady);
        return;
      }
      restart();
      return;
    }
    enterState(State::kReady);
  }

  void serviceBackoff() {
    if (static_cast<int32_t>(nowMillis() - deadline_) < 0) return;
    probeChannel_ = 1;
    enterState(State::kExitPassthrough);
  }

  bool started_ = false;
  State state_ = State::kDisabled;
  WifiConfig config_{};
  NRF52Serial uart_{uBit.io.P8, uBit.io.P1, NRF_UARTE1};

  uint8_t stage_[kStageBuffer] = {};
  uint16_t stageLen_ = 0;
  uint16_t stagePos_ = 0;

  uint8_t rx_[kRxBuffer] = {};
  size_t rxHead_ = 0;
  size_t rxTail_ = 0;
  size_t rxCount_ = 0;

  // v5 UDP plane: its own ring (never shares rx_ with the TCP REPL) plus the
  // learned peer and when it was last heard from.
  uint8_t v5Rx_[kV5RxBuffer] = {};
  size_t v5RxHead_ = 0;
  size_t v5RxTail_ = 0;
  size_t v5RxCount_ = 0;
  char v5PeerIp_[16] = {};
  uint16_t v5PeerPort_ = 0;
  uint32_t lastV5Heard_ = 0;
  bool v5PeerKnown_ = false;

  uint8_t tx_[kTxBuffer] = {};
  size_t txLen_ = 0;
  uint32_t txLastAppend_ = 0;

  char line_[kLineBuffer] = {};
  size_t lineLen_ = 0;

  Matcher expect_;
  Matcher rejectError_;
  Matcher rejectFail_;
  Matcher rejectBusy_;  // ESP-AT "busy p..." when commands arrive too fast
  IpdParser ipd_;

  uint32_t deadline_ = 0;
  uint8_t probeChannel_ = 1;
  uint8_t probeAttempt_ = 0;
  uint8_t joinQueryAttempt_ = 0;
  char expectJoined_[48] = {};
  uint8_t step_ = 0;
  int clientLink_ = -1;
  int payloadLink_ = -1;
  size_t payloadRemaining_ = 0;
  bool awaiting_ = false;
  bool awaitMatched_ = false;
  bool awaitRejected_ = false;
  char lastCommand_[kTraceCommand] = {};
  char lastReply_[kTraceReply] = {};
  size_t lastReplyLen_ = 0;
  char currentIp_[16] = {};
};

WifiTcpStdio& wifi() {
  static WifiTcpStdio link;
  return link;
}

}  // namespace

void service() { wifi().service(); }

void flushOutput() { wifi().flushPending(); }

bool connected() { return wifi().connected(); }

bool readable() { return wifi().readable(); }

size_t read(uint8_t* out, size_t cap) { return wifi().read(out, cap); }

bool writeToSocket(const uint8_t* data, size_t len) {
  return wifi().writeToSocket(data, len);
}

void debugStatus(char* out, size_t cap) { wifi().debugStatus(out, cap); }

size_t readV5(uint8_t* out, size_t cap) { return wifi().readV5(out, cap); }

bool v5PeerKnown() { return wifi().v5PeerKnown(); }

bool sendV5Datagram(const uint8_t* data, size_t len) {
  return wifi().sendV5Datagram(data, len);
}

}  // namespace RobotWifi
