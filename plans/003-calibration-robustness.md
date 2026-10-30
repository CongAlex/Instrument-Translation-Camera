# 003 — Calibration robustness (DRAFT)

- **Status:** DRAFT. Not executable yet. It will be detailed against whatever commit plan 002 lands as.
- **Depends on:** 002
- **Effort:** S–M

## Scope (agreed with the user, 2026-10-29)

1. **Stillness check before capture.**
   - Calibration capture starts only after:
     - about 2 s have passed since frames began arriving, because phone auto-exposure settles; and
     - the mean absolute difference between consecutive grayscale frames has stayed below about 3/255 for 1 s.
   - This adds to the existing zero-hands rule in `phone_server.receive_frame`.
2. **"Camera moved" watcher.**
   - Every 2 s, when no hand landmark lies within 30 px of any saved paper corner, re-run `calibration.find_paper_corners` on the live frame.
   - If any corner moved more than 1.5% of the frame width, mark the calibration stale: stop region lookup and show "Camera moved: press C to recalibrate."
3. **Edge stabilisation.**
   - Per finger, map the fingertip into flattened space with `H`.
   - If it is within about 5 canonical px of a region boundary, keep that finger's previous region instead of the new one.
   - This needs per-finger state, kept for the first hand only.

## Tests to add

- A stillness gate fed with a synthetic frame sequence: noisy frames, then still frames.
- A watcher fed with shifted corners.
- Edge hysteresis on a fingertip that jitters across a boundary.
