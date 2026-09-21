"""
Damiao motor drivers for serial bridge and SocketCAN transports.
"""

from __future__ import annotations

from enum import IntEnum
from struct import pack, unpack
import threading
import time
from typing import Dict, Iterable, Optional

import numpy as np
import serial

try:
    import can
except Exception:  # pragma: no cover - optional dependency at runtime
    can = None


class Motor_Status(IntEnum):
    DISABLED = 0x0
    ENABLED = 0x1
    OVERVOLTAGE = 0x8
    UNDERVOLTAGE = 0x9
    OVERCURRENT = 0xA
    MOS_OVERTEMP = 0xB
    COIL_OVERTEMP = 0xC
    COMM_LOST = 0xD
    OVERLOAD = 0xE


class DM_Motor_Type(IntEnum):
    DM4310 = 0
    DM4310_48V = 1
    DM4340 = 2
    DM4340_48V = 3
    DM6006 = 4
    DM8006 = 5
    DM8009 = 6
    DM10010L = 7
    DM10010 = 8
    DMH3510 = 9
    DMH6215 = 10
    DMG6220 = 11


class DM_variable(IntEnum):
    UV_Value = 0
    KT_Value = 1
    OT_Value = 2
    OC_Value = 3
    ACC = 4
    DEC = 5
    MAX_SPD = 6
    MST_ID = 7
    ESC_ID = 8
    TIMEOUT = 9
    CTRL_MODE = 10
    Damp = 11
    Inertia = 12
    hw_ver = 13
    sw_ver = 14
    SN = 15
    NPP = 16
    Rs = 17
    LS = 18
    Flux = 19
    Gr = 20
    PMAX = 21
    VMAX = 22
    TMAX = 23
    I_BW = 24
    KP_ASR = 25
    KI_ASR = 26
    KP_APR = 27
    KI_APR = 28
    OV_Value = 29
    GREF = 30
    Deta = 31
    V_BW = 32
    IQ_c1 = 33
    VL_c1 = 34
    can_br = 35
    sub_ver = 36
    u_off = 50
    v_off = 51
    k1 = 52
    k2 = 53
    m_off = 54
    dir = 55
    p_m = 80
    xout = 81


class Control_Type(IntEnum):
    MIT = 1
    POS_VEL = 2
    VEL = 3
    Torque_Pos = 4


LIMIT_PARAM = [
    [12.5, 30, 10],
    [12.5, 50, 10],
    [12.5, 8, 28],
    [12.5, 10, 28],
    [12.5, 45, 20],
    [12.5, 45, 40],
    [12.5, 45, 54],
    [12.5, 25, 200],
    [12.5, 20, 200],
    [12.5, 280, 1],
    [12.5, 45, 10],
    [12.5, 45, 10],
]


def _clamp_float_to_uint(value: float, minimum: float, maximum: float, bits: int) -> np.uint16:
    value = min(max(value, minimum), maximum)
    span = maximum - minimum
    return np.uint16(((value - minimum) / span) * ((1 << bits) - 1))


def _uint_to_float(value: np.uint16, minimum: float, maximum: float, bits: int) -> np.float32:
    span = maximum - minimum
    return np.float32((float(value) / ((1 << bits) - 1)) * span + minimum)


def _float_to_uint8s(value: float) -> tuple[int, int, int, int]:
    return unpack("4B", pack("f", value))


def _data_to_uint8s(value: int) -> tuple[int, int, int, int]:
    return unpack("4B", pack("I", value))


def _uint8s_to_uint32(byte1: int, byte2: int, byte3: int, byte4: int) -> int:
    return unpack("<I", pack("<4B", byte1, byte2, byte3, byte4))[0]


def _uint8s_to_float(byte1: int, byte2: int, byte3: int, byte4: int) -> float:
    return unpack("<f", pack("<4B", byte1, byte2, byte3, byte4))[0]


def _rid_is_uint32(rid: int) -> bool:
    return (7 <= rid <= 10) or (13 <= rid <= 16) or (35 <= rid <= 36)


class Motor:
    def __init__(self, MotorType: DM_Motor_Type, SlaveID: int, MasterID: int = 0):
        self.state_q = 0.0
        self.state_dq = 0.0
        self.state_tau = 0.0
        self.state_t_mos = 0.0
        self.state_t_rotor = 0.0
        self.motor_status = Motor_Status.DISABLED
        self.motor_id = 0
        self.SlaveID = SlaveID
        self.MasterID = MasterID
        self.MotorType = MotorType
        self.isEnable = False
        self.NowControlMode = Control_Type.MIT
        self.temp_param_dict: Dict[int, float | int] = {}
        self.last_status_frame: Dict[str, object] | None = None

    def recv_data(
        self,
        q: float,
        dq: float,
        tau: float,
        t_mos: float = 0,
        t_rotor: float = 0,
        motor_id: int = 0,
        status: int = 0,
    ):
        self.state_q = q
        self.state_dq = dq
        self.state_tau = tau
        self.state_t_mos = t_mos
        self.state_t_rotor = t_rotor
        self.motor_id = motor_id
        try:
            self.motor_status = Motor_Status(status)
        except ValueError:
            self.motor_status = status
        self.isEnable = self.motor_status == Motor_Status.ENABLED

    def getPosition(self):
        return self.state_q

    def getVelocity(self):
        return self.state_dq

    def getTorque(self):
        return self.state_tau

    def getT_MOS(self):
        return self.state_t_mos

    def getT_Rotor(self):
        return self.state_t_rotor

    def getMotorStatus(self):
        return self.motor_status

    def isHealthy(self):
        return self.motor_status in [Motor_Status.DISABLED, Motor_Status.ENABLED]

    def hasError(self):
        return self.motor_status in [
            Motor_Status.OVERVOLTAGE,
            Motor_Status.UNDERVOLTAGE,
            Motor_Status.OVERCURRENT,
            Motor_Status.MOS_OVERTEMP,
            Motor_Status.COIL_OVERTEMP,
            Motor_Status.COMM_LOST,
            Motor_Status.OVERLOAD,
        ]

    def snapshot(self) -> Dict[str, float | int | str | bool]:
        status = self.getMotorStatus()
        status_code = int(status)
        return {
            "slave_id": self.SlaveID,
            "master_id": self.MasterID,
            "motor_type": self.MotorType.name,
            "position": float(self.state_q),
            "velocity": float(self.state_dq),
            "torque": float(self.state_tau),
            "t_mos": float(self.state_t_mos),
            "t_rotor": float(self.state_t_rotor),
            "status": status.name if isinstance(status, Motor_Status) else f"UNKNOWN_0x{status_code:X}",
            "status_code": status_code,
            "is_enabled": self.isEnable,
            "is_healthy": self.isHealthy(),
            "has_error": self.hasError(),
            "params": dict(self.temp_param_dict),
            "last_status_frame": self.last_status_frame,
        }


class _BaseDamiaoDriver:
    def __init__(self):
        self.motors_map: Dict[int, Motor] = {}
        self.data_save = bytes()
        self._lock = threading.RLock()

    def addMotor(self, motor: Motor) -> bool:
        self.motors_map[motor.SlaveID] = motor
        if motor.MasterID != 0:
            self.motors_map[motor.MasterID] = motor
        return True

    def removeMotor(self, motor: Motor):
        for key in [motor.SlaveID, motor.MasterID]:
            if key in self.motors_map and self.motors_map[key] is motor:
                del self.motors_map[key]

    def ensure_motor(self, motor: Motor):
        slave_owner = self.motors_map.get(motor.SlaveID)
        master_owner = self.motors_map.get(motor.MasterID) if motor.MasterID else motor
        if slave_owner is not motor or master_owner is not motor:
            self.addMotor(motor)

    def _build_mit_buffer(self, motor: Motor, kp: float, kd: float, q: float, dq: float, tau: float):
        q_max, dq_max, tau_max = LIMIT_PARAM[motor.MotorType]
        kp_uint = _clamp_float_to_uint(kp, 0, 500, 12)
        kd_uint = _clamp_float_to_uint(kd, 0, 5, 12)
        q_uint = _clamp_float_to_uint(q, -q_max, q_max, 16)
        dq_uint = _clamp_float_to_uint(dq, -dq_max, dq_max, 12)
        tau_uint = _clamp_float_to_uint(tau, -tau_max, tau_max, 12)

        data_buf = np.array([0x00] * 8, np.uint8)
        data_buf[0] = (q_uint >> 8) & 0xFF
        data_buf[1] = q_uint & 0xFF
        data_buf[2] = dq_uint >> 4
        data_buf[3] = ((dq_uint & 0xF) << 4) | ((kp_uint >> 8) & 0xF)
        data_buf[4] = kp_uint & 0xFF
        data_buf[5] = kd_uint >> 4
        data_buf[6] = ((kd_uint & 0xF) << 4) | ((tau_uint >> 8) & 0xF)
        data_buf[7] = tau_uint & 0xFF
        return data_buf

    def _process_status_payload(self, data: Iterable[int], can_id: int):
        payload = list(data)
        if len(payload) < 8:
            return

        target_key = can_id
        if can_id == 0:
            target_key = payload[0] & 0x0F
        if target_key not in self.motors_map:
            return

        motor = self.motors_map[target_key]
        # Damiao feedback is commonly documented as ERR/status in D0[7:4] and
        # ESC_ID in D0[3:0]. Our left-arm factory profile intentionally uses
        # ESC_ID 0x10 for L-J8, which does not fit in a 4-bit ID field. In that
        # case the observed D0 is the full 8-bit ESC_ID (0x10), and interpreting
        # its high nibble as status falsely reports ENABLED. When the full byte
        # matches the configured slave ID, prefer the known ID and leave status
        # as DISABLED for the static feedback frame.
        if payload[0] == motor.SlaveID and motor.SlaveID > 0x0F:
            motor_id = motor.SlaveID
            status = int(Motor_Status.DISABLED)
        else:
            motor_id = payload[0] & 0x0F
            status = (payload[0] >> 4) & 0x0F
        motor.last_status_frame = {
            "timestamp": time.time(),
            "can_id": int(can_id),
            "data_hex": "".join(f"{byte:02X}" for byte in payload[:8]),
            "data": [int(byte) for byte in payload[:8]],
        }
        q_uint = np.uint16((np.uint16(payload[1]) << 8) | payload[2])
        dq_uint = np.uint16((np.uint16(payload[3]) << 4) | (payload[4] >> 4))
        tau_uint = np.uint16(((payload[4] & 0xF) << 8) | payload[5])
        q_max, dq_max, tau_max = LIMIT_PARAM[motor.MotorType]
        recv_q = _uint_to_float(q_uint, -q_max, q_max, 16)
        recv_dq = _uint_to_float(dq_uint, -dq_max, dq_max, 12)
        recv_tau = _uint_to_float(tau_uint, -tau_max, tau_max, 12)
        motor.recv_data(recv_q, recv_dq, recv_tau, float(payload[6]), float(payload[7]), motor_id, status)

    def _looks_like_param_payload(self, data: Iterable[int]) -> bool:
        payload = list(data)
        if len(payload) < 8 or payload[2] not in (0x33, 0x55):
            return False
        slave_id = (payload[1] << 8) | payload[0]
        return slave_id in self.motors_map

    def _process_param_payload(self, data: Iterable[int], can_id: int):
        payload = list(data)
        if len(payload) < 8 or payload[2] not in (0x33, 0x55):
            return

        master_id = can_id
        slave_id = (payload[1] << 8) | payload[0]
        if master_id == 0x00:
            master_id = slave_id
        if master_id not in self.motors_map and slave_id in self.motors_map:
            master_id = slave_id
        if master_id not in self.motors_map:
            return

        rid = payload[3]
        if _rid_is_uint32(rid):
            value = _uint8s_to_uint32(payload[4], payload[5], payload[6], payload[7])
        else:
            value = _uint8s_to_float(payload[4], payload[5], payload[6], payload[7])
        self.motors_map[master_id].temp_param_dict[rid] = value


class DamiaoMotorDriver(_BaseDamiaoDriver):
    def __init__(self, serial_port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        super().__init__()
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.arm_scan_param_read_timeout = 0.25

    def connect(self) -> bool:
        try:
            self.serial_conn = serial.Serial(self.serial_port, self.baudrate, timeout=0.1)
            return True
        except Exception:
            self.serial_conn = None
            return False

    def disconnect(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        self.serial_conn = None

    def __send_data(self, motor_id: int, data: np.ndarray):
        if not self.serial_conn:
            raise RuntimeError("serial not connected")
        frame = np.array(
            [
                0x55,
                0xAA,
                0x1E,
                0x03,
                0x01,
                0x00,
                0x00,
                0x00,
                0x0A,
                0x00,
                0x00,
                0x00,
                0x00,
                motor_id & 0xFF,
                (motor_id >> 8) & 0xFF,
                0x00,
                0x08,
                0x00,
                0x00,
            ]
            + list(data)
            + [0x00],
            np.uint8,
        )
        self.serial_conn.write(bytes(frame))

    def __control_cmd(self, motor: Motor, cmd: np.uint8):
        data_buf = np.array([0xFF] * 7 + [cmd], np.uint8)
        self.__send_data(motor.SlaveID, data_buf)

    def recv(self):
        if not self.serial_conn:
            return
        with self._lock:
            data_recv = b"".join([self.data_save, self.serial_conn.read_all()])
            packets = self._extract_packets(data_recv)
            for packet in packets:
                payload = packet[7:15]
                can_id = (packet[6] << 24) | (packet[5] << 16) | (packet[4] << 8) | packet[3]
                cmd = packet[1]
                if cmd == 0x11:
                    if self._looks_like_param_payload(payload):
                        self._process_param_payload(payload, can_id)
                    else:
                        self._process_status_payload(payload, can_id)

    def _extract_packets(self, data: bytes):
        frames = []
        header = 0xAA
        tail = 0x55
        frame_length = 16
        i = 0
        remainder_pos = 0
        while i <= len(data) - frame_length:
            if data[i] == header and data[i + frame_length - 1] == tail:
                frames.append(data[i : i + frame_length])
                i += frame_length
                remainder_pos = i
            else:
                i += 1
        self.data_save = data[remainder_pos:]
        return frames

    def _read_param_frame(self, motor: Motor, rid: DM_variable):
        data_buf = np.array(
            [motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0x33, np.uint8(rid), 0, 0, 0, 0],
            np.uint8,
        )
        self.__send_data(0x7FF, data_buf)

    def _write_param_frame(self, motor: Motor, rid: DM_variable, data: float | int):
        payload = np.array(
            [motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0x55, np.uint8(rid), 0, 0, 0, 0],
            np.uint8,
        )
        payload[4:8] = _data_to_uint8s(int(data)) if _rid_is_uint32(int(rid)) else _float_to_uint8s(float(data))
        self.__send_data(0x7FF, payload)

    def enable(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__control_cmd(motor, np.uint8(0xFC))
            time.sleep(0.1)
            self.recv()
            return True

    def enable_fast(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__control_cmd(motor, np.uint8(0xFC))
            return True

    def disable(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__control_cmd(motor, np.uint8(0xFD))
            time.sleep(0.02)
            self.recv()
            motor.isEnable = False
            return True

    def disable_fast(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__control_cmd(motor, np.uint8(0xFD))
            motor.isEnable = False
            return True

    def set_zero_position(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__control_cmd(motor, np.uint8(0xFE))
            time.sleep(0.1)
            self.recv()
            return True

    def controlMIT(self, motor: Motor, kp: float, kd: float, q: float, dq: float, tau: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__send_data(motor.SlaveID, self._build_mit_buffer(motor, kp, kd, q, dq, tau))
            self.recv()
            return True

    def controlMIT_fast(self, motor: Motor, kp: float, kd: float, q: float, dq: float, tau: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.__send_data(motor.SlaveID, self._build_mit_buffer(motor, kp, kd, q, dq, tau))
            return True

    def control_Vel(self, motor: Motor, vel_desired: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            data_buf = np.array([0x00] * 8, np.uint8)
            data_buf[0:4] = _float_to_uint8s(vel_desired)
            self.__send_data(0x200 + motor.SlaveID, data_buf)
            self.recv()
            return True

    def control_Pos_Vel(self, motor: Motor, p_desired: float, v_desired: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            data_buf = np.array([0x00] * 8, np.uint8)
            data_buf[0:4] = _float_to_uint8s(p_desired)
            data_buf[4:8] = _float_to_uint8s(v_desired)
            self.__send_data(0x100 + motor.SlaveID, data_buf)
            self.recv()
            return True

    def refresh_motor_status(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            before = motor.last_status_frame
            data_buf = np.array([motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0xCC, 0, 0, 0, 0, 0], np.uint8)
            self.__send_data(0x7FF, data_buf)
            time.sleep(0.03)
            self.recv()
            return motor.last_status_frame is not None and motor.last_status_frame is not before

    def read_motor_param(self, motor: Motor, rid: DM_variable, timeout: float | None = None):
        with self._lock:
            self.ensure_motor(motor)
            self._read_param_frame(motor, rid)
            effective_timeout = 1.0 if timeout is None else max(0.01, float(timeout))
            wait_slices = max(1, int(round(effective_timeout / 0.05)))
            for _ in range(wait_slices):
                time.sleep(0.05)
                self.recv()
                if int(rid) in motor.temp_param_dict:
                    return motor.temp_param_dict[int(rid)]
            return None

    def change_motor_param(self, motor: Motor, rid: DM_variable, data: float | int) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            original_slave_id = motor.SlaveID
            target_slave_id = int(data) if int(rid) == int(DM_variable.ESC_ID) else None
            if target_slave_id is not None and target_slave_id != original_slave_id:
                self.motors_map[target_slave_id] = motor
            self._write_param_frame(motor, rid, data)
            for _ in range(20):
                time.sleep(0.05)
                self.recv()
                if int(rid) in motor.temp_param_dict:
                    value = motor.temp_param_dict[int(rid)]
                    if _rid_is_uint32(int(rid)):
                        matched = int(value) == int(data)
                    else:
                        matched = abs(float(value) - float(data)) < 0.1
                    if matched and target_slave_id is not None:
                        if self.motors_map.get(original_slave_id) is motor:
                            del self.motors_map[original_slave_id]
                        motor.SlaveID = target_slave_id
                        self.motors_map[target_slave_id] = motor
                    return matched
            if target_slave_id is not None and target_slave_id != original_slave_id:
                if self.motors_map.get(target_slave_id) is motor:
                    del self.motors_map[target_slave_id]
            return False

    def save_motor_param(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.disable(motor)
            data_buf = np.array([motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0xAA, 0, 0, 0, 0, 0], np.uint8)
            self.__send_data(0x7FF, data_buf)
            time.sleep(0.05)
            self.recv()
            return True

    def switchControlMode(self, motor: Motor, control_mode: Control_Type) -> bool:
        return self.change_motor_param(motor, DM_variable.CTRL_MODE, int(control_mode))

    def read_params(self, motor: Motor, rids: Iterable[DM_variable], timeout: float | None = None):
        params = {}
        for rid in rids:
            params[rid.name] = self.read_motor_param(motor, rid, timeout=timeout)
        return params

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


class DamiaoSocketCANDriver(_BaseDamiaoDriver):
    """SocketCAN transport for Damiao motors, in classic CAN or CAN-FD.

    FD follows what openarm_can does on the wire (1.4.0,
    src/openarm/damiao_motor/dm_motor_device.cpp `create_canfd_frame`): an FD frame
    carrying the same 8-byte Damiao payload, with the bit rate switch set so the data
    phase runs at the faster rate. A socket opened for FD still receives classic
    frames, so a mixed bus stays readable.
    """

    def __init__(self, channel: str = "can0", bitrate: int = 1000000, fd: bool = False):
        super().__init__()
        self.channel = channel
        self.bitrate = bitrate
        self.fd = bool(fd)
        self.bus = None
        self.param_read_timeout = 1.0
        self.fast_param_read_timeout = 0.15
        self.arm_scan_param_read_timeout = 0.25
        self.param_write_timeout = 0.5

    def connect(self) -> bool:
        if can is None:
            return False
        try:
            # The interface itself carries the timing; `ip link` has already applied
            # it (see WorkstationService._can_configure_command). `fd=True` only asks
            # the socket for CAN_RAW_FD_FRAMES, as the official CANSocket does.
            self.bus = can.Bus(
                interface="socketcan",
                channel=self.channel,
                bitrate=self.bitrate,
                fd=self.fd,
            )
            return True
        except Exception:
            self.bus = None
            return False

    def disconnect(self):
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass
        self.bus = None

    def _send_frame(self, arbitration_id: int, data: Iterable[int]):
        if self.bus is None:
            raise RuntimeError("socketcan not connected")
        message = can.Message(
            arbitration_id=arbitration_id,
            data=list(data),
            is_extended_id=False,
            is_fd=self.fd,
            # CANFD_BRS: the data phase runs at dbitrate. Without it an FD frame is
            # sent at the arbitration rate and the point of switching is lost.
            bitrate_switch=self.fd,
        )
        self.bus.send(message)

    def _drain(self, timeout: float = 0.3):
        if self.bus is None:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.bus.recv(timeout=max(0.0, deadline - time.time()))
            if msg is None:
                continue
            data = list(msg.data)
            if len(data) < 8:
                continue
            if self._looks_like_param_payload(data):
                self._process_param_payload(data, msg.arbitration_id)
            else:
                self._process_status_payload(data, msg.arbitration_id)

    def enable(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, [0xFF] * 7 + [0xFC])
            self._drain(0.1)
            return True

    def enable_fast(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, [0xFF] * 7 + [0xFC])
            return True

    def disable(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, [0xFF] * 7 + [0xFD])
            self._drain(0.05)
            motor.isEnable = False
            return True

    def disable_fast(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, [0xFF] * 7 + [0xFD])
            motor.isEnable = False
            return True

    def set_zero_position(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, [0xFF] * 7 + [0xFE])
            self._drain(0.1)
            return True

    def refresh_motor_status(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            before = motor.last_status_frame
            self._send_frame(0x7FF, [motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0xCC, 0, 0, 0, 0, 0])
            self._drain(0.2)
            return motor.last_status_frame is not None and motor.last_status_frame is not before

    def read_motor_param(self, motor: Motor, rid: DM_variable, timeout: float | None = None):
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(0x7FF, [motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0x33, int(rid), 0, 0, 0, 0])
            effective_timeout = self.param_read_timeout if timeout is None else max(0.01, float(timeout))
            deadline = time.time() + effective_timeout
            while time.time() < deadline:
                self._drain(0.05)
                if int(rid) in motor.temp_param_dict:
                    return motor.temp_param_dict[int(rid)]
            return None

    def change_motor_param(self, motor: Motor, rid: DM_variable, data: float | int) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            original_slave_id = motor.SlaveID
            original_master_id = motor.MasterID
            target_slave_id = int(data) if int(rid) == int(DM_variable.ESC_ID) else None
            target_master_id = int(data) if int(rid) == int(DM_variable.MST_ID) else None
            if target_slave_id is not None and target_slave_id != original_slave_id:
                self.motors_map[target_slave_id] = motor
            if target_master_id and target_master_id != original_master_id:
                self.motors_map[target_master_id] = motor
            payload = [motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0x55, int(rid), 0, 0, 0, 0]
            payload[4:8] = list(_data_to_uint8s(int(data)) if _rid_is_uint32(int(rid)) else _float_to_uint8s(float(data)))
            self._send_frame(0x7FF, payload)
            deadline = time.time() + self.param_write_timeout
            while time.time() < deadline:
                self._drain(0.05)
                if int(rid) in motor.temp_param_dict:
                    value = motor.temp_param_dict[int(rid)]
                    if _rid_is_uint32(int(rid)):
                        matched = int(value) == int(data)
                    else:
                        matched = abs(float(value) - float(data)) < 0.1
                    if matched and target_master_id is not None:
                        if original_master_id and original_master_id != target_master_id:
                            if self.motors_map.get(original_master_id) is motor:
                                del self.motors_map[original_master_id]
                        motor.MasterID = target_master_id
                        self.motors_map[target_master_id] = motor
                    if matched and target_slave_id is not None:
                        if self.motors_map.get(original_slave_id) is motor:
                            del self.motors_map[original_slave_id]
                        motor.SlaveID = target_slave_id
                        self.motors_map[target_slave_id] = motor
                    return matched
            if target_slave_id is not None and target_slave_id != original_slave_id:
                if self.motors_map.get(target_slave_id) is motor:
                    del self.motors_map[target_slave_id]
            if target_master_id and target_master_id != original_master_id:
                if self.motors_map.get(target_master_id) is motor:
                    del self.motors_map[target_master_id]
            return False

    def save_motor_param(self, motor: Motor) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self.disable(motor)
            self._send_frame(0x7FF, [motor.SlaveID & 0xFF, (motor.SlaveID >> 8) & 0xFF, 0xAA, 0, 0, 0, 0, 0])
            self._drain(0.1)
            return True

    def controlMIT(self, motor: Motor, kp: float, kd: float, q: float, dq: float, tau: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, self._build_mit_buffer(motor, kp, kd, q, dq, tau))
            self._drain(0.1)
            return True

    def controlMIT_fast(self, motor: Motor, kp: float, kd: float, q: float, dq: float, tau: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            self._send_frame(motor.SlaveID, self._build_mit_buffer(motor, kp, kd, q, dq, tau))
            return True

    def control_Vel(self, motor: Motor, vel_desired: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            payload = [0x00] * 8
            payload[0:4] = list(_float_to_uint8s(vel_desired))
            self._send_frame(0x200 + motor.SlaveID, payload)
            self._drain(0.1)
            return True

    def control_Pos_Vel(self, motor: Motor, p_desired: float, v_desired: float) -> bool:
        with self._lock:
            self.ensure_motor(motor)
            payload = [0x00] * 8
            payload[0:4] = list(_float_to_uint8s(p_desired))
            payload[4:8] = list(_float_to_uint8s(v_desired))
            self._send_frame(0x100 + motor.SlaveID, payload)
            self._drain(0.1)
            return True

    def switchControlMode(self, motor: Motor, control_mode: Control_Type) -> bool:
        return self.change_motor_param(motor, DM_variable.CTRL_MODE, int(control_mode))

    def read_params(self, motor: Motor, rids: Iterable[DM_variable], timeout: float | None = None):
        params = {}
        for rid in rids:
            params[rid.name] = self.read_motor_param(motor, rid, timeout=timeout)
        return params
