#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>

/**
 * VW Passat B6 (2010) White MFA+ BAP Custom Screen Controller
 * Platform: ESP32 + MCP2515 CAN Controller
 * Bus: VW PQ46 Infotainment CAN (Strictly 100 kbps)
 *
 * Hardware Wiring:
 *   ESP32 Pin 5   -> MCP2515 CS
 *   ESP32 Pin 4   -> MCP2515 INT
 *   ESP32 Pin 18  -> MCP2515 SCK
 *   ESP32 Pin 19  -> MCP2515 SO (MISO)
 *   ESP32 Pin 23  -> MCP2515 SI (MOSI)
 *   ESP32 5V/3.3V -> MCP2515 VCC (Check module regulator / transceiver requirement)
 *   ESP32 GND     -> MCP2515 GND
 *
 * Vehicle Connection:
 *   MCP2515 CANH  -> Quadlock Orange / Violet
 *   MCP2515 CANL  -> Quadlock Orange / Brown
 *   MCP2515 GND   -> Vehicle Ground
 *
 * NOTE: Ensure the onboard 120-ohm termination jumper on the MCP2515 is REMOVED.
 */

// Pin definitions
#ifndef CAN_CS_PIN
#define CAN_CS_PIN 5
#endif

#ifndef CAN_INT_PIN
#define CAN_INT_PIN 4
#endif

#ifndef CAN_OSC_MHZ
// Common blue/red MCP2515 breakout boards use 8MHz crystal (labeled 8.000).
// If your crystal is labeled 16.000, change this to MCP_16MHZ.
#define CAN_OSC_MHZ MCP_8MHZ
#endif

MCP_CAN CAN0(CAN_CS_PIN);

// Target BAP IDs for VW PQ46 Infotainment
// Note: 0x66C is the active Audio BAP CAN ID confirmed on this vehicle's bus (0x6C6 is alternate)
const uint16_t BAP_CAN_ID    = 0x66C;
const uint8_t  BAP_LSG_AUDIO = 0x31;  // Logical Device ID: Audio
const uint8_t  BAP_FCT_TEXT  = 0x17;  // Function ID: Station Name / Main Screen Text
const uint8_t  BAP_OP_STATUS = 0x04;  // OpCode: Status (Report to Cluster)

/**
 * Sends a segmented BAP long frame to the instrument cluster.
 * 
 * Frame 0 (Start Frame 0x80):
 *   Byte 0: 0x80 | (group_id << 4) | (total_len >> 8)
 *   Byte 1: total_len & 0xFF
 *   Byte 2: Header Byte 0 ((op_code << 4) | (lsg_id >> 2))
 *   Byte 3: Header Byte 1 (((lsg_id & 0x03) << 6) | (fct_id & 0x3F))
 *   Bytes 4..7: First 4 payload bytes (Byte 4 is string length, bytes 5..7 initial chars)
 *
 * Continuation Frames (0xC0 | seq):
 *   Byte 0: 0xC0 | (group_id << 4) | (seq & 0x0F)
 *   Bytes 1..7: Next chunk of ASCII characters
 */
void sendBapLongString(uint16_t canId, uint8_t opCode, uint8_t lsgId, uint8_t fctId, const char* text, uint8_t groupId = 0) {
    size_t textLen = strlen(text);
    if (textLen > 60) textLen = 60; // White MFA+ display buffer limit

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
        f0[i] = 0x00; // Zero padding
    }

    CAN0.sendMsgBuf(canId, 0, 8, f0);
    delay(4); // 4ms inter-frame pacing for cluster reassembly

    // Continuation Frames (0xC0, 0xC1, ...)
    size_t offset = 4;
    uint8_t seq = 0;

    while (offset < totalPayloadLen) {
        uint8_t fn[8];
        memset(fn, 0, sizeof(fn));
        fn[0] = 0xC0 | ((groupId & 0x03) << 4) | (seq & 0x0F);

        size_t chunk = totalPayloadLen - offset;
        if (chunk > 7) chunk = 7;

        for (size_t i = 0; i < chunk; i++) {
            fn[1 + i] = payload[offset + i];
        }

        CAN0.sendMsgBuf(canId, 0, 1 + chunk, fn);
        offset += chunk;
        seq = (seq + 1) & 0x0F;
        delay(4); // 4ms pacing
    }
}

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 2000);

    Serial.println("\n========================================================");
    Serial.println("  ESP32 VW Passat B6 MFA+ BAP Controller Initializing   ");
    Serial.println("========================================================");
    Serial.printf("  CAN Bus: 100 kbps (VW PQ46 Infotainment)\n");
    Serial.printf("  MCP2515 CS Pin: %d | INT Pin: %d\n", CAN_CS_PIN, CAN_INT_PIN);
    Serial.printf("  Target CAN ID: 0x%03X (Audio BAP)\n", BAP_CAN_ID);
    Serial.println("--------------------------------------------------------");

    // Initialize MCP2515 at 100 kbps with specified oscillator
    if (CAN0.begin(MCP_ANY, CAN_100KBPS, CAN_OSC_MHZ) == CAN_OK) {
        Serial.println("[ESP32] MCP2515 Initialized Successfully at 100 kbps!");
    } else {
        Serial.println("[ESP32] FATAL: Error Initializing MCP2515!");
        Serial.println("        1. Check SPI wiring (CS, SCK, MOSI, MISO, GND, VCC).");
        Serial.println("        2. Verify crystal frequency (8MHz vs 16MHz in platformio.ini).");
        while (1) {
            delay(1000);
        }
    }

    CAN0.setMode(MCP_NORMAL);
    pinMode(CAN_INT_PIN, INPUT);
    Serial.println("[ESP32] MCP2515 in NORMAL mode. Ready.\n");
}

unsigned long lastSendTime = 0;
uint32_t screenCounter = 0;

void loop() {
    // Periodically refresh the cluster display every 150ms
    // Refresh rate keeps the custom screen active and overwrites OEM / Android head unit packets
    if (millis() - lastSendTime >= 150) {
        lastSendTime = millis();

        char displayBuffer[32];
        snprintf(displayBuffer, sizeof(displayBuffer), "PASSAT B6 #%u", screenCounter++);

        sendBapLongString(BAP_CAN_ID, BAP_OP_STATUS, BAP_LSG_AUDIO, BAP_FCT_TEXT, displayBuffer);
    }

    // Monitor incoming CAN messages via MCP2515 interrupt pin
    if (!digitalRead(CAN_INT_PIN)) {
        long unsigned int rxId;
        unsigned char len = 0;
        unsigned char rxBuf[8];

        CAN0.readMsgBuf(&rxId, &len, rxBuf);

        // Steering wheel button events on CAN ID 0x5C1
        if (rxId == 0x5C1 && len > 0) {
            uint8_t btnCode = rxBuf[0];
            if (btnCode != 0x00) {
                Serial.printf("[MFSW] Steering Wheel Button Pressed: 0x%02X\n", btnCode);
            }
        }
    }
}
