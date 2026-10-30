# Project Metrics

These are numbers worth keeping for write-ups and résumé bullets. Every entry gives its date, how it was measured, and whether it is **measured** (on real hardware) or **synthetic** (from the automated test images). Add new rows as you go, and never edit old rows: the before and after numbers are the story.

## Camera stream performance (iPhone → ngrok → laptop)

| Date | Change | Metric | Before | After | Source |
|---|---|---|---|---|---|
| 2026-10-29 | Removed the 10 fps client cap, let frames be sent concurrently, moved server processing off the request path, stopped cached JS | Frames per second delivered | 4–5 fps | ~27 fps (**~6× faster**) | Measured on the phone's FPS counter |
| 2026-10-29 | Same change | Capture resolution | 320×240 | 640×480 (**4× the pixels**) | Measured, at the same time as the fps gain above |
| 2026-10-29 | Server measurement after decoupling (2 frames in flight) | Per-frame processing on the laptop (paper detection + MediaPipe hands + overlay) | n/a | 18 ms (headroom for about 55 fps) | Measured on the laptop's `proc` counter |
| 2026-10-29 | 2 → 4 frames in flight over the internet tunnel | Laptop receive rate | 10 fps | ~27 fps | Measured (`rx` counter and phone FPS) |

## Camera over USB (iPhone → Camo → laptop), replacing ngrok

| Date | Change | Metric | Before | After | Source |
|---|---|---|---|---|---|
| 2026-10-29 | Switched from browser page + ngrok internet tunnel to a USB webcam (Camo, free tier) | Frames arriving | ~27 fps over ngrok, about 150–200 ms network round trip (estimated) | ~30 fps over a USB cable, with no internet path | Measured (`rx` counter) |
| 2026-10-29 | Shrank webcam frames to 640 px wide; profiled the pipeline | Processing time per frame (hand tracking alone is about 15 ms) | ~140 ms at 1280×720 | **~13 ms** at 640×360, with `age` (arrival to ready) ~14 ms. That is headroom for about 70 fps | Measured headless on AC power with the CPU uncontended. A live run on 11% battery (CPU throttled to ~50%) showed ~190 ms, so retest when plugged in |
| 2026-10-29 | Reliability fixes on the USB path | Black-screen and freeze bugs | Forced 640×480 made Camo send black frames; one bad frame killed the processing thread; Ctrl+C hung the terminal | All fixed and covered by tests where possible | Measured |

## Calibration (paper keyboard detection)

| Date | Metric | Result | Source |
|---|---|---|---|
| 2026-10-29 | One-octave paper piano: keys found and ordered chromatically (C → B, 12 keys) | 12/12 correct when straight, tilted, sideways (rotated 90°) and at 40% scale | Synthetic tests |
| 2026-10-29 | Hand-drawn pen box on lined paper (first real photo) | 0 → 1 box detected, after outline gap-closing | Measured on a real photo, now a regression test |
| 2026-10-29 | Hand-drawn 2-white + 1-black key sketch plus a box | 4/4 regions on both saved frames | Measured on real photos |
| 2026-10-29 | Real 640×480 frames from a higher camera angle with the paper rotated (torn, round-cornered lined paper) | Paper found in 0/2 → 2/2 frames; all 4 regions correct in 2/2 (ruled lines no longer split keys) | Measured on real photos, now regression tests |
| 2026-10-29 | Small hand-drawn one-octave keyboard (~1 × 3.5 cm, black keys ~2–3 mm) on blank paper | 11/12 keys at the default sensitivity → **12/12, in chromatic order**, with the sensitivity slider raised | Measured on a real photo, now a regression test |
| 2026-10-29 | Re-tuning detection after calibration | Re-detects ~0.3 s after a slider stops moving, using the saved reference image; no new capture needed | By design |
| 2026-10-29 | Soft shadow across the paper on a real Camo frame | Before: detected as a huge fake black key. After: ignored (dark ink must now be dark compared with the surrounding paper) | Measured on a real photo, now a regression test |
| 2026-10-29 | Lookup cost from fingertip to key | One array read per fingertip (precomputed key map) | By design |

## Tap Strap (M0 tooling, strap not yet tested on paper)

| Date | Metric | Result | Source |
|---|---|---|---|
| 2026-10-29 | Tap detector and analysis pipeline, checked on synthetic 200 Hz recordings with known taps and 30% crosstalk | Precision 1.00 and recall 1.00 on all 5 fingers; crosstalk measured at 0.30 (matches what was built in); 200 Hz, 0 gaps, batching measured correctly | Synthetic tests |
| 2026-10-29 | Labelled-data tooling | Guided recording sessions (taps, press-hold-lift, idle) that save ML-ready labelled CSVs | By design |

## Engineering quality

| Date | Metric | Before | After |
|---|---|---|---|
| 2026-10-29 | Automated tests | 0 | 19 (server + calibration), all passing |
| 2026-10-29 | Automated tests (later the same day) | 19 | 35 (server, calibration, real-photo fixtures, strap decoding, M0 analysis), all passing |
| 2026-10-29 | Repos consolidated | Camera and strap code in separate repos | One master repo |
| 2026-10-29 | Server hardening | No upload limit, CORS open to all sites, thread-unsafe ML calls | 2 MB cap, CORS removed, serialised landmarker with strictly increasing timestamps |

## Still to measure (fill in later)

- **Latency:** time from tap to sound, end to end (design target: 50 ms or less).
- **Camera freshness:** age of the fingertip data when a tap arrives (target: 100 ms or less). Today's tunnel round trip is probably around 150–200 ms (not yet measured).
- **Speed with the laptop plugged in:** re-measure `proc` and `age` live on AC power at Best performance. Optional next step: skip paper detection on each frame once calibrated.
- **Tap Strap:** tap detection precision and recall (±20 ms), and Bluetooth latency.
- **Key accuracy:** percent correct per key in live play, especially at key edges, and how it changes with key size.
- **Calibration success rate:** under normal light, dim light and a slight tilt.
