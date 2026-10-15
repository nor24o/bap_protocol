"""
VW Passat B6 (PQ46) Infotainment CAN Simulator (Mock Bus)
Simulates realistic 100 kbps CAN traffic including background baseline,
door events, steering wheel buttons (MFSW), and Android Head Unit BAP screen packets.
"""

import time
import queue
import threading
import can
from typing import Optional, List
from bap_protocol import build_bap_long_frames, DEFAULT_BAP_AUDIO_CAN_ID, OP_STATUS, LSG_AUDIO, FCT_AUDIO_STATION_NAME


class MockVwCanBus(can.BusABC):
    """
    Simulated CAN bus emulating VW Passat B6 100 kbps Infotainment CAN.
    Can be used as a drop-in replacement for can.interface.Bus when no physical hardware is plugged in.
    """
    def __init__(self, channel='MOCK_VW_PQ46', bitrate=100000, **kwargs):
        super().__init__(channel=channel, **kwargs)
        self.channel_info = f"VW PQ46 Mock Bus ({channel}) @ {bitrate} bps"
        self._rx_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._stop_event = threading.Event()
        self._active_action: Optional[str] = None
        self._action_lock = threading.Lock()
        
        # Generator thread
        self._thread = threading.Thread(target=self._bus_loop, daemon=True)
        self._thread.start()

    def set_action(self, action_name: Optional[str]):
        """
        Set active simulated user action:
        - None or 'quiet': Normal quiet baseline
        - 'driver_door': Simulates opening and closing the driver door
        - 'steering_buttons': Simulates steering wheel button presses
        - 'android_radio_bap': Simulates Android radio changing stations
        """
        with self._action_lock:
            self._active_action = action_name

    def _bus_loop(self):
        last_100ms = 0.0
        last_radio_bap = 0.0
        last_1000ms = 0.0
        
        door_state = 0
        radio_station_idx = 0
        stations = ["VW HIT RADIO", "ROCK 104.5", "BAP PASSAT B6", "BLUETOOTH AUDIO"]
        button_idx = 0
        button_codes = [0x02, 0x03, 0x06, 0x07]  # Vol+, Vol-, Next, Prev

        while not self._stop_event.is_set():
            now = time.time()
            with self._action_lock:
                action = self._active_action

            # 100ms Periodic Background Frames
            if now - last_100ms >= 0.10:
                last_100ms = now
                
                # 0x35B: Speed / Gateway status
                self._push_msg(0x35B, bytes([0x00, 0x12, 0x34, 0x00, 0x56, 0x78, 0x00, 0x90]))
                
                # 0x635: Illumination / cluster state
                self._push_msg(0x635, bytes([0x60, 0x10, 0x00, 0x00]))
                
                # 0x470: Door status
                if action == 'driver_door':
                    # Toggle door open/closed
                    door_state = 1 if (int(now * 2) % 2 == 0) else 0
                    self._push_msg(0x470, bytes([door_state, 0x00, 0x00, 0x00]))
                else:
                    self._push_msg(0x470, bytes([0x00, 0x00, 0x00, 0x00]))

                # 0x5C1: Steering Wheel Buttons (MFSW)
                if action == 'steering_buttons':
                    # Send button press pulses
                    code = button_codes[button_idx % len(button_codes)]
                    button_idx += 1
                    self._push_msg(0x5C1, bytes([code, 0x01]))
                else:
                    self._push_msg(0x5C1, bytes([0x00, 0x00]))

            # 1000ms Periodic Frames
            if now - last_1000ms >= 1.0:
                last_1000ms = now
                # 0x271: Clock broadcast
                self._push_msg(0x271, bytes([0x18, 0x30, 0x15, 0x10, 0x26]))

            # Radio BAP screen broadcast every 150ms
            if now - last_radio_bap >= 0.15:
                last_radio_bap = now
                if action == 'android_radio_bap':
                    current_station = stations[radio_station_idx % len(stations)]
                    radio_station_idx += 1
                else:
                    current_station = "FM 101.5 MHZ"
                    
                bap_frames = build_bap_long_frames(
                    can_id=DEFAULT_BAP_AUDIO_CAN_ID,
                    op_code=OP_STATUS,
                    lsg_id=LSG_AUDIO,
                    fct_id=FCT_AUDIO_STATION_NAME,
                    text_string=current_station
                )
                for cid, data in bap_frames:
                    self._push_msg(cid, data)
                    time.sleep(0.003)

            time.sleep(0.01)

    def _push_msg(self, can_id: int, data: bytes):
        msg = can.Message(
            arbitration_id=can_id,
            data=data,
            is_extended_id=False,
            timestamp=time.time()
        )
        try:
            self._rx_queue.put_nowait(msg)
        except queue.Full:
            pass

    def recv(self, timeout: Optional[float] = None) -> Optional[can.Message]:
        try:
            return self._rx_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, msg: can.Message, timeout: Optional[float] = None) -> None:
        """Receive sent messages (e.g. from injector)"""
        # When an injector sends a message, loop it back or log it
        pass

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
