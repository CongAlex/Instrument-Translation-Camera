"""Pure-Python decoding for Tap Strap raw-sensor packets.

No Bluetooth or SDK imports here, so this module can be unit-tested and reused
offline (e.g. replaying logged bytes).

Wire format (from Tap's raw sensors spec / tap-python-sdk ``parsers.raw_data_msg``)
---------------------------------------------------------------------------------
A BLE notification on the NUS TX characteristic holds one or more messages::

    [msg_type: 1 bit][timestamp_ms: 31 bits][payload]

* The 32-bit header is little-endian. If its top bit is set the message is a
  finger-accelerometer message, otherwise it is a thumb-IMU message.
* IMU payload:   6 x int16 LE -> gyro x,y,z then accel x,y,z   (12 bytes)
* Accel payload: 15 x int16 LE -> thumb, index, middle, ring, pinky (x,y,z each)
* A zero header (or end of buffer) terminates the list.

Values are raw LSB counts; multiply by the scale factor for the selected range.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Tuple, Union

FINGERS = ("thumb", "index", "middle", "ring", "pinky")

# Range -> (command byte, scale). Scale is mg/LSB for accel, mdps/LSB for gyro.
FINGER_ACCEL_RANGES = {2: (1, 3.91), 4: (2, 7.81), 8: (3, 15.62), 16: (4, 31.25)}
IMU_GYRO_RANGES = {125: (1, 4.375), 250: (2, 8.75), 500: (3, 17.5), 1000: (4, 35.0), 2000: (5, 70.0)}
IMU_ACCEL_RANGES = {2: (1, 0.061), 4: (2, 0.122), 8: (3, 0.244), 16: (4, 0.488)}

_ACCEL_FLAG = 1 << 31
Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class SensorConfig:
    """Selected dynamic ranges. Units: g for accelerometers, deg/s for gyro."""

    finger_accel_g: int = 4
    imu_gyro_dps: int = 500
    imu_accel_g: int = 4

    def __post_init__(self):
        if self.finger_accel_g not in FINGER_ACCEL_RANGES:
            raise ValueError(f"finger_accel_g must be one of {sorted(FINGER_ACCEL_RANGES)}")
        if self.imu_gyro_dps not in IMU_GYRO_RANGES:
            raise ValueError(f"imu_gyro_dps must be one of {sorted(IMU_GYRO_RANGES)}")
        if self.imu_accel_g not in IMU_ACCEL_RANGES:
            raise ValueError(f"imu_accel_g must be one of {sorted(IMU_ACCEL_RANGES)}")

    @property
    def command_bytes(self) -> List[int]:
        """Sensitivity bytes sent after the raw-mode opcode: [finger, gyro, imu_accel]."""
        return [
            FINGER_ACCEL_RANGES[self.finger_accel_g][0],
            IMU_GYRO_RANGES[self.imu_gyro_dps][0],
            IMU_ACCEL_RANGES[self.imu_accel_g][0],
        ]

    @property
    def finger_g_per_lsb(self) -> float:
        return FINGER_ACCEL_RANGES[self.finger_accel_g][1] / 1000.0

    @property
    def gyro_dps_per_lsb(self) -> float:
        return IMU_GYRO_RANGES[self.imu_gyro_dps][1] / 1000.0

    @property
    def imu_g_per_lsb(self) -> float:
        return IMU_ACCEL_RANGES[self.imu_accel_g][1] / 1000.0


@dataclass(frozen=True)
class FingerAccelSample:
    """One ~200 Hz sample from the five finger accelerometers, in g."""

    device_ms: int
    thumb: Vec3
    index: Vec3
    middle: Vec3
    ring: Vec3
    pinky: Vec3

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in FINGERS}

    def magnitudes(self) -> Tuple[float, ...]:
        """|a| per finger in g (≈1.0 at rest because of gravity)."""
        return tuple((x * x + y * y + z * z) ** 0.5 for (x, y, z) in (getattr(self, f) for f in FINGERS))


@dataclass(frozen=True)
class ImuSample:
    """One ~208 Hz sample from the thumb IMU (Tap Strap 2 only)."""

    device_ms: int
    gyro_dps: Vec3
    accel_g: Vec3


Sample = Union[FingerAccelSample, ImuSample]


def _vec(vals, scale) -> Vec3:
    return (vals[0] * scale, vals[1] * scale, vals[2] * scale)


def decode_notification(data: bytes, config: SensorConfig) -> List[Sample]:
    """Decode one raw NUS notification into samples in physical units."""
    out: List[Sample] = []
    ptr, n = 0, len(data)
    while ptr + 4 <= n:
        (header,) = struct.unpack_from("<I", data, ptr)
        if header == 0:
            break
        ptr += 4
        if header & _ACCEL_FLAG:
            if ptr + 30 > n:
                break  # truncated packet
            raw = struct.unpack_from("<15h", data, ptr)
            ptr += 30
            s = config.finger_g_per_lsb
            out.append(FingerAccelSample(
                header & ~_ACCEL_FLAG,
                *(_vec(raw[i:i + 3], s) for i in range(0, 15, 3)),
            ))
        else:
            if ptr + 12 > n:
                break
            raw = struct.unpack_from("<6h", data, ptr)
            ptr += 12
            out.append(ImuSample(header, _vec(raw[0:3], config.gyro_dps_per_lsb),
                                 _vec(raw[3:6], config.imu_g_per_lsb)))
    return out


def encode_for_test(samples: List[Tuple[str, int, List[int]]]) -> bytes:
    """Build a notification from (kind, device_ms, raw_lsb_values). Used by tests/demo."""
    buf = bytearray()
    for kind, ts, vals in samples:
        if kind == "accl":
            buf += struct.pack("<I15h", ts | _ACCEL_FLAG, *vals)
        else:
            buf += struct.pack("<I6h", ts, *vals)
    return bytes(buf)
