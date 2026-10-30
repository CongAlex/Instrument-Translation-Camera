# 007 — Live calibration sliders

- **Written against:** commit `bbb6903` (on `main`)
- **Status:** TODO
- **Effort:** M
- **Drift check:** `git diff bbb6903 -- calibration.py phone_server.py tests/` must print nothing; otherwise STOP.

## Why

The user now draws on blank paper, and the keyboards are small. On the real frame `samples/frame_20261029_220957.jpg` (a one-octave keyboard about 1 × 3.5 cm), the result depends on the ink sensitivity:

- At `INK_RATIO = 0.7` the drawing gives 11 regions, because one white key is missed.
- At `INK_RATIO = 0.8` it gives all 12, in the correct order `OSOSOOSOSOSO`.
- But 0.8 breaks the lined-paper fixtures. On lined paper the printed ruled lines count as ink at 0.8.

Small black keys can also be erased by the `LINE_KERNEL` (15) opening, because they are narrower than the kernel.

There is no single default that fits every sheet, so the user gets two sliders. Moving a slider re-runs detection instantly on the saved calibration reference image. There is no need to press C again.

## Current code (read the files fully first)

**`calibration.py`**

Constants:
- `INK_RATIO = 0.7`
- `LINE_KERNEL = 15`

Functions:
- **`find_regions(flat)`** uses `INK_RATIO` on line ~112 and `LINE_KERNEL` on line ~128.
- **`build_calibration(frames)`** returns a dict. It includes `"reference"`, the median BGR frame, and calls `find_regions(flat)`.
- **`save_calibration(cal, directory)`** writes `calibration.npz` and `regions.json`. The JSON file is the list `cal["regions"]`.
- **`load_calibration(directory, frame_shape)`** rebuilds the dict, or returns `None`.

**`phone_server.py`**

- **Module globals** include `calibration`, `calibrating`, `status_text` and `frame_lock`.
- **`process_frame`** builds the calibration with `new_cal = build_calibration(calibration_frames)`. It loads a saved one with `load_calibration(CALIBRATION_DIR, frame.shape)`.
- **The `__main__` loop** shows `cv2.imshow("Phone Camera Feed", frame)` and handles the C, S and Q keys with `key = cv2.waitKey(1) & 0xFF`.

## Scope

- **In scope:** `calibration.py`, `phone_server.py`, `tests/test_calibration.py`, a new fixture `tests/fixtures/blank_piano_small.jpg` (a copy of `samples/frame_20261029_220957.jpg`), and `README.md` (2–3 lines in the Calibration section).
- **Out of scope:** everything else. Do not change the default values of `INK_RATIO` or `LINE_KERNEL`. Do not change any other detection logic.

## Steps

### 1. `calibration.py`: settings as parameters

- **`find_regions(flat, ink_ratio=INK_RATIO, line_kernel=LINE_KERNEL)`:** use the parameters in place of the constants inside the function.
- **`build_calibration(frames, ink_ratio=INK_RATIO, line_kernel=LINE_KERNEL)`:** pass both parameters through to `find_regions`. Add `"settings": {"ink_ratio": float(ink_ratio), "line_kernel": int(line_kernel)}` to the returned dict.
- **New `rebuild_calibration(cal, ink_ratio, line_kernel)`:** returns `build_calibration([cal["reference"]], ink_ratio, line_kernel)`. Add the comment `# Re-detect on the saved reference image; no new frames needed.`
- **`save_calibration`:** also write `settings.json` containing `cal["settings"]`. Leave `regions.json` unchanged.
- **`load_calibration`:** read `settings.json` if it exists. Otherwise use `{"ink_ratio": INK_RATIO, "line_kernel": LINE_KERNEL}`. Store the result as `"settings"`.

### 2. `phone_server.py`: two trackbars

- **Constants and globals.** Add the window name `SETTINGS_WINDOW = "Calibration settings"` and these globals:

  ```python
  ink_ratio_setting = INK_RATIO
  line_kernel_setting = LINE_KERNEL
  ```

  Import `INK_RATIO`, `LINE_KERNEL` and `rebuild_calibration` from `calibration`.
- **Use the settings when calibrating.** In `process_frame`, call `build_calibration(calibration_frames, ink_ratio_setting, line_kernel_setting)`.
- **Sync the settings when a calibration loads.** After a successful `load_calibration`, set both globals from `calibration["settings"]`.
- **Create the window and trackbars.** In `__main__`, before the loop:
  - `cv2.namedWindow(SETTINGS_WINDOW)`
  - `cv2.createTrackbar("Sensitivity", SETTINGS_WINDOW, 50, 100, lambda v: None)`. Sensitivity `s` maps to `ink_ratio = 0.5 + 0.4 * s / 100`, so 50 gives 0.70, the default, and higher values are more liberal.
  - `cv2.createTrackbar("Min black key", SETTINGS_WINDOW, 15, 31, lambda v: None)`. This value is `line_kernel`, clamped to at least 3.
- **Each loop iteration:**
  - **Push loaded settings to the trackbars.** Under the lock, if `calibration` exists and its settings differ from what the trackbars were last set to, call `cv2.setTrackbarPos` to match. This keeps the trackbars in step with a loaded calibration. Track the last applied values in two local variables.
  - **Read the trackbars.** Call `cv2.getTrackbarPos` for both and compute `(ink_ratio, line_kernel)`.
  - **Debounce changes.** When those values differ from the globals, record the time. Once they have stayed unchanged for **0.3 s**:
    - Update the globals.
    - If a calibration exists and is not being calibrated:
      - **Try:** `new_cal = rebuild_calibration(calibration, ink_ratio, line_kernel)`, then save it, assign it, and set `status_text = f"Re-detected: {n} regions (sens {s}, key {k})"`.
      - **On `ValueError`:** set the status to the error and keep the old calibration.

      Do all of this under `frame_lock`.

### 3. Tests

Add these tests to `tests/test_calibration.py`:

- **`test_blank_piano_needs_higher_sensitivity`:** build from the fixture at the default sensitivity and assert fewer than 12 regions. Then call `rebuild_calibration(cal, 0.8, 15)` and assert that the kinds string is exactly `"OSOSOOSOSOSO"`.
- **`test_settings_roundtrip`:** build a synthetic solid sheet with `ink_ratio=0.75, line_kernel=11`. Save it to a temporary directory, load it back, and assert `settings == {"ink_ratio": 0.75, "line_kernel": 11}`.
- **`test_rebuild_matches_build`:** for the synthetic piano, `rebuild_calibration(cal, INK_RATIO, LINE_KERNEL)["regions"]` equals `cal["regions"]`.

Existing tests stay unchanged and must keep passing. That includes the one marked `@unittest.expectedFailure`.

### 4. README

In the Calibration section, add: the **Calibration settings** window has **Sensitivity** (raise it if lines are missed, lower it if paper texture or shadows become regions) and **Min black key** (lower it for small drawings). Changes re-detect instantly.

## Verification

Use `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe` and install nothing.

1. `python -m unittest discover -s tests -t .` reports 24 tests, `OK (expected failures=1)`.
2. `python -c "import phone_server"` exits 0.
3. `git diff --stat bbb6903` lists only in-scope files.

## STOP conditions

- If `rebuild_calibration(cal, 0.8, 15)` on the fixture does not give `OSOSOOSOSOSO`, report what it gives. You may try `line_kernel` 11 once. Do not change the expectation.
- If OpenCV trackbar calls fail in the import-time test environment, STOP and report. Trackbars must only be created under `__main__`.

## Maintenance note

- **Possible next step:** derive both settings automatically from the measured stroke width, using a distance transform of the ink mask. The sliders would then become overrides.
- **Small drawings:** keys smaller than about 4 mm sit at the camera's resolution limit at 640×480. The real fix is to draw bigger or move the phone closer.
