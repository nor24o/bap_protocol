"""
Unit & Integration Tests for VW BAP Protocol Engine
"""

import unittest
from bap_protocol import (
    encode_bap_header,
    decode_bap_header,
    build_bap_long_frames,
    BapReassembler,
    OP_STATUS,
    LSG_AUDIO,
    FCT_AUDIO_STATION_NAME,
    DEFAULT_BAP_AUDIO_CAN_ID
)


class TestBapProtocol(unittest.TestCase):
    def test_header_roundtrip(self):
        # Audio Status, FCT 0x17
        op = OP_STATUS  # 0x02
        lsg = LSG_AUDIO  # 0x31
        fct = FCT_AUDIO_STATION_NAME  # 0x17
        
        b0, b1 = encode_bap_header(op, lsg, fct)
        # Expected:
        # b0 = (2 << 4) | (0x31 >> 2) = 0x20 | 0x0C = 0x2C
        # b1 = ((0x31 & 3) << 6) | (0x17 & 0x3F) = (1 << 6) | 0x17 = 0x40 | 0x17 = 0x57
        self.assertEqual(b0, 0x2C)
        self.assertEqual(b1, 0x57)
        
        dec_op, dec_lsg, dec_fct = decode_bap_header(b0, b1)
        self.assertEqual(dec_op, op)
        self.assertEqual(dec_lsg, lsg)
        self.assertEqual(dec_fct, fct)

    def test_build_and_reassemble_short_string(self):
        text = "VW"
        frames = build_bap_long_frames(
            can_id=DEFAULT_BAP_AUDIO_CAN_ID,
            op_code=OP_STATUS,
            lsg_id=LSG_AUDIO,
            fct_id=FCT_AUDIO_STATION_NAME,
            text_string=text
        )
        # Length of payload = 1 (len byte) + 2 (chars) = 3 bytes
        # Fits entirely into Start Frame (which takes up to 4 bytes: length byte + 'V' + 'W')
        self.assertEqual(len(frames), 1)
        can_id, data = frames[0]
        self.assertEqual(can_id, DEFAULT_BAP_AUDIO_CAN_ID)
        self.assertEqual(len(data), 8)
        
        # Verify Start frame header
        # b0: 0x80 | total_len >> 8 (0) = 0x80
        # b1: total_len = 3
        # b2: 0x4C
        # b3: 0x57
        # b4: len byte = 2
        # b5: 'V' (0x56)
        # b6: 'W' (0x57)
        # b7: 0x00 padding
        self.assertEqual(data[0], 0x80)
        self.assertEqual(data[1], 0x03)
        self.assertEqual(data[2], 0x2C)
        self.assertEqual(data[3], 0x57)
        self.assertEqual(data[4], 2)
        self.assertEqual(data[5], ord('V'))
        self.assertEqual(data[6], ord('W'))
        
        reassembler = BapReassembler()
        result = reassembler.process_frame(can_id, data)
        self.assertIsNotNone(result)
        self.assertEqual(result['text'], "VW")
        self.assertEqual(result['can_id'], hex(DEFAULT_BAP_AUDIO_CAN_ID))
        self.assertEqual(result['op_code'], OP_STATUS)
        self.assertEqual(result['lsg_id'], hex(LSG_AUDIO))
        self.assertEqual(result['fct_id'], hex(FCT_AUDIO_STATION_NAME))

    def test_build_and_reassemble_long_string(self):
        test_text = "ANTIGRAVITY VW BAP TELEMETRY TEST #1234"
        frames = build_bap_long_frames(
            can_id=DEFAULT_BAP_AUDIO_CAN_ID,
            op_code=OP_STATUS,
            lsg_id=LSG_AUDIO,
            fct_id=FCT_AUDIO_STATION_NAME,
            text_string=test_text
        )
        
        # Multi-frame segmented
        self.assertGreater(len(frames), 1)
        
        reassembler = BapReassembler()
        result = None
        for cid, data in frames:
            res = reassembler.process_frame(cid, data)
            if res is not None:
                result = res
                
        self.assertIsNotNone(result)
        self.assertEqual(result['text'], test_text)
        self.assertEqual(result['can_id'], hex(DEFAULT_BAP_AUDIO_CAN_ID))
        self.assertEqual(result['op_code'], OP_STATUS)

    def test_cluster_length_limit(self):
        # Clusters usually display up to 60 characters
        overlong_text = "A" * 100
        frames = build_bap_long_frames(text_string=overlong_text)
        reassembler = BapReassembler()
        result = None
        for cid, data in frames:
            res = reassembler.process_frame(cid, data)
            if res is not None:
                result = res
        self.assertIsNotNone(result)
        self.assertEqual(len(result['text']), 60)


if __name__ == '__main__':
    unittest.main()
