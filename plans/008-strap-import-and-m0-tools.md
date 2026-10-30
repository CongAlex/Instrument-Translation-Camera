# 008 — Bring in the Tap Strap code + M0 recording/analysis tools

- **Written against:** `main` at `43103ce` (this repo), and `6183892` of `../Instrument-Tapstrap-Test`.
- **Status:** TODO
- **Effort:** M
- **Drift check:**
  - `git diff 43103ce -- .gitignore requirements.txt` in this repo must print nothing.
  - `git -C ../Instrument-Tapstrap-Test log -1 --format=%h` must print `6183892`.
  - Otherwise STOP.

## Why

The design doc's Milestone 0 asks whether finger taps on paper give clean, separate accelerometer spikes per finger on a Tap Strap 2, and what the Bluetooth timing looks like. Everything downstream depends on that answer.

The user wants this repo to be the single master repo, so the strap code moves in here.

The strap isn't available right now. So this plan builds the **recording tool** and the **analysis tool**, and proves both work using synthetic data and the existing `DemoStream`.

The recordings are also the labelled dataset for a future ML tap detector. Keep the format simple and documented.

## Background: the strap package (in `../Instrument-Tapstrap-Test`)

- **`tapstrap/decode.py`:** `SensorConfig(finger_accel_g=...)`, `FingerAccelSample(device_ms, thumb, index, middle, ring, pinky)` (each finger an `(x, y, z)` in g), `ImuSample`, `FINGERS`.
- **`tapstrap/stream.py`:** `TapRawStream(config)` is an async context manager with `on_sample(cb)`, where `cb(sample, host_time_s)` and `host_time_s` is `time.time()` taken once per BLE notification. Samples batched in one notification therefore share a host time. `DemoStream` is a synthetic 200 Hz stream with no taps.
- **`stream_raw.py`:** contains `class Recorder`, which writes `PREFIX_fingers.csv` with columns `host_time_s, device_ms, thumb_x_g, thumb_y_g, thumb_z_g, index_x_g, … pinky_z_g`, and `PREFIX_imu.csv`. Read the file to see how `--demo` and the async main are structured, and reuse that pattern.
- **`tests/test_decode.py`:** pytest style, 43 lines.

**Important:** the strap repo's working tree has an uncommitted change that deletes `k += 1` in `DemoStream`. That deletion is a bug. Copy files from the **committed** version, using `git -C ../Instrument-Tapstrap-Test show 6183892:<path> > <dest>`, never from the working tree. Do not modify the strap repo at all.

**This repo's conventions:**
- Flat layout, stdlib `unittest`.
- Plain functions, short `# Comment.` lines.
- Tests run with `python -m unittest discover -s tests -t .`.

## Scope

- **New, copied in:**
  - `tapstrap/__init__.py`, `tapstrap/decode.py`, `tapstrap/stream.py`
  - `stream_raw.py`, `live_plot.py`
  - `tests/test_decode.py`, converted to unittest
- **New, written:**
  - `m0_record.py`, `m0_analyze.py`
  - `tests/test_m0.py`
- **Edited:**
  - `requirements.txt`: append the strap repo's deps, `tap-python-sdk @ git+https://github.com/TapWithUs/tap-python-sdk.git` and `matplotlib>=3.7`. Do not add pytest.
  - `.gitignore`: add `recordings/`.
  - `README.md`: add a short "Tap Strap (M0)" section.
- **Out of scope:** every camera file (`phone_*.py/js/html/css`, `calibration.py`, `paper_detector.py`, `calibrate_image.py`), and the strap repo itself.

## Steps

### 1. Copy the package

Copy the files above at commit `6183892`, unchanged except as follows:

- **Convert `tests/test_decode.py` to unittest.**
  - Wrap the functions in `class DecodeTests(unittest.TestCase)` as methods.
  - Replace bare `assert` with `self.assertTrue` / `self.assertEqual`.
  - Replace `pytest.approx(x, abs=e)` with `self.assertAlmostEqual(..., delta=e)`, or `rel` handled as `delta=abs(x) * rel`.
  - Replace `pytest.raises` with `self.assertRaises`.
  - Keep every check's meaning.
  - Add the same `sys.path` header that `tests/test_server.py` uses.

### 2. Install the dependencies

Run `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe -m pip install "tap-python-sdk @ git+https://github.com/TapWithUs/tap-python-sdk.git" "matplotlib>=3.7"`.

If the install fails, STOP and report the error.

### 3. `m0_record.py`: a prompted recording session

This builds a labelled dataset. Usage:

```
python m0_record.py [--out PREFIX] [--demo] [--taps 20] [--holds 10] [--idle 30] [--period 1.0]
```

**Defaults:**
- `--out` defaults to `recordings/m0_<YYYYmmdd_HHMMSS>`. Create `recordings/` if missing.
- Use `SensorConfig(finger_accel_g=8)` and `TapRawStream`, or `DemoStream` when `--demo` is passed.
- Attach `stream_raw.Recorder(PREFIX)` via `on_sample`, imported from `stream_raw`.

**Schedule:** build it up front as a list of `(offset_s, kind, finger)`.
1. A 3 s countdown.
2. For each finger in `FINGERS`, `--taps` cues of kind `tap`, one per `--period`.
3. A 2 s gap.
4. For each finger, `--holds` sequences of `press` at t and `lift` at t + 1.0 s, with sequences spaced 2.0 s apart.
5. Then one `idle_start`, and `idle_end` `--idle` seconds later. The user moves the hand around without tapping during this block.

Change of block: print a clear instruction line (for example `"NEXT: tap with INDEX on each click"`) and pause 2 s.

**Cues:**
- Fire each cue at its scheduled `time.time()` using `asyncio.sleep`. Use the same clock as `host_time_s`.
- On each cue, print the cue (for example `"  INDEX  tap"`) and make a short click: `winsound.Beep(1000, 30)` on Windows, run in a thread so it doesn't block; otherwise print `"\a"`.
- Append each cue to `PREFIX_cues.csv` with columns `host_time_s, kind, finger`. The time is taken right before the click.

**Ending:** Ctrl+C ends early, and every file must still be closed cleanly. Finally, print the paths written.

Add a module docstring that documents the three files and their columns. This is the dataset format for future ML.

### 4. `m0_analyze.py`: the offline report

Usage: `python m0_analyze.py PREFIX`. Expose `analyze(prefix) -> dict` for the tests; `main()` prints the report and writes the files.

**Load the data.** Read `PREFIX_fingers.csv` and `PREFIX_cues.csv` with the `csv` module and numpy. Do not use pandas.

**Signal.** Per finger, compute the vector jerk per sample: `j[k] = |a[k] - a[k-1]| / dt[k]`, in g/s. `dt` comes from `device_ms` differences in seconds; use the median dt wherever a dt is 0 or negative.

**Stream health** (key `"stream"`):
- median sample rate in Hz, from the `device_ms` diffs;
- the number of gaps over 20 ms;
- the batching fraction, meaning the share of samples whose `host_time_s` equals the previous sample's;
- the arrival-delay spread: `d = host_time_s - device_ms/1000`, then `d - d.min()`, reported in ms as p50 and p95. This is the latency jitter proxy. True latency needs an external reference; say so in the report.

**Labels.** For each `tap` cue on finger f, the labelled tap time is the time of max jerk on f within `[cue - 0.15 s, cue + 0.25 s]`. Do the same for `lift` cues and for `press` cues.

**Separability** (key `"separability"[finger]`): `median(labelled tap peak jerk) / percentile99(jerk on f during the idle block)`. If there is no idle block, use all samples farther than 0.3 s from any cue.

**Detector** (keys `"detection"[finger]` = `{"precision", "recall", "f1"}`):
- **Threshold** per finger: the geometric mean of the median tap peak and the idle p99.
- **Candidates:** threshold crossings with a 60 ms refractory period per finger.
- **Crosstalk rule:** among candidates on different fingers within 10 ms of each other, keep only the largest, unless another one is at least 0.7× its size (a chord).
- **Scoring:** a detection on finger f is a true positive if it is within ±50 ms of an unmatched labelled tap on f. Score over the tap blocks plus the idle block. Idle detections are false positives.

**Crosstalk** (key `"crosstalk"`, a 5×5 list): row i holds, for taps cued on finger i, the median over taps of (peak jerk on finger j in the label window) / (peak on finger i). The diagonal is therefore 1.

**Lift** (key `"lift"[finger]`): `median(lift peak) / idle p99`, plus the recall of the same detector run over the lift windows.

**Outputs:**
- `PREFIX_report.txt`: the tables, plus a one-paragraph verdict per finger. Separability over 3 counts as "clean", 1.5–3 as "marginal", under 1.5 as "not separable".
- `PREFIX_report.png`: matplotlib with the Agg backend. Draw five stacked jerk traces for the first 60 s of the tap block, with cue ticks, plus a crosstalk heatmap.

### 5. Tests: `tests/test_m0.py`

**Helper `write_synthetic(prefix, crosstalk=0.3, seed=0)`:**
- Writes a fingers CSV at 200 Hz with `device_ms` stepping by 5 ms.
- Host time equals device time plus a 30 ms offset, with samples batched in pairs that share a host time.
- The signal is Gaussian noise of σ = 0.01 g per axis, on top of `(0, 0, -1)` gravity.
- Generate cues on the same schedule shape as the recorder, with small counts.
- At each tap cue + 80 ms, add a spike to the cued finger: a single-sample step of +1.5 g on z, then back to baseline.
- Add the same spike scaled by `crosstalk` to the neighbouring fingers.
- For each lift, add a smaller spike of +0.5 g.

**Tests:**
- `test_detects_synthetic_taps`: every finger has recall ≥ 0.95 and precision ≥ 0.9.
- `test_crosstalk_matrix`: the diagonal is ≈ 1, and the immediate neighbours are within 0.3 ± 0.1.
- `test_stream_stats`: the rate is 200 ± 1 Hz, there are 0 gaps, and the batching fraction is ≈ 0.5 (± 0.05).
- `test_report_files`: running `main` writes both the report `.txt` and the `.png`.
- `test_recorder_demo_smoke`: run `m0_record.py --demo --out <tmp>/s --taps 1 --holds 1 --idle 1 --period 0.2` as a subprocess, with a 60 s timeout. All three CSVs must exist, and the cues file must contain at least 10 tap rows plus the press, lift and idle rows.

## Verification

Use `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe`.

1. `python -m unittest discover -s tests -t .` passes: the previous 24 tests (with 1 expected failure), plus the decode tests, plus 5 new ones.
2. `python m0_record.py --demo --taps 2 --holds 1 --idle 2 --period 0.3` runs to completion.
   - Then `python m0_analyze.py <that prefix>` writes the report.
   - Paste the report's stream-health section and the first verdict line into your final message.
   - The demo stream has no taps, so verdicts of "not separable" are expected and fine.
3. `git diff --stat 43103ce` lists only in-scope files, and `git -C ../Instrument-Tapstrap-Test status --short` is unchanged: it still shows only ` M tapstrap/stream.py`.

## STOP conditions

- The pip install fails.
- Decode tests fail after conversion. Report them; do not edit the decode logic.
- The synthetic tests need loosened thresholds to pass. Report the observed numbers instead.

## Maintenance note

- **This repo is now the source of truth for `tapstrap/`.** The old repo is an archive.
- **The ML path from the design doc** (threshold, then a classifier, then a 1D CNN) consumes exactly these three CSVs. The cues are the labels.
- **When the strap is back:** do 2–3 real sessions, then put the numbers in `METRICS.md`.
