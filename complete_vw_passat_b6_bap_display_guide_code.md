# VW Passat B6 (2010) White MFA+ BAP Custom Screen: Complete Blueprint

This document contains the complete technical reference, wiring specifications, PCAN Python scripts, and standalone ESP32 C++ firmware for sniffing, hijacking, and sending custom screens to the white dot-matrix instrument cluster (MFA+ / FIS) on a 2010 Volkswagen Passat B6 (PQ46 platform).

---

## Table of Contents
1. [Physical Bus & Hardware Configuration](#1-physical-bus--hardware-configuration)
2. [VW BAP Protocol Architecture](#2-vw-bap-protocol-architecture)
3. [Phase 1: Interactive Differential Sniffer (`sniff_mapper.py`)](#3-phase-1-interactive-differential-sniffer-sniff_mapperpy)
4. [Phase 2: PCAN Custom Screen Injector (`inject_screen.py`)](#4-phase-2-pcan-custom-screen-injector-inject_screenpy)
5. [Phase 3: Standalone ESP32 + MCP2515 Firmware](#5-phase-3-standalone-esp32--mcp2515-firmware)
   - [PlatformIO Configuration (`platformio.ini`)](#platformio-configuration-platformioini)
   - [Complete ESP32 C++ Source (`src/main.cpp`)](#complete-esp32-c-source-srcmaincpp)
6. [Antigravity Direct Prompt Reference](#6-antigravity-direct-prompt-reference)

---

## 1. Physical Bus & Hardware Configuration

### Bus Specifications
* **Bus Name:** VW PQ46 Infotainment CAN (Comfort/Infotainment)
* **Baud Rate:** Strictly **$100\text{ kbps}$** ($100{,}000\text{ bps}$). Do not use $500\text{ kbps}$.
* **Location:** Quadlock wiring harness directly behind the radio / Android head unit.

### Pinout & Wire Colors
| Signal | Car Wire Color | PeakCAN DB9 Pin | MCP2515 Board Pin |
| :--- | :--- | :--- | :--- |
| **CAN-High** | Orange / Violet | Pin 7 | `CANH` screw terminal |
| **CAN-Low** | Orange / Brown | Pin 2 | `CANL` screw terminal |
| **GND** | Brown (or Chassis) | Pin 3 | `GND` |

> **Termination Note:** The vehicle bus is already terminated with $60\,\Omega$ to $120\,\Omega$ equivalent resistance. Ensure any onboard $120\,\Omega$ termination jumper on the MCP2515 or PeakCAN adapter is **disabled** to avoid loading down the vehicle bus.

---

## 2. VW BAP Protocol Architecture

On the 2010 white instrument cluster, the display is the **ASG** (*Anzeigesteuergerät*) and audio/navigation sources are **FSGs** (*Funktionssteuergerät*). Raw pixel drawing is not supported; communication is done via structured BAP packets.

### Logical Device IDs (`LSG-ID`)
* `0x31`: Audio / Radio (Currently used by your Android CAN decoder box)
* `0x32`: Navigation
* `0x28`: Telephone

### 16-Bit BAP Header Structure (Big-Endian)
Every BAP message payload starts with (or encodes) a 2-byte header:
* **Bit 15:** Frame type flag ($0 = \text{Short Frame}$, $1 = \text{Long Frame}$)
* **Bits 14..12:** `OpCode`
  * `0x0`: `Get`
  * `0x1`: `SetGet`
  * `0x2`: `HeartbeatStatus`
  * `0x3`: `StatusAck`
  * `0x4`: `Status`
  * `0x7`: `Error`
* **Bits 11..6:** `LSG-ID` (6 bits)
* **Bits 5..0:** `FCT-ID` (6 bits, Function ID)

### Frame Formatting
1. **Short Frame ($\le 6$ payload bytes):**
   * Byte 0: `(OpCode << 4) | (LSG_ID >> 2)`
   * Byte 1: `((LSG_ID & 0x03) << 6) | (FCT_ID & 0x3F)`
   * Bytes 2..7: Payload data.

2. **Long Frame (Segmented string transmission for screen text):**
   * **Start Frame:**
     * Byte 0: `0x80 | (group_id << 4) | ((total_payload_len >> 8) & 0x0F)`
     * Byte 1: `total_payload_len & 0xFF`
     * Byte 2: `(OpCode << 4) | (LSG_ID >> 2)`
     * Byte 3: `((LSG_ID & 0x03) << 6) | (FCT_ID & 0x3F)`
     * Bytes 4..7: First 4 bytes of data (Byte 4 is string length byte, Bytes 5..7 are initial ASCII characters).
   * **Continuation Frames:**
     * Byte 0: `0xC0 | (group_id << 4) | (sequence_index & 0x0F)`
     * Bytes 1..7: Next 7 ASCII characters.

---

## 3. Phase 1: Interactive Differential Sniffer (`sniff_mapper.py`)

Run this Python script on your laptop with the PeakCAN adapter attached. It will record a quiet background baseline, guide you through pressing buttons and opening doors, and automatically isolate the Android radio's BAP frames.

```python
#!/usr/bin/env python3
"""
Interactive Differential CAN Mapper & BAP Decoder for VW PQ46 (Passat B6).
Interface: PeakCAN-USB clone on PCAN_USBBUS1 at 100 kbps (listen-only).
"""

import time
import json
import sys

try:
    import can
    from can.bus import BusState
except ImportError:
    print("[!] python-can is not installed. Run: pip install python-can")
    sys.exit(1)

CHANNEL = 'PCAN_USBBUS1'
BITRATE = 100000  # VW Infotainment CAN is strictly 100,000 bps

def decode_bap_header(b0, b1):
    op_code = (b0 >> 4) & 0x07
    lsg_id = ((b0 & 0x0F) << 2) | ((b1 >> 6) & 0x03)
    fct_id = b1 & 0x3F
    return op_code, lsg_id, fct_id

def capture_window(bus, duration_sec):
    seen_payloads = {}
    bap_assembly = {}
    decoded_strings = []
    end_time = time.time() + duration_sec

    while time.time() < end_time:
        msg = bus.recv(timeout=0.1)
        if not msg:
            continue

        cid = msg.arbitration_id
        hex_data = msg.data.hex()

        if cid not in seen_payloads:
            seen_payloads[cid] = set()
        seen_payloads[cid].add(hex_data)

        # Check for BAP range (0x600 - 0x6FF)
        if 0x600 <= cid <= 0x6FF and len(msg.data) >= 2:
            b0 = msg.data[0]
            # Long frame start
            if (b0 & 0xC0) == 0x80 and len(msg.data) >= 4:
                grp = (b0 >> 4) & 0x03
                total_len = ((b0 & 0x0F) << 8) | msg.data[1]
                op, lsg, fct = decode_bap_header(msg.data[2], msg.data[3])
                bap_assembly[(cid, grp)] = {
                    'op': op, 'lsg': lsg, 'fct': fct, 'total_len': total_len,
                    'buffer': bytearray(msg.data[4:]), 'frames': [hex_data]
                }
            # Long frame continuation
            elif (b0 & 0xC0) == 0xC0:
                grp = (b0 >> 4) & 0x03
                key = (cid, grp)
                if key in bap_assembly:
                    entry = bap_assembly[key]
                    entry['buffer'].extend(msg.data[1:])
                    entry['frames'].append(hex_data)
                    if len(entry['buffer']) >= entry['total_len']:
                        raw_payload = bytes(entry['buffer'][:entry['total_len']])
                        # First byte is string length, subsequent bytes are text
                        text = raw_payload[1:].decode('utf-8', errors='replace')
                        decoded_strings.append({
                            'can_id': hex(cid),
                            'lsg_id': hex(entry['lsg']),
                            'fct_id': hex(entry['fct']),
                            'op_code': entry['op'],
                            'text': text,
                            'raw_frames': entry['frames']
                        })
                        del bap_assembly[key]

    return seen_payloads, decoded_strings

def main():
    print(f"[*] Initializing {CHANNEL} at {BITRATE} bps in PASSIVE mode...")
    try:
        bus = can.interface.Bus(interface='pcan', channel=CHANNEL, bitrate=BITRATE, state=BusState.PASSIVE)
    except Exception as e:
        print(f"[ERROR] Failed to open PCAN: {e}")
        return

    print("\n" + "="*60)
    print("STEP 1: QUIET BASELINE")
    print("Sit still, keep all doors closed, and do not touch any buttons.")
    input("Press ENTER to record 6-second quiet baseline...")
    print("[*] Recording baseline...")
    baseline_payloads, _ = capture_window(bus, 6.0)
    print(f"[+] Baseline recorded: {len(baseline_payloads)} active CAN IDs found:")
    for cid in sorted(baseline_payloads.keys()):
        print(f"    - ID: {hex(cid)} ({len(baseline_payloads[cid])} distinct payloads)")

    actions = [
        ("driver_door", "Open and close the DRIVER DOOR continuously for 5 seconds", 5.0),
        ("steering_buttons", "Press and release STEERING WHEEL buttons (Volume / Up / Down) for 5 seconds", 5.0),
        ("android_radio_bap", "Turn Android radio volume knob and switch stations continuously for 8 seconds", 8.0)
    ]

    results = {
        "baseline_ids": [hex(k) for k in sorted(baseline_payloads.keys())],
        "events": {}
    }

    for name, instruction, duration in actions:
        print("\n" + "="*60)
        print(f"STEP: {name.upper()}")
        print(f"Instruction: {instruction}")
        input("Press ENTER, then immediately perform the action...")
        print(f"[*] Capturing for {duration} seconds...")
        active_payloads, bap_texts = capture_window(bus, duration)

        delta = {}
        for cid, payloads in active_payloads.items():
            diff = payloads - baseline_payloads.get(cid, set())
            if diff:
                delta[hex(cid)] = list(diff)

        print(f"[+] Delta detected on IDs: {list(delta.keys())}")
        if bap_texts:
            print("[+] Captured BAP Strings:")
            for item in bap_texts:
                print(f"    - CAN ID: {item['can_id']} | LSG: {item['lsg_id']} | FCT: {item['fct_id']} | Text: '{item['text']}'")

        results["events"][name] = {
            "delta_frames": delta,
            "bap_strings": bap_texts
        }

    bus.shutdown()
    with open("bus_map.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n[SUCCESS] Capture complete. Results saved to 'bus_map.json'.")

if __name__ == "__main__":
    main()
```

---

## 4. Phase 2: PCAN Custom Screen Injector (`inject_screen.py`)

Once you know the exact CAN ID and `FCT-ID` from `bus_map.json` (commonly `CAN ID 0x6C6`, `LSG-ID 0x31`, `FCT-ID 0x17` or `0x18`), use this script to test overwriting the display with custom text.

```python
#!/usr/bin/env python3
"""
Custom BAP Text Injector for VW MFA+ Cluster via PeakCAN-USB.
Sends multi-frame BAP packets in ACTIVE mode at 100 kbps.
"""

import time
import sys

try:
    import can
    from can.bus import BusState
except ImportError:
    print("[!] python-can is not installed. Run: pip install python-can")
    sys.exit(1)

CHANNEL = 'PCAN_USBBUS1'
BITRATE = 100000

# Verified defaults for Audio (LSG 0x31) screen text
DEFAULT_CAN_ID = 0x6C6
DEFAULT_LSG_ID = 0x31
DEFAULT_FCT_ID = 0x17  # Station / Track text function

def build_bap_long_frames(can_id, op_code, lsg_id, fct_id, text_string, group_id=0):
    text_bytes = text_string.encode('ascii', errors='replace')
    payload = bytes([len(text_bytes)]) + text_bytes
    total_len = len(payload)

    # 16-bit BAP Header
    hdr0 = ((op_code & 0x07) << 4) | ((lsg_id >> 2) & 0x0F)
    hdr1 = ((lsg_id & 0x03) << 6) | (fct_id & 0x3F)

    frames = []

    # Start Frame (0x80)
    b0 = 0x80 | ((group_id & 0x03) << 4) | ((total_len >> 8) & 0x0F)
    b1 = total_len & 0xFF
    first_chunk = payload[:4]
    frame0_data = bytes([b0, b1, hdr0, hdr1]) + first_chunk
    frames.append(can.Message(arbitration_id=can_id, data=frame0_data, is_extended_id=False))

    # Continuation Frames (0xC0, 0xC1...)
    offset = 4
    seq = 0
    while offset < len(payload):
        cb0 = 0xC0 | ((group_id & 0x03) << 4) | (seq & 0x0F)
        chunk = payload[offset:offset + 7]
        frame_data = bytes([cb0]) + chunk
        frames.append(can.Message(arbitration_id=can_id, data=frame_data, is_extended_id=False))
        offset += 7
        seq += 1

    return frames

def main():
    custom_text = sys.argv[1] if len(sys.argv) > 1 else "CUSTOM SCREEN"
    print(f"[*] Opening {CHANNEL} in ACTIVE mode at {BITRATE} bps...")
    bus = can.interface.Bus(interface='pcan', channel=CHANNEL, bitrate=BITRATE, state=BusState.ACTIVE)

    frames = build_bap_long_frames(
        can_id=DEFAULT_CAN_ID,
        op_code=0x04,          # Status
        lsg_id=DEFAULT_LSG_ID,  # Audio
        fct_id=DEFAULT_FCT_ID,  # Screen string function
        text_string=custom_text
    )

    print(f"[*] Injecting text: '{custom_text}' (bursting for 8 seconds)...")
    end_time = time.time() + 8.0
    while time.time() < end_time:
        for f in frames:
            bus.send(f)
            time.sleep(0.004)  # 4ms inter-frame gap for cluster reassembly
        time.sleep(0.120)      # Repeat every 120ms to overwrite Android box

    bus.shutdown()
    print("[+] Test completed. Verify cluster display.")

if __name__ == "__main__":
    main()
```

---

## 5. Phase 3: Standalone ESP32 + MCP2515 Firmware

After confirming that the cluster accepts frames on the PCAN adapter, build and flash this standalone PlatformIO project.

### PlatformIO Configuration (`platformio.ini`)

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
lib_deps =
    coryjfowler/mcp_can @ ^1.5.0
build_flags =
    -D CAN_CS_PIN=5
    -D CAN_INT_PIN=4
    ; Set to 8MHz or 16MHz depending on the crystal on your MCP2515 module
    -D CAN_OSC_MHZ=MCP_8MHZ
```

### Complete ESP32 C++ Source (`src/main.cpp`)

```cpp
#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>

// Pin definitions
#ifndef CAN_CS_PIN
#define CAN_CS_PIN 5
#endif

#ifndef CAN_INT_PIN
#define CAN_INT_PIN 4
#endif

#ifndef CAN_OSC_MHZ
#define CAN_OSC_MHZ MCP_8MHZ // Common breakout boards use 8MHz; verify your crystal
#endif

MCP_CAN CAN0(CAN_CS_PIN);

// Target BAP IDs
const uint16_t BAP_CAN_ID = 0x6C6;
const uint8_t  BAP_LSG_AUDIO = 0x31;
const uint8_t  BAP_FCT_TEXT  = 0x17;
const uint8_t  BAP_OP_STATUS = 0x04;

void sendBapLongString(uint16_t canId, uint8_t opCode, uint8_t lsgId, uint8_t fctId, const char* text, uint8_t groupId = 0) {
    size_t textLen = strlen(text);
    if (textLen > 60) textLen = 60; // Cluster line buffer limit

    // Payload starts with 1-byte string length followed by ASCII characters
    uint8_t payload[64];
    payload[0] = (uint8_t)textLen;
    memcpy(&payload[1], text, textLen);
    uint16_t totalPayloadLen = textLen + 1;

    // Build 2-byte BAP Header
    uint8_t hdr0 = ((opCode & 0x07) << 4) | ((lsgId >> 2) & 0x0F);
    uint8_t hdr1 = ((lsgId & 0x03) << 6) | (fctId & 0x3F);

    // Frame 0: Start Frame (0x80)
    uint8_t f0[8];
    f0[0] = 0x80 | ((groupId & 0x03) << 4) | ((totalPayloadLen >> 8) & 0x0F);
    f0[1] = totalPayloadLen & 0xFF;
    f0[2] = hdr0;
    f0[3] = hdr1;

    size_t initialBytes = (totalPayloadLen > 4) ? 4 : totalPayloadLen;
    for (size_t i = 0; i < initialBytes; i++) {
        f0[4 + i] = payload[i];
    }
    for (size_t i = 4 + initialBytes; i < 8; i++) {
        f0[i] = 0x00;
    }

    CAN0.sendMsgBuf(canId, 0, 8, f0);
    delay(4); // 4ms inter-frame pacing

    // Continuation Frames (0xC0, 0xC1...)
    size_t offset = 4;
    uint8_t seq = 0;

    while (offset < totalPayloadLen) {
        uint8_t fn[8];
        memset(fn, 0, 8);
        fn[0] = 0xC0 | ((groupId & 0x03) << 4) | (seq & 0x0F);

        size_t chunk = totalPayloadLen - offset;
        if (chunk > 7) chunk = 7;

        for (size_t i = 0; i < chunk; i++) {
            fn[1 + i] = payload[offset + i];
        }

        CAN0.sendMsgBuf(canId, 0, 1 + chunk, fn);
        offset += chunk;
        seq++;
        delay(4);
    }
}

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 2000);

    Serial.println("\n[ESP32] VW BAP MFA+ Controller Initializing...");

    // Initialize MCP2515 at 100 kbps
    if (CAN0.begin(MCP_ANY, CAN_100KBPS, CAN_OSC_MHZ) == CAN_OK) {
        Serial.println("[ESP32] MCP2515 Initialized Successfully at 100 kbps!");
    } else {
        Serial.println("[ESP32] Error Initializing MCP2515. Check wiring and crystal frequency!");
        while (1) { delay(1000); }
    }

    CAN0.setMode(MCP_NORMAL);
    pinMode(CAN_INT_PIN, INPUT);
}

unsigned long lastSendTime = 0;
uint32_t counter = 0;

void loop() {
    // Transmit custom telemetry every 150ms
    if (millis() - lastSendTime >= 150) {
        lastSendTime = millis();

        char displayBuffer[32];
        snprintf(displayBuffer, sizeof(displayBuffer), "ESP32 TEST #%u", counter++);

        sendBapLongString(BAP_CAN_ID, BAP_OP_STATUS, BAP_LSG_AUDIO, BAP_FCT_TEXT, displayBuffer);
    }

    // Optional: Read incoming CAN frames from the bus
    if (!digitalRead(CAN_INT_PIN)) {
        long unsigned int rxId;
        unsigned char len = 0;
        unsigned char rxBuf[8];
        CAN0.readMsgBuf(&rxId, &len, rxBuf);

        // Filter steering wheel button events (0x5C1)
        if (rxId == 0x5C1 && len > 0) {
            uint8_t btn = rxBuf[0];
            if (btn != 0x00) {
                Serial.print("[BTN] Pressed code: 0x");
                Serial.println(btn, HEX);
            }
        }
    }
}
```

---

## 6. Antigravity Direct Prompt Reference

To have Google Antigravity autonomously execute this plan without manual intervention, paste the following instruction block directly into the Antigravity prompt interface:

```text
You have full local terminal and hardware execution access in this workspace.

Target setup:
- Vehicle: 2010 VW Passat B6 (Infotainment CAN, strictly 100,000 bps / 100 kbps).
- Interface: PeakCAN-USB clone on channel 'PCAN_USBBUS1'.
- Mode: Strictly passive listen-only (BusState.PASSIVE). Do not transmit frames yet. Do not generate ESP32 C++ code yet.

Your task:
1. Verify python-can is installed in the local Python environment. Install it if missing.
2. Create and run a passive sniffer script on PCAN_USBBUS1 at 100000 bps.
3. Record a 6-second quiet baseline while I touch nothing. Identify all periodic background CAN IDs, cycle times, and rolling counters.
4. Once the baseline is complete, pause and prompt me in chat to perform actions one by one:
   - Ask me to open/close the driver door, then record a 5s capture and compute the diff.
   - Ask me to press steering wheel / MFA stalk buttons, then record a 5s capture and compute the diff.
   - Ask me to turn the Android radio volume and change stations, then capture the BAP frames (0x600-0x6FF).
5. Reassemble the BAP long frames (0x80 start + 0xC0 sequence), decode the 2-byte BAP header, and extract the ASCII text currently sent to the cluster.
6. Save all decoded events, bitmasks, and BAP frame structures to bus_map.json.
```