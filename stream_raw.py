#!/usr/bin/env python3
"""Stream raw Tap Strap 2 sensor data to the terminal and (optionally) CSV.

Examples:
    python stream_raw.py                          # live readout
    python stream_raw.py --csv session1           # also log session1_fingers.csv / session1_imu.csv
    python stream_raw.py --finger-range 8 --gyro-range 1000 --duration 30
    python stream_raw.py --demo                   # synthetic data, no strap needed
"""
import argparse
import asyncio
import csv
import logging
import time

from tapstrap import FINGERS, DemoStream, FingerAccelSample, ImuSample, SensorConfig, TapRawStream


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--address", help="BLE address / device id (default: first Tap found)")
    p.add_argument("--finger-range", type=int, default=4, choices=[2, 4, 8, 16], help="finger accel range, ±g")
    p.add_argument("--gyro-range", type=int, default=500, choices=[125, 250, 500, 1000, 2000], help="thumb gyro, ±dps")
    p.add_argument("--imu-range", type=int, default=4, choices=[2, 4, 8, 16], help="thumb IMU accel range, ±g")
    p.add_argument("--csv", metavar="PREFIX", help="write PREFIX_fingers.csv and PREFIX_imu.csv")
    p.add_argument("--duration", type=float, help="stop after N seconds")
    p.add_argument("--demo", action="store_true", help="use synthetic data instead of a real strap")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def bar(value, full_scale=3.0, width=12):
    n = min(width, int(abs(value) / full_scale * width))
    return "█" * n + "·" * (width - n)


class Recorder:
    def __init__(self, prefix):
        self.ff = open(f"{prefix}_fingers.csv", "w", newline="")
        self.fi = open(f"{prefix}_imu.csv", "w", newline="")
        self.wf, self.wi = csv.writer(self.ff), csv.writer(self.fi)
        self.wf.writerow(["host_time_s", "device_ms"] + [f"{f}_{ax}_g" for f in FINGERS for ax in "xyz"])
        self.wi.writerow(["host_time_s", "device_ms", "gyro_x_dps", "gyro_y_dps", "gyro_z_dps",
                          "accel_x_g", "accel_y_g", "accel_z_g"])

    def __call__(self, s, host_time):
        if isinstance(s, FingerAccelSample):
            self.wf.writerow([f"{host_time:.4f}", s.device_ms] +
                             [f"{v:.4f}" for f in FINGERS for v in getattr(s, f)])
        else:
            self.wi.writerow([f"{host_time:.4f}", s.device_ms] +
                             [f"{v:.3f}" for v in (*s.gyro_dps, *s.accel_g)])

    def close(self):
        self.ff.close()
        self.fi.close()


async def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    cfg = SensorConfig(args.finger_range, args.gyro_range, args.imu_range)
    stream = (DemoStream if args.demo else TapRawStream)(cfg, address=args.address)

    latest = {"fingers": None, "imu": None}
    counts = {"fingers": 0, "imu": 0}

    def track(s, _t):
        key = "fingers" if isinstance(s, FingerAccelSample) else "imu"
        latest[key] = s
        counts[key] += 1

    stream.on_sample(track)
    rec = Recorder(args.csv) if args.csv else None
    if rec:
        stream.on_sample(rec)

    start = time.time()
    try:
        async with stream:
            last = time.time()
            while args.duration is None or time.time() - start < args.duration:
                await asyncio.sleep(0.25)
                now = time.time()
                dt, last = now - last, now
                f, i = latest["fingers"], latest["imu"]
                lines = []
                if f:
                    for name, mag in zip(FINGERS, f.magnitudes()):
                        lines.append(f"  {name:<6} |a|={mag:5.2f} g  {bar(mag)}")
                if i:
                    gx, gy, gz = i.gyro_dps
                    lines.append(f"  gyro  ({gx:7.1f}, {gy:7.1f}, {gz:7.1f}) dps")
                rate = f"fingers {counts['fingers'] / dt:5.0f} Hz | imu {counts['imu'] / dt:5.0f} Hz"
                counts["fingers"] = counts["imu"] = 0
                print("\033[2J\033[H" + rate + "\n" + ("\n".join(lines) or "  waiting for data..."), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if rec:
            rec.close()
            print(f"Saved {args.csv}_fingers.csv and {args.csv}_imu.csv")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
