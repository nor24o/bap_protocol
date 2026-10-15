# VW Passat B6 (2010) White MFA+ BAP Controller & Sniffer Toolkit

This repository contains the complete implementation for sniffing, mapping, and injecting custom text onto the white dot-matrix instrument cluster (MFA+ / FIS) of a 2010 Volkswagen Passat B6 (PQ46 platform).

---

## 🛠️ System Overview

* **Target CAN Bus:** PQ46 Infotainment CAN (Comfort / Infotainment).
* **Bus Speed:** Strictly **100 kbps** ($100{,}000\text{ bps}$). Never use 500 kbps.
* **Display Architecture:** BAP (Bedien- und Anzeigeprotokoll). The instrument cluster is an **ASG** (*Display Controller*), and the radio / Android box is an **FSG** (*Function Controller*, LSG `0x31`, CAN ID `0x6C6`).
* **Hardware Interface:** PEAK-System PCAN-USB (channel `PCAN_USBBUS1`).
* **Standalone Firmware:** ESP32 + MCP2515 CAN controller via SPI.

---

## 📁 Repository Structure

| File / Folder | Purpose |
| :--- | :--- |
| [bap_protocol.py](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/bap_protocol.py) | Core BAP protocol engine: header encoding/decoding, multi-frame fragmentation, and stateful reassembler. |
| [sniff_mapper.py](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/sniff_mapper.py) | Interactive differential CAN sniffer. Records baseline and guides through door, steering button, and radio tests. Supports both physical PCAN and offline simulation. |
| [inject_screen.py](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/inject_screen.py) | Custom screen text injector. Sends segmented BAP long frames onto the vehicle bus or validates them in dry-run mode. |
| [vw_can_sim.py](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/vw_can_sim.py) | Realistic Passat B6 100 kbps CAN simulator for desk testing without vehicle connection. |
| [test_bap.py](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/test_bap.py) | Automated test suite validating packet assembly, limits, and header math. |
| [verify_pipeline.py](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/verify_pipeline.py) | One-click diagnostic pipeline verifying Python, drivers, hardware status, and tests. |
| [bus_map.json](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/bus_map.json) | Exported differential capture results (baseline IDs, delta frames, decoded BAP strings). |
| [esp32_firmware/](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/esp32_firmware/) | Complete PlatformIO project for flashing standalone ESP32 + MCP2515 hardware. |

---

## 🚀 Usage Guide

### 1. Desk Testing (Without Car Connected)

You can test the entire workflow right at your desk without being in the car:

#### A. Run the Verification Pipeline
```powershell
python verify_pipeline.py
```

#### B. Run the Differential Sniffer in Simulation Mode
```powershell
# Interactive mode (prompts for door, steering buttons, radio)
python sniff_mapper.py --mock

# Fully automated non-interactive run
python sniff_mapper.py --mock --auto
```

#### C. Inspect BAP Packet Structure (Dry-Run Injector)
```powershell
python inject_screen.py "MY PASSAT B6" --dry-run
```

---

### 2. Live Vehicle Testing (With PCAN Connected to Car)

#### Physical Wiring:
Connect your PCAN-USB DB9 connector directly to the Quadlock harness behind the radio:
* **CAN-High (Orange / Violet)** $\rightarrow$ **DB9 Pin 7**
* **CAN-Low (Orange / Brown)** $\rightarrow$ **DB9 Pin 2**
* **GND (Brown)** $\rightarrow$ **DB9 Pin 3**

> **Note:** Ensure any $120\,\Omega$ termination jumper on your adapter is **removed** (vehicle bus is already terminated).

#### Step 1: Run Differential Mapping
Turn ignition ON (engine can be OFF):
```powershell
python sniff_mapper.py
```
Follow the on-screen steps:
1. Sit still for 6 seconds (records quiet baseline).
2. Open and close the driver door for 5 seconds.
3. Press steering wheel buttons for 5 seconds.
4. Turn radio volume and switch stations for 8 seconds.

Results will automatically save to [bus_map.json](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/bus_map.json).

#### Step 2: Inject Custom Screen Text
Overwrite the instrument cluster display:
```powershell
python inject_screen.py "TURBO BOOST 1.4"
```

---

### 3. ESP32 Standalone Hardware

See [esp32_firmware/README.md](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/esp32_firmware/README.md) for complete circuit schematics, crystal frequency settings (8MHz vs 16MHz), and PlatformIO flashing instructions.
