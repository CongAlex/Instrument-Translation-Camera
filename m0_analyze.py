#!/usr/bin/env python3
"""Offline report for an m0_record.py session: python m0_analyze.py PREFIX

Reads PREFIX_fingers.csv and PREFIX_cues.csv, writes PREFIX_report.txt and PREFIX_report.png.
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tapstrap import FINGERS

BEFORE, AFTER = 0.15, 0.25  # Label window around a cue, seconds.
REFRACTORY = 0.06
MATCH = 0.05
CROSS_WINDOW = 0.01
CHORD = 0.7


def load(prefix):
    with open(f"{prefix}_fingers.csv", newline="") as f:
        rows = list(csv.reader(f))[1:]
    data = np.array(rows, dtype=float)
    with open(f"{prefix}_cues.csv", newline="") as f:
        cues = [(float(t), k, fg) for t, k, fg in list(csv.reader(f))[1:]]
    return data[:, 0], data[:, 1], data[:, 2:].reshape(-1, 5, 3), cues


def jerk_of(dev_ms, acc):
    """Vector jerk per finger, shape (5, N), in g/s."""
    dt = np.diff(dev_ms) / 1000.0
    dt[dt <= 0] = np.median(dt[dt > 0])
    j = np.linalg.norm(np.diff(acc, axis=0), axis=2) / dt[:, None]
    return np.vstack([np.zeros((1, 5)), j]).T


def window_peak(t, j, cue):
    """(time, peak) of the max of j within the label window around cue."""
    idx = np.flatnonzero((t >= cue - BEFORE) & (t <= cue + AFTER))
    if len(idx) == 0:
        return np.nan, np.nan
    k = idx[np.argmax(j[idx])]
    return t[k], j[k]


def detect(t, jerk, thresholds):
    """Candidates (time, finger index, peak) after refractory and crosstalk rules."""
    cands = []
    for i in range(5):
        last = -1e18
        for k in np.flatnonzero(jerk[i] > thresholds[i]):
            if t[k] < last + REFRACTORY:
                continue
            last = t[k]
            m = (t >= t[k]) & (t < t[k] + REFRACTORY)
            cands.append((t[k], i, jerk[i][m].max()))
    # Drop a candidate when a clearly bigger one fires on another finger at the same moment.
    return [c for c in cands
            if not any(o[1] != c[1] and abs(o[0] - c[0]) <= CROSS_WINDOW and o[2] > c[2] and c[2] < CHORD * o[2]
                       for o in cands)]


def analyze(prefix):
    host, dev, acc, cues = load(prefix)
    dt = np.diff(dev) / 1000.0
    d = host - dev / 1000.0
    d_ms = (d - d.min()) * 1000
    out = {"stream": {
        "rate_hz": float(1 / np.median(dt[dt > 0])),  # Skips repeated timestamps (the demo stream emits them).
        "gaps_over_20ms": int(np.sum(dt > 0.02)),
        "batching_fraction": float(np.mean(host[1:] == host[:-1])),
        "delay_p50_ms": float(np.percentile(d_ms, 50)),
        "delay_p95_ms": float(np.percentile(d_ms, 95)),
    }}
    # Device clock mapped onto the host clock (cues use host time); the least-delayed packet sets the offset.
    t = dev / 1000.0 + d.min()
    jerk = jerk_of(dev, acc)

    def of(kind, f):
        return [c[0] for c in cues if c[1] == kind and c[2] == f]

    starts = [c[0] for c in cues if c[1] == "idle_start"]
    ends = [c[0] for c in cues if c[1] == "idle_end"]
    if starts and ends:
        idle = (t >= starts[0]) & (t <= ends[0])
    else:
        ct = np.array([c[0] for c in cues])
        idle = np.abs(t[:, None] - ct[None, :]).min(axis=1) > 0.3
    idle_p99 = np.percentile(jerk[:, idle], 99, axis=1)

    peaks = {k: [[window_peak(t, jerk[i], c)[1] for c in of(k, f)] for i, f in enumerate(FINGERS)]
             for k in ("tap", "lift", "press")}
    tap_med = np.array([np.median(p) for p in peaks["tap"]])
    out["separability"] = {f: float(tap_med[i] / idle_p99[i]) for i, f in enumerate(FINGERS)}

    thr = np.sqrt(tap_med * idle_p99)
    dets = detect(t, jerk, thr)
    tap_times = [c for f in FINGERS for c in of("tap", f)]
    ranges = [(min(tap_times) - 0.3, max(tap_times) + 0.5)]
    if starts and ends:
        ranges.append((starts[0], ends[0]))
    out["detection"], out["lift"] = {}, {}
    for i, f in enumerate(FINGERS):
        labels = sorted(window_peak(t, jerk[i], c)[0] for c in of("tap", f))
        mine = sorted(dd[0] for dd in dets if dd[1] == i and any(a <= dd[0] <= b for a, b in ranges))
        free, tp = list(labels), 0
        for x in mine:
            near = [y for y in free if abs(y - x) <= MATCH]
            if near:
                free.remove(min(near, key=lambda y: abs(y - x)))
                tp += 1
        p = tp / len(mine) if mine else 0.0
        r = tp / len(labels) if labels else 0.0
        out["detection"][f] = {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}
        lifts = of("lift", f)
        hit = sum(any(c - BEFORE <= dd[0] <= c + AFTER for dd in dets if dd[1] == i) for c in lifts)
        out["lift"][f] = {"ratio": float(np.median(peaks["lift"][i]) / idle_p99[i]),
                          "recall": hit / len(lifts) if lifts else 0.0}

    xt = []
    for i, f in enumerate(FINGERS):
        rows = []
        for c in of("tap", f):
            pk = [window_peak(t, jerk[j], c)[1] for j in range(5)]
            rows.append([pk[j] / pk[i] for j in range(5)])
        xt.append([float(x) for x in np.median(rows, axis=0)])
    out["crosstalk"] = xt
    out["_plot"] = (t, jerk, cues)
    return out


def verdict(f, sep, det):
    kind = "clean" if sep > 3 else "marginal" if sep >= 1.5 else "not separable"
    return (f"{f.upper()}: {kind}. Tap peaks are {sep:.1f}x the idle p99 jerk; the threshold detector gets "
            f"precision {det['precision']:.2f}, recall {det['recall']:.2f}.")


def report_text(r):
    s = r["stream"]
    lines = ["Stream health",
             f"  sample rate (median):      {s['rate_hz']:.1f} Hz",
             f"  gaps over 20 ms:           {s['gaps_over_20ms']}",
             f"  batching fraction:         {s['batching_fraction']:.2f}",
             f"  arrival delay p50 / p95:   {s['delay_p50_ms']:.1f} / {s['delay_p95_ms']:.1f} ms",
             "  (arrival-delay spread is a latency jitter proxy; true latency needs an external reference)",
             "", "Per finger",
             f"  {'finger':<7}{'sep':>7}{'prec':>7}{'recall':>8}{'f1':>6}{'lift/idle':>11}{'lift rec':>10}"]
    for f in FINGERS:
        d, lf = r["detection"][f], r["lift"][f]
        lines.append(f"  {f:<7}{r['separability'][f]:7.2f}{d['precision']:7.2f}{d['recall']:8.2f}{d['f1']:6.2f}"
                     f"{lf['ratio']:11.2f}{lf['recall']:10.2f}")
    lines += ["", "Crosstalk (row = cued finger, column = peak jerk ratio)",
              "         " + "".join(f"{f:>8}" for f in FINGERS)]
    lines += [f"  {f:<7}" + "".join(f"{v:8.2f}" for v in row) for f, row in zip(FINGERS, r["crosstalk"])]
    lines += ["", "Verdicts"] + [verdict(f, r["separability"][f], r["detection"][f]) for f in FINGERS]
    return "\n".join(lines) + "\n"


def plot(r, path):
    t, jerk, cues = r["_plot"]
    taps = [c for c in cues if c[1] == "tap"]
    t0 = min(c[0] for c in taps) - 1
    m = (t >= t0) & (t <= t0 + 60)
    fig = plt.figure(figsize=(14, 8))
    gs = fig.add_gridspec(5, 2, width_ratios=[3, 1])
    for i, f in enumerate(FINGERS):
        ax = fig.add_subplot(gs[i, 0])
        ax.plot(t[m] - t0, jerk[i][m], lw=0.6)
        for c in taps:
            if c[2] == f and c[0] - t0 <= 60:
                ax.axvline(c[0] - t0, color="r", alpha=0.4, lw=0.8)
        ax.set_ylabel(f"{f}\ng/s")
    ax.set_xlabel("seconds into tap block")
    hx = fig.add_subplot(gs[:, 1])
    im = hx.imshow(r["crosstalk"], vmin=0, vmax=1, cmap="viridis")
    hx.set_xticks(range(5), FINGERS, rotation=45)
    hx.set_yticks(range(5), FINGERS)
    hx.set_title("crosstalk")
    fig.colorbar(im, ax=hx)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.exit("usage: python m0_analyze.py PREFIX")
    prefix = argv[0]
    r = analyze(prefix)
    text = report_text(r)
    with open(f"{prefix}_report.txt", "w") as f:
        f.write(text)
    plot(r, f"{prefix}_report.png")
    print(text)


if __name__ == "__main__":
    main()
