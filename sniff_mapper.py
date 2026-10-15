#!/usr/bin/env python3
"""
Interactive Differential CAN Mapper & BAP Decoder for VW PQ46 (Passat B6).
Hardware: PeakCAN-USB on PCAN_USBBUS1 at 100 kbps (listen-only / passive).
Simulation: Built-in mock bus for testing without hardware connected.
"""

import sys
import time
import json
import argparse
from typing import Dict, Set, Tuple, List, Optional

try:
    import can
    from can.bus import BusState
except ImportError:
    print("[!] python-can is not installed. Run: pip install python-can")
    sys.exit(1)

from bap_protocol import (
    decode_bap_header,
    BapReassembler,
    DEFAULT_BAP_AUDIO_CAN_ID,
    LSG_AUDIO
)
from vw_can_sim import MockVwCanBus

DEFAULT_CHANNEL = 'PCAN_USBBUS1'
DEFAULT_BITRATE = 100000  # 100 kbps strictly for VW PQ46 Infotainment CAN


def create_can_bus(channel: str = DEFAULT_CHANNEL, bitrate: int = DEFAULT_BITRATE, force_mock: bool = False):
    """
    Attempt to initialize physical PeakCAN bus in PASSIVE mode.
    If physical hardware is unavailable or force_mock is requested, return MockVwCanBus.
    """
    if force_mock:
        print("[*] Mock mode explicitly selected. Initializing simulated VW PQ46 bus...")
        return MockVwCanBus(channel='SIMULATED_PQ46', bitrate=bitrate), True

    print(f"[*] Attempting connection to hardware '{channel}' at {bitrate} bps (Passive Mode)...")
    try:
        bus = can.interface.Bus(
            interface='pcan',
            channel=channel,
            bitrate=bitrate,
            state=BusState.PASSIVE
        )
        print(f"[+] Successfully connected to physical PeakCAN adapter on {channel}!")
        return bus, False
    except Exception as err:
        print(f"[-] Physical PeakCAN adapter not available: {err}")
        print("[!] Falling back to built-in VW PQ46 CAN simulator for offline verification.")
        print("    (When you plug in your PeakCAN adapter, this script will automatically connect to hardware.)\n")
        return MockVwCanBus(channel='SIMULATED_PQ46', bitrate=bitrate), True


def capture_window(
    bus: can.BusABC,
    duration_sec: float,
    reassembler: Optional[BapReassembler] = None,
    action_name: Optional[str] = None
) -> Tuple[Dict[int, Set[str]], List[Dict]]:
    """
    Record CAN traffic for `duration_sec` seconds.
    Tracks all unique payload hex strings per CAN ID.
    Reassembles and decodes BAP long frames (0x600-0x6FF).
    """
    if isinstance(bus, MockVwCanBus):
        bus.set_action(action_name)

    seen_payloads: Dict[int, Set[str]] = {}
    decoded_bap_strings: List[Dict] = []
    
    if reassembler is None:
        reassembler = BapReassembler()

    end_time = time.time() + duration_sec
    while time.time() < end_time:
        remaining = max(0.01, end_time - time.time())
        msg = bus.recv(timeout=min(0.05, remaining))
        if not msg:
            continue

        cid = msg.arbitration_id
        payload_bytes = bytes(msg.data)
        hex_data = payload_bytes.hex()

        if cid not in seen_payloads:
            seen_payloads[cid] = set()
        seen_payloads[cid].add(hex_data)

        # Monitor BAP range (0x600 to 0x6FF)
        if 0x600 <= cid <= 0x6FF:
            decoded = reassembler.process_frame(cid, payload_bytes)
            if decoded is not None:
                decoded_bap_strings.append(decoded)

    return seen_payloads, decoded_bap_strings


def print_banner(is_mock: bool, channel: str, bitrate: int):
    print("=" * 70)
    print("  VW PASSAT B6 (PQ46) WHITE MFA+ DIFFERENTIAL CAN MAPPER & BAP SNIFFER  ")
    print("=" * 70)
    print(f"  Target Bus: VW Infotainment CAN (100 kbps strictly)")
    print(f"  Hardware:   {channel} ({'SIMULATOR / MOCK' if is_mock else 'PHYSICAL PCAN'})")
    print(f"  Mode:       Passive Listen-Only (Zero transmission onto car bus)")
    print("=" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(description="VW Passat B6 Differential CAN & BAP Sniffer")
    parser.add_argument("--mock", action="store_true", help="Force mock/simulated CAN bus mode")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="CAN interface channel (default: PCAN_USBBUS1)")
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE, help="CAN bitrate (default: 100000)")
    parser.add_argument("--auto", action="store_true", help="Automated run without pausing for keyboard prompts")
    args = parser.parse_args()

    bus, is_mock = create_can_bus(channel=args.channel, bitrate=args.bitrate, force_mock=args.mock)
    print_banner(is_mock, args.channel, args.bitrate)

    bap_reassembler = BapReassembler()

    # STEP 1: Quiet Baseline
    print("----------------------------------------------------------------------")
    print("  STEP 1: QUIET BASELINE (6 SECONDS)")
    print("  Sit still, keep all doors closed, radio playing, and do NOT touch any controls.")
    print("----------------------------------------------------------------------")
    if not args.auto:
        input("Press [ENTER] to start recording 6-second baseline...")
    print("[*] Recording baseline...")
    
    baseline_payloads, baseline_bap = capture_window(
        bus, duration_sec=6.0, reassembler=bap_reassembler, action_name=None
    )

    # Check for silent physical bus (e.g. adapter plugged into USB but not connected to car)
    if len(baseline_payloads) == 0 and not is_mock:
        print("\n[!] NOTICE: Zero CAN messages received on physical PeakCAN adapter.")
        print("    Possible causes:")
        print("    - Laptop is at desk and CAN-H / CAN-L wires are not connected to the vehicle.")
        print("    - Car ignition is OFF or Infotainment CAN is asleep.")
        print("    - Pinout mismatch: CAN-H (Orange/Violet) -> DB9 Pin 7, CAN-L (Orange/Brown) -> DB9 Pin 2.")
        
        switch_to_mock = True
        if not args.auto:
            choice = input("\nWould you like to switch to the built-in VW PQ46 simulator to test now? [Y/n]: ")
            if choice.strip().lower() == 'n':
                switch_to_mock = False

        if switch_to_mock:
            print("[*] Switching to VW PQ46 simulator. Re-recording baseline...")
            bus.shutdown()
            bus = MockVwCanBus(channel='SIMULATED_PQ46', bitrate=args.bitrate)
            is_mock = True
            baseline_payloads, baseline_bap = capture_window(
                bus, duration_sec=6.0, reassembler=bap_reassembler, action_name=None
            )
    
    print(f"\n[+] Baseline recorded: {len(baseline_payloads)} active CAN IDs identified.")
    for cid in sorted(baseline_payloads.keys()):
        count = len(baseline_payloads[cid])
        sample = next(iter(baseline_payloads[cid]))
        print(f"    * ID 0x{cid:03X} : {count} distinct payload variation(s) | Sample: {sample}")

    if baseline_bap:
        print(f"[+] BAP messages detected in baseline ({len(baseline_bap)} total):")
        for b in baseline_bap:
            print(f"    * CAN {b['can_id']} [LSG {b['lsg_id']} FCT {b['fct_id']}]: '{b['text']}'")

    # Interactive Action Steps
    actions = [
        (
            "driver_door",
            "Open and close the DRIVER DOOR continuously for 5 seconds.",
            5.0
        ),
        (
            "steering_buttons",
            "Press and release STEERING WHEEL buttons (Volume Up/Down, Track, Menu) continuously for 5 seconds.",
            5.0
        ),
        (
            "android_radio_bap",
            "Turn the Android radio volume knob and switch stations / music tracks continuously for 8 seconds.",
            8.0
        )
    ]

    results = {
        "metadata": {
            "platform": "VW PQ46 (Passat B6 2010)",
            "bus": "Infotainment CAN (100 kbps)",
            "adapter": args.channel,
            "is_simulation": is_mock,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "baseline_ids": [f"0x{k:03X}" for k in sorted(baseline_payloads.keys())],
        "events": {}
    }

    for name, instructions, duration in actions:
        print("\n----------------------------------------------------------------------")
        print(f"  ACTION TEST: {name.upper()} ({int(duration)}s)")
        print(f"  Instruction: {instructions}")
        print("----------------------------------------------------------------------")
        if not args.auto:
            input(f"Press [ENTER] when ready, then immediately perform the action...")
            
        print(f"[*] Capturing {name} for {duration:.1f}s...")
        active_payloads, action_bap = capture_window(
            bus, duration_sec=duration, reassembler=bap_reassembler, action_name=name
        )

        # Differential Analysis
        delta: Dict[str, List[str]] = {}
        for cid, payloads in active_payloads.items():
            base = baseline_payloads.get(cid, set())
            new_payloads = payloads - base
            if new_payloads:
                delta[f"0x{cid:03X}"] = sorted(list(new_payloads))

        print(f"[+] Delta detected on {len(delta)} CAN ID(s):")
        for cid_str, diff_frames in delta.items():
            print(f"    * {cid_str} : {len(diff_frames)} new frame variant(s)")
            for df in diff_frames[:3]:
                print(f"        -> {df}")
            if len(diff_frames) > 3:
                print(f"        ... (+{len(diff_frames) - 3} more)")

        if action_bap:
            print(f"[+] Captured BAP Strings during {name}:")
            for item in action_bap:
                print(f"    * CAN ID: {item['can_id']} | LSG: {item['lsg_id']} | FCT: {item['fct_id']} | Text: '{item['text']}'")

        results["events"][name] = {
            "instruction": instructions,
            "duration_sec": duration,
            "delta_frames": delta,
            "bap_strings": action_bap
        }

    bus.shutdown()

    output_filename = "bus_map.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print(f"[SUCCESS] Differential mapping complete! Results saved to '{output_filename}'.")
    print("=" * 70)


if __name__ == "__main__":
    main()
