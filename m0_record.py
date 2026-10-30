#!/usr/bin/env python3
"""Prompted Tap Strap recording session for Milestone 0 (finger taps on paper).

    python m0_record.py [--out PREFIX] [--demo] [--taps 20] [--holds 10] [--idle 30] [--period 1.0]

Writes three CSVs (the labelled dataset for a future ML tap detector). All times are
host time.time() seconds, the same clock in every file:
    PREFIX_fingers.csv  host_time_s, device_ms, thumb_x_g, thumb_y_g, thumb_z_g, index_x_g, ... pinky_z_g
    PREFIX_imu.csv      host_time_s, device_ms, gyro_x_dps, gyro_y_dps, gyro_z_dps, accel_x_g, accel_y_g, accel_z_g
    PREFIX_cues.csv     host_time_s, kind, finger
        kind is tap | press | lift | idle_start | idle_end; finger is empty for idle_*.
        Each cue is logged right before its click, so the finger moves ~0.1-0.3 s later.
"""
import argparse
import asyncio
import csv
import os
import sys
import threading
import time
from datetime import datetime

from stream_raw import Recorder
from tapstrap import FINGERS, DemoStream, SensorConfig, TapRawStream

PAUSE = 2.0  # Seconds to read a new instruction.


def build_schedule(taps, holds, idle, period):
    """Return [(offset_s, kind, finger)]. kind "say" is a printed instruction, not a cue."""
    sched, t = [(0.0, "say", "Starting in 3 s...")], 3.0
    for f in FINGERS:
        sched.append((t, "say", f"NEXT: tap with {f.upper()} on each click"))
        t += PAUSE
        for _ in range(taps):
            sched.append((t, "tap", f))
            t += period
    t += 2.0
    for f in FINGERS:
        sched.append((t, "say", f"NEXT: {f.upper()} press on the first click, lift on the second"))
        t += PAUSE
        for _ in range(holds):
            sched += [(t, "press", f), (t + 1.0, "lift", f)]
            t += 2.0
    sched.append((t, "say", "NEXT: move your hand around WITHOUT tapping"))
    t += PAUSE
    sched += [(t, "idle_start", ""), (t + idle, "idle_end", "")]
    return sched


def click():
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(1000, 30), daemon=True).start()
    except ImportError:
        print("\a", end="", flush=True)


async def run(args, prefix):
    cfg = SensorConfig(finger_accel_g=8)
    stream = (DemoStream if args.demo else TapRawStream)(cfg)
    rec = Recorder(prefix)
    stream.on_sample(rec)
    cues_f = open(f"{prefix}_cues.csv", "w", newline="")
    cues = csv.writer(cues_f)
    cues.writerow(["host_time_s", "kind", "finger"])
    try:
        async with stream:
            t0 = time.time()
            for offset, kind, finger in build_schedule(args.taps, args.holds, args.idle, args.period):
                await asyncio.sleep(max(0.0, t0 + offset - time.time()))
                if kind == "say":
                    print(finger, flush=True)
                    continue
                now = time.time()
                cues.writerow([f"{now:.4f}", kind, finger])
                print(f"  {finger.upper():<6} {kind}" if finger else f"  {kind}", flush=True)
                click()
    finally:
        rec.close()
        cues_f.close()
        print("Wrote " + ", ".join(f"{prefix}_{n}.csv" for n in ("fingers", "imu", "cues")))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="file prefix (default recordings/m0_<timestamp>)")
    p.add_argument("--demo", action="store_true", help="synthetic stream, no strap")
    p.add_argument("--taps", type=int, default=20, help="taps per finger")
    p.add_argument("--holds", type=int, default=10, help="press/lift sequences per finger")
    p.add_argument("--idle", type=float, default=30, help="idle block seconds")
    p.add_argument("--period", type=float, default=1.0, help="seconds between taps")
    args = p.parse_args()
    prefix = args.out or f"recordings/m0_{datetime.now():%Y%m%d_%H%M%S}"
    os.makedirs(os.path.dirname(prefix) or ".", exist_ok=True)
    try:
        asyncio.run(run(args, prefix))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
