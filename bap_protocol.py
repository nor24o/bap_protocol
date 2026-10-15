"""
VW BAP (Bedien- und Anzeigeprotokoll) Protocol Engine
Volkswagen PQ35 / PQ46 Infotainment CAN (White MFA+ Instrument Cluster)
"""

from typing import List, Dict, Optional, Tuple
import time

# Standard Logical Device IDs (LSG-ID)
LSG_TELEPHONE   = 0x28
LSG_AUDIO       = 0x31  # Infotainment Radio / Android Head Unit
LSG_NAVIGATION  = 0x32  # Navigation System
LSG_CLIMATE     = 0x35

# Standard BAP Function IDs (FCT-ID) for Audio (LSG 0x31)
FCT_AUDIO_STATION_NAME  = 0x17  # Station name / screen text (white MFA+ top/center display)
FCT_AUDIO_TRACK_NAME    = 0x18  # Track info / metadata
FCT_AUDIO_SOURCE_STATUS = 0x19  # Current source (FM, AM, CD, BT, etc.)
FCT_AUDIO_VOLUME        = 0x22  # Volume level

# Standard OpCodes (Volkswagen BAP Specification)
OP_SET      = 0x0  # ASG -> FSG: Set property / Start method
OP_GET      = 0x1  # ASG -> FSG: Query property
OP_STATUS   = 0x2  # FSG -> ASG: Status response
OP_CHANGED  = 0x3  # FSG -> ASG: Unsolicited / event-driven display update
OP_ERROR    = 0x4  # Protocol / application error

# Standard CAN IDs on VW PQ35 / PQ46 Infotainment Bus (100 kbps)
BAP_CAN_ID_AUDIO      = 0x66C  # FSG (Radio) -> ASG (Cluster)
BAP_CAN_ID_TELEPHONE  = 0x66F  # FSG (Phone) -> ASG (Cluster)
BAP_CAN_ID_NAVIGATION = 0x67D  # FSG (Navi)  -> ASG (Cluster)
DEFAULT_BAP_AUDIO_CAN_ID = BAP_CAN_ID_AUDIO


def encode_bap_header(op_code: int, lsg_id: int, fct_id: int) -> Tuple[int, int]:
    """
    Encode 16-bit BAP Header:
    Bit 15: Frame type (0 for short frame in basic header)
    Bits 14..12: OpCode (3 bits)
    Bits 11..6:  LSG-ID (6 bits)
    Bits 5..0:   FCT-ID (6 bits)
    Returns: (byte0, byte1)
    """
    b0 = ((op_code & 0x07) << 4) | ((lsg_id >> 2) & 0x0F)
    b1 = ((lsg_id & 0x03) << 6) | (fct_id & 0x3F)
    return b0, b1


def decode_bap_header(b0: int, b1: int) -> Tuple[int, int, int]:
    """
    Decode 16-bit BAP Header bytes into (op_code, lsg_id, fct_id).
    """
    op_code = (b0 >> 4) & 0x07
    lsg_id = ((b0 & 0x0F) << 2) | ((b1 >> 6) & 0x03)
    fct_id = b1 & 0x3F
    return op_code, lsg_id, fct_id


def build_bap_long_frames(
    can_id: int = DEFAULT_BAP_AUDIO_CAN_ID,
    op_code: int = OP_STATUS,
    lsg_id: int = LSG_AUDIO,
    fct_id: int = FCT_AUDIO_STATION_NAME,
    text_string: str = "CUSTOM SCREEN",
    group_id: int = 0
) -> List[Tuple[int, bytes]]:
    """
    Build segmented BAP long frames for transmitting text to VW white MFA+ cluster.
    
    Frame Structure:
    1. Start Frame (0x80):
       - Byte 0: 0x80 | (group_id << 4) | ((total_len >> 8) & 0x0F)
       - Byte 1: total_len & 0xFF
       - Byte 2: BAP Header Byte 0 ((op_code << 4) | (lsg_id >> 2))
       - Byte 3: BAP Header Byte 1 (((lsg_id & 0x03) << 6) | (fct_id & 0x3F))
       - Bytes 4..7: First 4 bytes of payload (Byte 4 is string length, bytes 5..7 initial chars)
       
    2. Continuation Frames (0xC0, 0xC1, ...):
       - Byte 0: 0xC0 | (group_id << 4) | (seq & 0x0F)
       - Bytes 1..7: Up to 7 subsequent ASCII characters
    
    Returns: List of tuples (can_id, payload_bytes)
    """
    # Enforce maximum text length supported by cluster line buffer
    text_bytes = text_string.encode('ascii', errors='replace')[:60]
    
    # Payload format: 1-byte length followed by ASCII characters
    payload = bytes([len(text_bytes)]) + text_bytes
    total_len = len(payload)
    
    hdr0, hdr1 = encode_bap_header(op_code, lsg_id, fct_id)
    
    frames: List[Tuple[int, bytes]] = []
    
    # Start Frame (0x80)
    b0 = 0x80 | ((group_id & 0x03) << 4) | ((total_len >> 8) & 0x0F)
    b1 = total_len & 0xFF
    first_chunk = payload[:4]
    frame0_data = bytes([b0, b1, hdr0, hdr1]) + first_chunk
    # Pad to 8 bytes if needed
    if len(frame0_data) < 8:
        frame0_data = frame0_data.ljust(8, b'\x00')
    frames.append((can_id, frame0_data))
    
    # Continuation Frames (0xC0 | seq)
    offset = 4
    seq = 0
    while offset < total_len:
        cb0 = 0xC0 | ((group_id & 0x03) << 4) | (seq & 0x0F)
        chunk = payload[offset:offset + 7]
        frame_data = bytes([cb0]) + chunk
        frames.append((can_id, frame_data))
        offset += len(chunk)
        seq = (seq + 1) & 0x0F
        
    return frames


class BapReassembler:
    """
    Stateful reassembler for segmented VW BAP frames over CAN bus.
    Tracks ongoing segmented transfers keyed by (CAN_ID, Group_ID).
    """
    def __init__(self, timeout_sec: float = 0.5):
        self.timeout_sec = timeout_sec
        self.active_transfers: Dict[Tuple[int, int], Dict] = {}
        
    def process_frame(self, can_id: int, data: bytes) -> Optional[Dict]:
        """
        Feed a raw CAN frame into the reassembler.
        Returns a decoded dictionary when a multi-frame BAP message is fully reassembled.
        """
        now = time.time()
        # Clean up stale transfers
        expired_keys = [k for k, v in self.active_transfers.items() if now - v['start_time'] > self.timeout_sec]
        for k in expired_keys:
            del self.active_transfers[k]
            
        if len(data) < 2:
            return None
            
        b0 = data[0]
        frame_type = b0 & 0xC0
        group_id = (b0 >> 4) & 0x03
        key = (can_id, group_id)
        
        # Start Frame (0x80)
        if frame_type == 0x80:
            if len(data) < 4:
                return None
            total_len = ((b0 & 0x0F) << 8) | data[1]
            op_code, lsg_id, fct_id = decode_bap_header(data[2], data[3])
            
            initial_payload = bytearray(data[4:])
            self.active_transfers[key] = {
                'can_id': can_id,
                'group_id': group_id,
                'op_code': op_code,
                'lsg_id': lsg_id,
                'fct_id': fct_id,
                'total_len': total_len,
                'buffer': initial_payload,
                'expected_seq': 0,
                'start_time': now,
                'raw_frames': [data.hex()]
            }
            
            # If total_len fits in start frame
            if len(initial_payload) >= total_len:
                return self._finalize_transfer(key)
            return None
            
        # Continuation Frame (0xC0)
        elif frame_type == 0xC0:
            if key not in self.active_transfers:
                return None  # Orphaned continuation frame
                
            entry = self.active_transfers[key]
            seq = b0 & 0x0F
            entry['raw_frames'].append(data.hex())
            entry['buffer'].extend(data[1:])
            entry['expected_seq'] = (entry['expected_seq'] + 1) & 0x0F
            
            if len(entry['buffer']) >= entry['total_len']:
                return self._finalize_transfer(key)
            return None
            
        return None

    def _finalize_transfer(self, key: Tuple[int, int]) -> Dict:
        entry = self.active_transfers.pop(key)
        raw_payload = bytes(entry['buffer'][:entry['total_len']])
        
        # In BAP text messages, byte 0 is length of string
        string_len = raw_payload[0] if len(raw_payload) > 0 else 0
        text_bytes = raw_payload[1:1 + string_len]
        decoded_text = text_bytes.decode('ascii', errors='replace')
        
        return {
            'can_id': hex(entry['can_id']),
            'group_id': entry['group_id'],
            'lsg_id': hex(entry['lsg_id']),
            'fct_id': hex(entry['fct_id']),
            'op_code': entry['op_code'],
            'total_len': entry['total_len'],
            'text': decoded_text,
            'raw_payload_hex': raw_payload.hex(),
            'raw_frames': entry['raw_frames']
        }
