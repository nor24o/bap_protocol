# VW Passat B6 (2010) White MFA+ ESP32 BAP Display Controller

This firmware runs on a standalone **ESP32 Dev Module** paired with an **MCP2515 CAN controller** (SPI) to hijack the white instrument cluster display (MFA+ / FIS) on a 2010 Volkswagen Passat B6 (PQ46 platform).

---

## 1. Physical Wiring

### ESP32 to MCP2515 SPI Connection
| ESP32 Pin | MCP2515 Pin | Description |
| :--- | :--- | :--- |
| **GPIO 5** | `CS` | SPI Chip Select |
| **GPIO 4** | `INT` | CAN Receive Interrupt |
| **GPIO 18** | `SCK` | SPI Clock |
| **GPIO 19** | `SO` (MISO) | Master In, Slave Out |
| **GPIO 23** | `SI` (MOSI) | Master Out, Slave In |
| **GND** | `GND` | Ground reference |
| **5V** or **3.3V** | `VCC` | Module Power (Most MCP2515 boards with TJA1050 require 5V VCC) |

### MCP2515 to Passat B6 Quadlock Connector
Located behind the OEM radio / Android Head Unit:

| MCP2515 Pin | Vehicle Wire Color | Vehicle Signal |
| :--- | :--- | :--- |
| `CANH` (Terminal) | **Orange / Violet** | Infotainment CAN-High |
| `CANL` (Terminal) | **Orange / Brown** | Infotainment CAN-Low |
| `GND` | **Brown** | Vehicle Chassis Ground |

> **CRITICAL TERMINATION NOTICE:**
> The VW Passat B6 Infotainment CAN bus is already terminated with $60\,\Omega$ to $120\,\Omega$ equivalent resistance inside the vehicle gateways.
> **You MUST remove or cut the $120\,\Omega$ onboard termination jumper (`J1` / `R120`) on the MCP2515 board**, otherwise it will drag down the vehicle bus and trigger CAN communication faults on the dashboard.

---

## 2. Crystal Oscillator Configuration

MCP2515 breakout boards come with either an **8 MHz** or **16 MHz** crystal (look at the silver oval component on the board):
* If marked **`8.000`**: Keep `-D CAN_OSC_MHZ=MCP_8MHZ` in [platformio.ini](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/esp32_firmware/platformio.ini).
* If marked **`16.000`**: Change to `-D CAN_OSC_MHZ=MCP_16MHZ` in [platformio.ini](file:///c:/Users/Altiv9/Desktop/DEV/VW_SCREEN/esp32_firmware/platformio.ini).

---

## 3. Building and Flashing

### Using PlatformIO Core CLI:
```bash
cd esp32_firmware
pio run --target upload
pio device monitor -b 115200
```

### Using PlatformIO in VS Code:
1. Open the `esp32_firmware` folder.
2. Click the **Build** (checkmark) or **Upload** (arrow) button on the status bar.
3. Open the Serial Monitor at **115200 baud** to view real-time diagnostics and button codes.

---

## 4. Operation Overview

1. The firmware initializes the MCP2515 at **100 kbps** (`CAN_100KBPS`).
2. Every **150 ms**, it constructs a segmented BAP long frame (`CAN ID 0x6C6`, `LSG 0x31 Audio`, `FCT 0x17 Station Name`) containing the custom text and transmits it onto the bus with a 4 ms inter-frame pacing delay.
3. This 150 ms repetition rate continuously overrides the Android CAN decoder box, keeping your custom telemetry alive on the white instrument cluster.
4. When you press steering wheel buttons, incoming frames on `0x5C1` are logged to the Serial Monitor.
