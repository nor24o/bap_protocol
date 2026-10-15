# VW Passat B6 MFA+ BAP Reverse-Engineering & Custom Screen Blueprint

**Date:** 2026-10-15  
**Platform:** Volkswagen Passat B6 (2010, PQ46)  
**Cluster:** White Dot-Matrix MFA+ / FIS  
**Bus:** Infotainment CAN (Strictly 100 kbps)  
**Hardware:** PEAK-System PCAN-USB (`PCAN_USBBUS1`) & ESP32 + MCP2515  

---

## 1. Executive Summary & Breakthroughs

1. **Hardware Verification (ACTIVE Mode):**
   * PEAK PCAN-USB adapter (`PCAN_USBBUS1`) successfully connected in **ACTIVE** mode at 100,000 bps.
   * Transmitted live frames onto the physical bus with 100% bus health (ACKed by car ECUs, 0 error frames, 0 bus-off).
2. **OpCode Bug Identification & Fix:**
   * In earlier attempts, packets were sent with `OpCode = 0x04`. In the official Volkswagen BAP specification, `0x04` is the **ERROR** opcode! The cluster was receiving error frames.
   * Updated protocol engine to use **`0x03` (`Changed`)** and **`0x02` (`Status`)**, producing exact OEM header bytes (`3C 57`, `3C 58`).
3. **Gateway 19 Activation:**
   * Gateway installation list updated: **Navigation (37)** and **Telephone (77)** enabled alongside Radio (56).
   * Opens competition-free BAP display channels without interference from aftermarket radio CAN boxes.
4. **VW BAP Architecture Mapping (Reverse-Engineered & Cross-Referenced with `tmbinc/kisim`):**
   * **BAP Audio (`LSG 0x31`):** `0x66C` (FSG $\rightarrow$ ASG)
   * **BAP Navigation (`LSG 0x32`):** `0x67D` (FSG $\rightarrow$ ASG)
   * **BAP Telephone (`LSG 0x28`):** `0x66F` (FSG $\rightarrow$ ASG)
   * **BAP Display / ScreenData (`LSG 0x2B / 43`):** `0x67C` (ASG $\rightarrow$ FSG response)

---

## 2. Complete Live Vehicle CAN Bus Findings

From the differential sniffer run recorded in `bus_map.json` and `baseline_analysis.json`:

### A. Bus Health & Parameters
* **Bitrate:** 100,000 bps (100 kbps) confirmed.
* **Active CAN IDs (39 total):**
  `0x151`, `0x2C1`, `0x2C3`, `0x351`, `0x359`, `0x35B`, `0x3C3`, `0x3E1`, `0x3E3`, `0x42B`, `0x433`, `0x439`, `0x470`, `0x497`, `0x523`, `0x527`, `0x531`, `0x54B`, `0x555`, `0x557`, `0x56F`, `0x571`, `0x575`, `0x5B5`, `0x5E1`, `0x60E`, `0x621`, `0x62F`, `0x635`, `0x651`, `0x653`, `0x655`, `0x658`, `0x65D`, `0x65F`, `0x661`, `0x66C`, `0x6DA`, `0x6DB`.

### B. Identified Physical Events
1. **Driver Door Open/Close:**
   * Direct delta activity on `0x3C3`, `0x527`, and `0x531`.
2. **Steering Wheel Buttons:**
   * Rapid frame deltas captured on `0x35B` (Multi-function steering wheel / gateway data stream).
3. **Radio & BAP Traffic:**
   * Live traffic captured on **`0x66C`** and **`0x6DB`**.
   * Exact frame captured during radio activity:
     ```
     CAN ID: 0x66C | Length: 8
     Start Frame: 80 08 3C 43 38 03 FF FC
     Cont Frame:  C0 00 00 00 00
     Decoded: OpCode=0x3 (Changed), LSG=0x31 (Audio), FCT=0x03 (Function-List)
     ```
   * Recurring baseline queries on `0x66C`:
     `3C 51 00`, `3C 52 00 00`, `3C 53 00`, `3C 54 00`, `3C 58 00`, `3C 59 00 00 00 00 00`, `3C 5A 00 00`.

---

## 3. Protocol Implementation Details

### A. 16-Bit BAP Header (Big-Endian)
* Bit 15: Frame Type (0 = Short Frame)
* Bits 14..12: OpCode (`0x0` Set, `0x1` Get, `0x2` Status, `0x3` Changed, `0x4` Error)
* Bits 11..6: LSG-ID (6 bits)
* Bits 5..0: FCT-ID (6 bits)

### B. Long Frame Segmentation
* **Start Frame (`0x80`):**
  * Byte 0: `0x80 | ((total_payload_len >> 8) & 0x0F)`
  * Byte 1: `total_payload_len & 0xFF`
  * Byte 2..3: 16-bit BAP Header (`0x3C 0x57` for Audio Station Name, `0x3C 0x58` for Track Name)
  * Byte 4: String length byte
  * Byte 5..7: Initial ASCII characters
* **Continuation Frames (`0xC0`):**
  * Byte 0: `0xC0 | (seq_index & 0x0F)`
  * Byte 1..7: Next 7 ASCII characters

### C. Handshake Sequence
Before accepting screen text, the cluster expects:
1. `FCT 0x02` (BAP-Config): `3C 42 03 00 31 00 03 01`
2. `FCT 0x03` (Function-List): `80 08 3C 43 38 03 FF FC` + `C0 00 00 00 00`
3. `FCT 0x0F` (FSG-OperationState): `3C 4F 00` (Normal Operation)

---

## 4. Codebase Assets & Tooling

All files located in `c:\Users\Altiv9\Desktop\DEV\VW_SCREEN\`:

* **`bap_protocol.py`**: Validated BAP codec with standard VW OpCodes and multi-frame reassembler.
* **`inject_screen.py`**: Active multi-target BAP injector with automated initialization handshakes.
* **`sniff_mapper.py`**: Interactive differential sniffer with live PCAN & mock simulation support.
* **`deep_baseline_analyzer.py`**: High-resolution cycle time and timing jitter analyzer.
* **`capture_action.py`**: Designated single-action differential recorder.
* **`vw_can_sim.py`**: Offline desk simulation engine.
* **`test_bap.py`**: Unit test suite verifying BAP header packing and reassembly.
* **`bus_map.json` & `baseline_analysis.json`**: Complete physical vehicle captures.
* **`esp32_firmware/`**: PlatformIO firmware for standalone ESP32 + MCP2515 hardware.
