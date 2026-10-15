#!/usr/bin/env python3
"""
Deep Live Baseline & CAN Timing Analyzer for VW Passat B6 (PQ46)
Interface: PeakCAN-USB on PCAN_USBBUS1 at 100 kbps (Passive Listen-Only).
Analyzes cycle times, jitter, rolling counters, and BAP packets.
"""

import sys
import time
import json
from collections import defaultdict
from typing import Dict, List, Any

try:
    import can
    from can.bus import BusState
except ImportError:
    print("[!] python-can not installed.")
    sys.exit(1)

from bap_protocol import BapReassembler, decode_bap_header

CHANNEL = 'PCAN_USBBUS1'
BITRATE = 100000


def analyze_baseline(duration_sec: float = 6.0):
    print(f"[*] Opening {CHANNEL} at {BITRATE} bps in PASSIVE mode...")
    bus = can.interface.Bus(interface='pcan', channel=CHANNEL, bitrate=BITRATE, state=BusState.PASSIVE)

    print(f"[*] Recording quiet baseline for {duration_sec:.1f} seconds...")
    start_time = time.time()
    end_time = start_time + duration_sec

    frames_by_id: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    bap_reassembler = BapReassembler()
    bap_messages = []
    raw_bap_frames = []

    msg_count = 0
    while time.time() < end_time:
        msg = bus.recv(timeout=0.05)
        if not msg:
            continue
        msg_count += 1
        t = time.time()
        cid = msg.arbitration_id
        data_bytes = bytes(msg.data)
        
        frames_by_id[cid].append({
            'timestamp': t,
            'data': data_bytes,
            'hex': data_bytes.hex()
        })

        if 0x600 <= cid <= 0x6FF:
            raw_bap_frames.append({
                'can_id': hex(cid),
                'hex': data_bytes.hex(),
                'timestamp': t
            })
            decoded = bap_reassembler.process_frame(cid, data_bytes)
            if decoded:
                bap_messages.append(decoded)

    bus.shutdown()
    actual_duration = time.time() - start_time
    print(f"[+] Baseline capture complete. Total frames received: {msg_count} across {actual_duration:.2f}s.")

    # Analysis
    analysis_results = {
        "summary": {
            "channel": CHANNEL,
            "bitrate": BITRATE,
            "duration_sec": actual_duration,
            "total_frames": msg_count,
            "unique_ids_count": len(frames_by_id)
        },
        "can_ids": {},
        "bap_messages": bap_messages,
        "raw_bap_frames": raw_bap_frames
    }

    print("\n" + "=" * 80)
    print(f"{'CAN ID':<8} | {'Count':<6} | {'Cycle (ms)':<10} | {'Min..Max (ms)':<14} | {'Distinct Payloads':<18} | {'Rolling Counter'}")
    print("-" * 80)

    for cid in sorted(frames_by_id.keys()):
        frames = frames_by_id[cid]
        count = len(frames)
        distinct = sorted(list(set(f['hex'] for f in frames)))

        # Cycle time analysis
        intervals_ms = []
        for i in range(1, len(frames)):
            dt = (frames[i]['timestamp'] - frames[i-1]['timestamp']) * 1000.0
            intervals_ms.append(dt)

        if intervals_ms:
            avg_cycle = sum(intervals_ms) / len(intervals_ms)
            min_cycle = min(intervals_ms)
            max_cycle = max(intervals_ms)
            cycle_str = f"{avg_cycle:6.1f} ms"
            minmax_str = f"{min_cycle:4.1f}..{max_cycle:4.1f}"
        else:
            avg_cycle = None
            minmax_str = "N/A"
            cycle_str = "Single"

        # Rolling counter detection
        counter_info = None
        min_len = min(len(f['data']) for f in frames) if frames else 0
        if count >= 4 and min_len > 0:
            # Check each byte and nibble
            for byte_idx in range(min_len):
                vals = [f['data'][byte_idx] for f in frames]
                # Check low nibble
                low_nibbles = [v & 0x0F for v in vals]
                diffs = [(low_nibbles[i] - low_nibbles[i-1]) % 16 for i in range(1, len(low_nibbles))]
                if len(diffs) > 3 and all(d in (1, 2) for d in diffs):
                    counter_info = f"Byte {byte_idx} Low Nibble (0..15)"
                    break

                # Check high nibble
                high_nibbles = [(v >> 4) & 0x0F for v in vals]
                h_diffs = [(high_nibbles[i] - high_nibbles[i-1]) % 16 for i in range(1, len(high_nibbles))]
                if len(h_diffs) > 3 and all(d in (1, 2) for d in h_diffs):
                    counter_info = f"Byte {byte_idx} High Nibble (0..15)"
                    break

        counter_str = counter_info if counter_info else "None detected"

        print(f"0x{cid:03X}    | {count:<6} | {cycle_str:<10} | {minmax_str:<14} | {len(distinct):<18} | {counter_str}")

        analysis_results["can_ids"][f"0x{cid:03X}"] = {
            "count": count,
            "avg_cycle_ms": round(avg_cycle, 2) if avg_cycle else None,
            "min_cycle_ms": round(min(intervals_ms), 2) if intervals_ms else None,
            "max_cycle_ms": round(max(intervals_ms), 2) if intervals_ms else None,
            "distinct_count": len(distinct),
            "distinct_payloads": distinct[:10],
            "rolling_counter": counter_info
        }

    print("=" * 80)

    if bap_messages:
        print(f"\n[+] Captured {len(bap_messages)} decoded BAP message(s):")
        for b in bap_messages:
            safe_text = b['text'].encode('ascii', errors='backslashreplace').decode('ascii')
            print(f"    * CAN: {b['can_id']} | LSG: {b['lsg_id']} | FCT: {b['fct_id']} | Text: {repr(safe_text)}")
    else:
        print("\n[*] No multi-frame BAP text strings reassembled during quiet baseline.")
        if raw_bap_frames:
            print(f"[*] Found {len(raw_bap_frames)} raw frames in BAP range (0x600-0x6FF):")
            for rf in raw_bap_frames[:10]:
                print(f"    * {rf['can_id']} : {rf['hex']}")

    with open("baseline_analysis.json", "w") as f:
        json.dump(analysis_results, f, indent=2)
    print("\n[+] Full baseline analysis saved to 'baseline_analysis.json'.")


if __name__ == "__main__":
    analyze_baseline(6.0)
