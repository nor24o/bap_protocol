#!/usr/bin/env python3
"""
Custom BAP Text & State Injector for VW MFA+ Cluster (Passat B6 PQ46).
Supports physical PeakCAN hardware in ACTIVE mode at 100 kbps.
Includes BAP protocol handshakes (BAP-Config, Function-List, FSG-OperationState)
and multi-frame segmented text broadcasting for Audio (0x66C), Navigation (0x67D),
and dual-channel injection.
"""

import sys
import time
import argparse
from typing import Optional, List, Tuple

try:
    import can
    from can.bus import BusState
except ImportError:
    print("[!] python-can is not installed. Run: pip install python-can")
    sys.exit(1)

from bap_protocol import (
    build_bap_long_frames,
    encode_bap_header,
    decode_bap_header,
    BapReassembler,
    BAP_CAN_ID_AUDIO,
    BAP_CAN_ID_NAVIGATION,
    BAP_CAN_ID_TELEPHONE,
    LSG_AUDIO,
    LSG_NAVIGATION,
    LSG_TELEPHONE,
    FCT_AUDIO_STATION_NAME,
    FCT_AUDIO_TRACK_NAME,
    OP_CHANGED,
    OP_STATUS
)

DEFAULT_CHANNEL = 'PCAN_USBBUS1'
DEFAULT_BITRATE = 100000  # 100 kbps strictly for VW PQ46 Infotainment CAN


def send_bap_handshake(bus: can.BusABC, can_id: int, lsg_id: int):
    """
    Execute BAP initialization sequence required by the ASG (Instrument Cluster):
    1. BAP-Config (FCT 0x02)
    2. Function-List (FCT 0x03, 8-byte bitmask)
    3. FSG-OperationState (FCT 0x0F = 0x00 Normal Operation)
    """
    print(f"[*] Sending BAP Handshake on CAN ID 0x{can_id:03X} (LSG 0x{lsg_id:02X})...")
    
    # 1. BAP Config (FCT 0x02)
    hdr0, hdr1 = encode_bap_header(OP_CHANGED, lsg_id, 0x02)
    config_msg = can.Message(
        arbitration_id=can_id,
        data=[hdr0, hdr1, 0x03, 0x00, lsg_id, 0x00, 0x03, 0x01],
        is_extended_id=False
    )
    bus.send(config_msg)
    time.sleep(0.005)

    # 2. Function-List (FCT 0x03) - Segmented frame
    hdr0, hdr1 = encode_bap_header(OP_CHANGED, lsg_id, 0x03)
    f0 = can.Message(
        arbitration_id=can_id,
        data=[0x80, 0x08, hdr0, hdr1, 0x38, 0x03, 0xFF, 0xFC],
        is_extended_id=False
    )
    f1 = can.Message(
        arbitration_id=can_id,
        data=[0xC0, 0x00, 0x00, 0x00, 0x00],
        is_extended_id=False
    )
    bus.send(f0)
    time.sleep(0.004)
    bus.send(f1)
    time.sleep(0.005)

    # 3. FSG-OperationState: Normal Operation (FCT 0x0F, payload 0x00)
    hdr0, hdr1 = encode_bap_header(OP_CHANGED, lsg_id, 0x0F)
    opstate_msg = can.Message(
        arbitration_id=can_id,
        data=[hdr0, hdr1, 0x00],
        is_extended_id=False
    )
    bus.send(opstate_msg)
    time.sleep(0.010)
    print(f"[+] Handshake complete on 0x{can_id:03X}!")


def inspect_frames(frames: List[Tuple[int, bytes]], target_text: str):
    """
    Detailed frame-by-frame diagnostic breakdown for offline verification.
    """
    print("\n" + "=" * 70)
    print("  BAP PACKET STRUCTURE INSPECTION & VALIDATION  ")
    print("=" * 70)
    print(f"Target Text:      '{target_text}' ({len(target_text)} characters)")
    print(f"Total CAN Frames: {len(frames)}")
    print("-" * 70)

    reassembler = BapReassembler()
    cluster_decoded = None

    for i, (cid, data) in enumerate(frames):
        b0 = data[0]
        hex_dump = " ".join(f"{b:02X}" for b in data)
        frame_type_str = "START (0x80)" if (b0 & 0xC0) == 0x80 else f"CONT (0xC0 seq={b0 & 0x0F})"

        print(f"Frame #{i:02d} | CAN ID: 0x{cid:03X} | [{frame_type_str}]")
        print(f"  HEX: {hex_dump}")

        if (b0 & 0xC0) == 0x80:
            total_len = ((b0 & 0x0F) << 8) | data[1]
            op, lsg, fct = decode_bap_header(data[2], data[3])
            str_len = data[4]
            first_chars = data[5:].decode('ascii', errors='replace').rstrip('\x00')
            print(f"  Header Breakdown: TotalPayloadLen={total_len} | OpCode=0x{op:X} (Changed) | LSG=0x{lsg:X} | FCT=0x{fct:X}")
            print(f"  Initial Chunk:    StrLenByte={str_len} | TextChars='{first_chars}'")
        else:
            chunk = data[1:].decode('ascii', errors='replace')
            print(f"  Continuation:     TextChars='{chunk}'")

        res = reassembler.process_frame(cid, data)
        if res:
            cluster_decoded = res

    print("-" * 70)
    if cluster_decoded and cluster_decoded['text'] == target_text[:60]:
        print(f"[+] CLUSTER EMULATOR VERIFICATION: PASSED!")
        print(f"    Reassembled Text: '{cluster_decoded['text']}'")
        print(f"    Payload Size:     {cluster_decoded['total_len']} bytes")
    else:
        print(f"[!] Cluster emulator check discrepancy: {cluster_decoded}")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Inject custom text to VW MFA+ cluster via BAP")
    parser.add_argument("text", nargs="?", default="CUSTOM SCREEN", help="Text to display on cluster")
    parser.add_argument("--line2", default="", help="Secondary line text (for Audio track or Nav street)")
    parser.add_argument("--mode", choices=["audio", "navi", "both"], default="both",
                        help="Target subsystem: 'audio' (0x66C), 'navi' (0x67D), or 'both' (default: both)")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="CAN interface channel (default: PCAN_USBBUS1)")
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE, help="CAN bitrate (default: 100000)")
    parser.add_argument("--duration", type=float, default=10.0, help="Transmission burst duration in seconds (default: 10.0)")
    parser.add_argument("--interval", type=float, default=0.080, help="Burst repeat interval in seconds (default: 0.080)")
    parser.add_argument("--gap", type=float, default=0.004, help="Inter-frame delay in seconds (default: 0.004)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and validate frames without sending to hardware")
    args = parser.parse_args()

    targets = []
    if args.mode in ("audio", "both"):
        targets.append(("Audio", BAP_CAN_ID_AUDIO, LSG_AUDIO, FCT_AUDIO_STATION_NAME, FCT_AUDIO_TRACK_NAME))
    if args.mode in ("navi", "both"):
        targets.append(("Navigation", BAP_CAN_ID_NAVIGATION, LSG_NAVIGATION, 0x17, 0x16))

    all_raw_frames = []
    for name, cid, lsg, fct1, fct2 in targets:
        # Line 1 (Main Station / Header)
        frames_l1 = build_bap_long_frames(
            can_id=cid,
            op_code=OP_CHANGED,
            lsg_id=lsg,
            fct_id=fct1,
            text_string=args.text
        )
        all_raw_frames.extend(frames_l1)
        
        # Line 2 (Secondary line if provided)
        if args.line2:
            frames_l2 = build_bap_long_frames(
                can_id=cid,
                op_code=OP_CHANGED,
                lsg_id=lsg,
                fct_id=fct2,
                text_string=args.line2
            )
            all_raw_frames.extend(frames_l2)

    inspect_frames(all_raw_frames[:len(all_raw_frames)//len(targets)], args.text)

    if args.dry_run:
        print("[*] Dry-run complete. Exiting without transmitting.")
        return

    # Attempt to open physical hardware
    print(f"[*] Attempting to open {args.channel} in ACTIVE mode at {args.bitrate} bps...")
    try:
        bus = can.interface.Bus(
            interface='pcan',
            channel=args.channel,
            bitrate=args.bitrate,
            state=BusState.ACTIVE
        )
        print(f"[+] Hardware opened successfully on {args.channel}!")
    except Exception as err:
        print(f"[-] Physical PeakCAN adapter not detected: {err}")
        print("[!] Note: Make sure PeakCAN is plugged in and drivers installed.")
        return

    # 1. Execute BAP Handshake on each target channel first
    for name, cid, lsg, _, _ in targets:
        send_bap_handshake(bus, cid, lsg)

    # Convert text payload frames to can.Message objects
    can_messages = [
        can.Message(arbitration_id=cid, data=data, is_extended_id=False)
        for cid, data in all_raw_frames
    ]

    target_desc = ", ".join(f"{name} (0x{cid:03X})" for name, cid, _, _, _ in targets)
    print(f"\n[*] Transmitting '{args.text}' onto {target_desc} for {args.duration}s...")
    print(f"    Repeat interval: {int(args.interval * 1000)}ms | Inter-frame gap: {int(args.gap * 1000)}ms")
    end_time = time.time() + args.duration
    burst_count = 0

    try:
        while time.time() < end_time:
            burst_count += 1
            for msg in can_messages:
                bus.send(msg)
                time.sleep(args.gap)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[!] Transmission interrupted by user.")
    finally:
        bus.shutdown()

    print(f"\n[+] Successfully completed {burst_count} bursts across {args.duration:.1f}s.")
    print("[+] Check your cluster display now!")


if __name__ == "__main__":
    main()
