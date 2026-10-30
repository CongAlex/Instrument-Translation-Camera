# Project Metrics

These are numbers worth keeping for write-ups and résumé bullets. Every entry gives its date, how it was measured, and whether it is **measured** (on real hardware) or **synthetic** (from the automated test images). Add new rows as you go, and never edit old rows: the before and after numbers are the story.

## Camera stream performance (iPhone → ngrok → laptop)

| Date | Change | Metric | Before | After | Source |
|---|---|---|---|---|---|
| 2026-10-29 | Removed the 10 fps client cap, let frames be sent concurrently, moved server processing off the request path, stopped cached JS | Frames per second delivered | 4–5 fps | ~27 fps (**~6× faster**) | Measured on the phone's FPS counter |
| 2026-10-29 | Same change | Capture resolution | 320×240 | 640×480 (**4× the pixels**) | Measured, at the same time as the fps gain above |
| 2026-10-29 | Server measurement after decoupling (2 frames in flight) | Per-frame processing on the laptop (paper detection + MediaPipe hands + overlay) | n/a | 18 ms (headroom for about 55 fps) | Measured on the laptop's `proc` counter |
| 2026-10-29 | 2 → 4 frames in flight over the internet tunnel | Laptop receive rate | 10 fps | ~27 fps | Measured (`rx` counter and phone FPS) |

## Calibration (paper keyboard detection)

| Date | Metric | Result | Source |
|---|---|---|---|
| 2026-10-29 | One-octave paper piano: keys found and ordered chromatically (C → B, 12 keys) | 12/12 correct when straight, tilted, sideways (rotated 90°) and at 40% scale | Synthetic tests |
| 2026-10-29 | Hand-drawn pen box on lined paper (first real photo) | 0 → 1 box detected, after outline gap-closing | Measured on a real photo, now a regression test |
| 2026-10-29 | Hand-drawn 2-white + 1-black key sketch plus a box | 4/4 regions on both saved frames | Measured on real photos |
| 2026-10-29 | Real 640×480 frames from a higher camera angle with the paper rotated (torn, round-cornered lined paper) | Paper found in 0/2 → 2/2 frames; all 4 regions correct in 2/2 (ruled lines no longer split keys) | Measured on real photos, now regression tests |
| 2026-10-29 | Lookup cost from fingertip to key | One array read per fingertip (precomputed key map) | By design |

## Engineering quality

| Date | Metric | Before | After |
|---|---|---|---|
| 2026-10-29 | Automated tests | 0 | 19 (server + calibration), all passing |
| 2026-10-29 | Server hardening | No upload limit, CORS open to all sites, thread-unsafe ML calls | 2 MB cap, CORS removed, serialised landmarker with strictly increasing timestamps |

## Still to measure (fill in later)

- **Latency:** time from tap to sound, end to end (design target: 50 ms or less).
- **Camera freshness:** age of the fingertip data when a tap arrives (target: 100 ms or less). Today's tunnel round trip is probably around 150–200 ms (not yet measured).
- **Round trip on LAN HTTPS vs ngrok:** the planned transport upgrade.
- **Tap Strap:** tap detection precision and recall (±20 ms), and Bluetooth latency.
- **Key accuracy:** percent correct per key in live play, especially at key edges, and how it changes with key size.
- **Calibration success rate:** under normal light, dim light and a slight tilt.
