import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import m0_analyze
from m0_record import build_schedule
from tapstrap import FINGERS

ROOT = Path(__file__).resolve().parent.parent
T0 = 1000.0


def write_synthetic(prefix, crosstalk=0.3, seed=0):
    rng = np.random.default_rng(seed)
    sched = [s for s in build_schedule(taps=6, holds=3, idle=3, period=0.5) if s[1] != "say"]
    n = int((sched[-1][0] + 1.0) * 200)
    acc = rng.normal(0, 0.01, (n, 5, 3)) + np.array([0, 0, -1.0])
    for off, kind, f in sched:
        if kind not in ("tap", "lift"):
            continue
        k = int(round((off + 0.08) / 0.005))
        size = 1.5 if kind == "tap" else 0.5
        i = FINGERS.index(f)
        acc[k, i, 2] += size
        for j in (i - 1, i + 1):
            if 0 <= j < 5:
                acc[k, j, 2] += size * crosstalk
    with open(f"{prefix}_fingers.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host_time_s", "device_ms"] + [f"{f}_{a}_g" for f in FINGERS for a in "xyz"])
        for k in range(n):
            # Host time is shared by each pair of samples (one BLE notification), 30 ms after the later one.
            w.writerow([f"{T0 + (k | 1) * 0.005 + 0.03:.4f}", 100000 + 5 * k] + [f"{v:.4f}" for v in acc[k].ravel()])
    with open(f"{prefix}_cues.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host_time_s", "kind", "finger"])
        for off, kind, f in sched:
            w.writerow([f"{T0 + off:.4f}", kind, f])


class M0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.prefix = str(Path(cls.tmp.name) / "syn")
        write_synthetic(cls.prefix)
        cls.result = m0_analyze.analyze(cls.prefix)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_detects_synthetic_taps(self):
        for f, d in self.result["detection"].items():
            self.assertGreaterEqual(d["recall"], 0.95, f)
            self.assertGreaterEqual(d["precision"], 0.9, f)

    def test_crosstalk_matrix(self):
        xt = self.result["crosstalk"]
        for i in range(5):
            self.assertAlmostEqual(xt[i][i], 1.0, delta=0.01)
            for j in (i - 1, i + 1):
                if 0 <= j < 5:
                    self.assertAlmostEqual(xt[i][j], 0.3, delta=0.1)

    def test_stream_stats(self):
        s = self.result["stream"]
        self.assertAlmostEqual(s["rate_hz"], 200, delta=1)
        self.assertEqual(s["gaps_over_20ms"], 0)
        self.assertAlmostEqual(s["batching_fraction"], 0.5, delta=0.05)

    def test_report_files(self):
        m0_analyze.main([self.prefix])
        self.assertTrue(Path(f"{self.prefix}_report.txt").exists())
        self.assertTrue(Path(f"{self.prefix}_report.png").exists())

    def test_recorder_demo_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "s")
            # taps=2 (not 1): five fingers need two taps each to reach the 10 tap rows checked below.
            subprocess.run([sys.executable, str(ROOT / "m0_record.py"), "--demo", "--out", prefix, "--taps", "2",
                            "--holds", "1", "--idle", "1", "--period", "0.2"], cwd=ROOT, timeout=60, check=True)
            for name in ("fingers", "imu", "cues"):
                self.assertTrue(Path(f"{prefix}_{name}.csv").exists(), name)
            with open(f"{prefix}_cues.csv", newline="") as fh:
                kinds = [r[1] for r in list(csv.reader(fh))[1:]]
            self.assertGreaterEqual(kinds.count("tap"), 10)
            for k in ("press", "lift", "idle_start", "idle_end"):
                self.assertIn(k, kinds)


if __name__ == "__main__":
    unittest.main()
