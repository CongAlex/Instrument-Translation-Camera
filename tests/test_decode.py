import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tapstrap.decode import (FingerAccelSample, ImuSample, SensorConfig, decode_notification,
                             encode_for_test)


class DecodeTests(unittest.TestCase):
    def assertVecAlmostEqual(self, got, want, rel=1e-6):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, delta=max(abs(w) * rel, 1e-12))

    def test_finger_accel_scaling_4g(self):
        cfg = SensorConfig(finger_accel_g=4)
        raw = [128, 0, -128] * 5           # 128 LSB * 7.81 mg = 0.99968 g
        out = decode_notification(encode_for_test([("accl", 12345, raw)]), cfg)
        self.assertTrue(len(out) == 1 and isinstance(out[0], FingerAccelSample))
        s = out[0]
        self.assertEqual(s.device_ms, 12345)
        self.assertVecAlmostEqual(s.index, (0.99968, 0.0, -0.99968))
        self.assertAlmostEqual(s.magnitudes()[0], 0.99968 * 2 ** 0.5, delta=0.99968 * 2 ** 0.5 * 1e-6)

    def test_imu_scaling_and_multiple_messages(self):
        cfg = SensorConfig(imu_gyro_dps=2000, imu_accel_g=16)
        data = encode_for_test([
            ("imu", 100, [1000, -1000, 0, 2048, 0, -2048]),
            ("accl", 101, list(range(15))),
            ("imu", 105, [0] * 6),
        ])
        out = decode_notification(data, cfg)
        self.assertEqual([type(s) for s in out], [ImuSample, FingerAccelSample, ImuSample])
        self.assertVecAlmostEqual(out[0].gyro_dps, (70.0, -70.0, 0.0))
        self.assertVecAlmostEqual(out[0].accel_g, (0.999424, 0.0, -0.999424))
        self.assertEqual(out[1].device_ms, 101)

    def test_zero_padding_and_truncation_stop_cleanly(self):
        cfg = SensorConfig()
        data = encode_for_test([("imu", 7, [1] * 6)]) + b"\x00" * 8
        self.assertEqual(len(decode_notification(data, cfg)), 1)
        truncated = encode_for_test([("accl", 9, [0] * 15)])[:-4]
        self.assertEqual(decode_notification(truncated, cfg), [])

    def test_command_bytes_and_validation(self):
        self.assertEqual(SensorConfig(16, 125, 2).command_bytes, [4, 1, 1])
        with self.assertRaises(ValueError):
            SensorConfig(finger_accel_g=3)


if __name__ == "__main__":
    unittest.main()
