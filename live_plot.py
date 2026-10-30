#!/usr/bin/env python3
"""Live plot of Tap Strap 2 raw data: per-finger accel magnitude + thumb gyro.

    python live_plot.py            # real strap
    python live_plot.py --demo     # synthetic data
    python live_plot.py --window 3 --finger-range 8
"""
import argparse
import asyncio
import collections
import logging

import matplotlib.pyplot as plt

from tapstrap import FINGERS, DemoStream, FingerAccelSample, SensorConfig, TapRawStream


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--address")
    p.add_argument("--finger-range", type=int, default=4, choices=[2, 4, 8, 16])
    p.add_argument("--gyro-range", type=int, default=500, choices=[125, 250, 500, 1000, 2000])
    p.add_argument("--imu-range", type=int, default=4, choices=[2, 4, 8, 16])
    p.add_argument("--window", type=float, default=5.0, help="seconds of history shown")
    p.add_argument("--demo", action="store_true")
    return p.parse_args()


async def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = SensorConfig(args.finger_range, args.gyro_range, args.imu_range)
    stream = (DemoStream if args.demo else TapRawStream)(cfg, address=args.address)

    n = int(args.window * 210)
    ft = collections.deque(maxlen=n)
    fmag = [collections.deque(maxlen=n) for _ in FINGERS]
    gt = collections.deque(maxlen=n)
    gyro = [collections.deque(maxlen=n) for _ in range(3)]

    def collect(s, _t):
        if isinstance(s, FingerAccelSample):
            ft.append(s.device_ms / 1000)
            for d, m in zip(fmag, s.magnitudes()):
                d.append(m)
        else:
            gt.append(s.device_ms / 1000)
            for d, v in zip(gyro, s.gyro_dps):
                d.append(v)

    stream.on_sample(collect)

    plt.ion()
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    fig.canvas.manager.set_window_title("Tap Strap 2 raw sensors")
    flines = [ax1.plot([], [], label=f)[0] for f in FINGERS]
    glines = [ax2.plot([], [], label=a)[0] for a in "xyz"]
    ax1.set_ylabel("finger |accel| (g)")
    ax1.set_ylim(0, args.finger_range * 1.05)
    ax1.legend(loc="upper left", ncol=5, fontsize=8)
    ax2.set_ylabel("thumb gyro (deg/s)")
    ax2.set_ylim(-args.gyro_range, args.gyro_range)
    ax2.set_xlabel("device time (s)")
    ax2.legend(loc="upper left", ncol=3, fontsize=8)
    fig.tight_layout()

    async with stream:
        while plt.fignum_exists(fig.number):
            if ft:
                for line, d in zip(flines, fmag):
                    line.set_data(ft, d)
                ax1.set_xlim(ft[-1] - args.window, ft[-1])
            if gt:
                for line, d in zip(glines, gyro):
                    line.set_data(gt, d)
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            await asyncio.sleep(1 / 30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
