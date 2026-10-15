#!/usr/bin/env python3
"""
Single-Action Differential CAN Capture for VW Passat B6 (PQ46)
Records a designated action window, computes differential against baseline,
reassembles BAP frames, and merges into bus_map.json.
"""

import sys
import time
import json
import argparse
from typing import Dict, Set, List

try:
    import can
    from can.bus import BusState
except ImportError:
    print("[!] python-can is not installed.")
    sys.exit(1)

from bap_protocol import BapReassembler

CHANNEL = 'PCAN_USBBUS1'
BITRATE = 100000


def run_action_capture(action_name: str, duration_sec: float = 5.0, instruction: str = ""):
    print(f"\n[*] Starting capture for action: {action_name.upper()}")
    print(f"[*] Instruction: {instruction}")
    print(f"[*] Opening {CHANNEL} in PASSIVE mode...")

    # Load baseline from baseline_analysis.json or bus_map.json
    baseline_payloads = {}
    try:
        with open("baseline_analysis.json", "r") as f:
            base_data = json.load(f)
            for cid_str, info in base_data.get("can_ids", {}).items():
                cid = int(cid_str, 16)
                baseline_payloads[cid] = set(info.get("distinct_payloads", []))
    except Exception as e:
        print(f"[!] Note: Could not load baseline_analysis.json ({e}). Baseline will be empty.")

    bus = can.interface.Bus(interface='pcan', channel=CHANNEL, bitrate=BITRATE, state=BusState.PASSIVE)
    reassembler = BapReassembler()

    seen_payloads: Dict[int, Set[str]] = {}
    decoded_bap = []

    print(f"[*] Capturing frames for {duration_sec:.1f} seconds NOW. Please perform the action...")
    start_time = time.time()
    end_time = start_time + duration_sec
    frame_count = 0

    while time.time() < end_time:
        msg = bus.recv(timeout=0.05)
        if not msg:
            continue
        frame_count += 1
        cid = msg.arbitration_id
        hex_data = bytes(msg.data).hex()

        if cid not in seen_payloads:
            seen_payloads[cid] = set()
        seen_payloads[cid].add(hex_data)

        if 0x600 <= cid <= 0x6FF:
            res = reassembler.process_frame(cid, bytes(msg.data))
            if res:
                decoded_bap.append(res)

    bus.shutdown()
    actual_duration = time.time() - start_time
    print(f"[+] Capture finished: {frame_count} frames received in {actual_duration:.2f}s.")

    # Compute delta
    delta: Dict[str, List[str]] = {}
    for cid, payloads in seen_payloads.items():
        base = baseline_payloads.get(cid, set())
        diff = payloads - base
        if diff:
            delta[f"0x{cid:03X}"] = sorted(list(diff))

    print(f"\n[+] Differential Analysis Results for '{action_name}':")
    if delta:
        print(f"    Detected {len(delta)} CAN ID(s) with new / changed payloads:")
        for cid_str, new_frames in delta.items():
            print(f"    * {cid_str} ({len(new_frames)} new frame variant(s)):")
            for nf in new_frames[:5]:
                print(f"        -> {nf}")
            if len(new_frames) > 5:
                print(f"        ... (+{len(new_frames)-5} more)")
    else:
        print("    [!] No delta detected compared to quiet baseline.")

    if decoded_bap:
        print(f"\n[+] Decoded BAP Messages ({len(decoded_bap)} total):")
        for b in decoded_bap:
            safe_text = b['text'].encode('ascii', errors='backslashreplace').decode('ascii')
            print(f"    * CAN: {b['can_id']} | LSG: {b['lsg_id']} | FCT: {b['fct_id']} | Op: 0x{b['op_code']:X} | Text: {repr(safe_text)}")

    # Update bus_map.json
    bus_map = {}
    try:
        with open("bus_map.json", "r") as f:
            bus_map = json.load(f)
    except Exception:
        bus_map = {"metadata": {}, "events": {}}

    bus_map["metadata"]["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    bus_map["metadata"]["channel"] = CHANNEL
    bus_map["metadata"]["is_simulation"] = False
    if "events" not in bus_map:
        bus_map["events"] = {}

    bus_map["events"][action_name] = {
        "instruction": instruction,
        "duration_sec": actual_duration,
        "total_frames_captured": frame_count,
        "delta_frames": delta,
        "bap_strings": decoded_bap
    }

    with open("bus_map.json", "w", encoding="utf-8") as f:
        json.dump(bus_map, f, indent=2)

    print(f"\n[+] Merged results into 'bus_map.json'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, help="Action name (e.g. driver_door, steering_buttons, android_radio_bap)")
    parser.add_argument("--duration", type=float, default=5.0, help="Duration in seconds")
    parser.add_argument("--instruction", default="", help="Instruction description")
    args = parser.parse_args()

    run_action_capture(args.action, args.duration, args.instruction)
