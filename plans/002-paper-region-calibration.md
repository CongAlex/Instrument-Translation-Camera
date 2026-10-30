# 002 — Paper region calibration (M-1)

- **Written against:** commit `3e0f1a1`, which is plan 001 on top of `6c76881`. Repo: `CongAlex/Instrument-Translation-Camera`.
- **Status:** TODO
- **Effort:** M
- **Depends on:** 001. Your worktree must contain commit `3e0f1a1`; see "Setup".

## Goal

A phone camera looks straight down at a printed US Letter sheet, in landscape, on a desk. The sheet carries black ink drawings. Each drawing is either:

- a **solid black rectangle**, or
- a **white area enclosed by a black outline**.

A piano drawing combines both: white keys are outlined areas, and black keys are solid boxes drawn over them.

Calibration finds every such **region** and numbers them **1..N left to right** by the region's centre x. On a one-octave piano drawing this yields chromatic order automatically (1=C, 2=C#, 3=D, ...). Calibration then produces a **key map**: an image the size of the camera frame in which each pixel holds the ID of the region under it, and 0 means "no region".

At runtime, each of the 5 fingertips is looked up in the key map, and the result is drawn on the live view.

## Background: current code (after plan 001)

`phone_server.py` is a Flask app.

- `POST /frame` decodes a JPEG into `frame` (BGR).
- `annotated, mask = detect_paper(frame)` returns a copy with the paper outline drawn on it, plus a white mask. The mask uses HSV `inRange` with `[0,0,120]..[180,80,255]`.
- MediaPipe `hand_landmarker.detect_for_video` runs on the clean `frame` inside `landmarker_lock`.
- `annotated = draw_hand_landmarks(annotated, result)` draws the landmarks.
- The results are stored under `frame_lock` as `latest_frame` / `latest_mask`.
- The `__main__` block starts Flask in a daemon thread. It then loops showing `latest_frame` with `cv2.imshow("Phone Camera Feed", ...)` and quits on Q.
- `BASE_DIR = Path(__file__).resolve().parent` exists.
- `result.hand_landmarks` is a list of hands. Each hand is a list of 21 landmarks with normalised `.x` / `.y` coordinates (0..1).

Tests live in `tests/test_server.py`, use stdlib `unittest`, and run with `python -m unittest discover -s tests -t .` from the repo root.

**Conventions:**
- Plain module-level functions, no classes.
- Plain dicts for data.
- 4-space indent.
- Short `# Comment.` lines.
- Wrapped call arguments as in the existing code.
- **No new dependencies.** Use only numpy, cv2 and the stdlib.

## Setup

Run in your worktree, before anything else:

```
git merge --ff-only 3e0f1a1
```

Then confirm that `git log --oneline -1` shows `3e0f1a1`.

If it fails, STOP and report.

## Scope

**In scope:**
- new `calibration.py`
- new `calibrate_image.py`
- new `tests/test_calibration.py`
- edits to `phone_server.py`
- `.gitignore` (add one line)
- `README.md` (add one short section)

**Out of scope:**
- `paper_detector.py` (import it, don't change it)
- `phone_camera.*`
- `models/`
- `requirements.txt`
- `tests/test_server.py` (must keep passing unchanged)

Do not add a stillness check, a "camera moved" watcher, or edge smoothing across frames. Those belong to plan 003.

## Step 1 — `calibration.py`

Use these module constants, all in canonical (flattened) pixels:

```python
FLAT_W, FLAT_H = 1100, 850   # US Letter landscape, 100 px per inch.
FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}
BORDER_PX = 12               # Ignore ink this close to the paper edge.
DARK_LEVEL = 100             # Anything darker than this is ink.
SPECK_AREA = 50
LINE_KERNEL = 15             # Wider than outlines, narrower than solid boxes.
MIN_REGION_AREA = 1000
SNAP_PX = 20                 # About 0.5 cm.
```

Implement these functions exactly as specified.

**`order_corners(pts)`**
- Input: a float32 array of shape (4, 2).
- Return the points as top-left, top-right, bottom-right, bottom-left:
  - `s = pts.sum(axis=1)` and `d = pts[:, 1] - pts[:, 0]`.
  - TL = `argmin(s)`, BR = `argmax(s)`, TR = `argmin(d)`, BL = `argmax(d)`.

**`find_paper_corners(frame_bgr)`**
1. `_, mask = detect_paper(frame_bgr)`. Import it from `paper_detector`.
2. Find external contours and take the largest.
3. Return `None` if there are no contours, or if the largest has area `< 0.2 * h * w`.
4. Simplify with `approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)`.
5. Return `None` unless `len(approx) == 4`.
6. Otherwise return `order_corners(approx.reshape(4, 2).astype(np.float32))`.

**`flatten(gray, corners)`**
1. `dst = np.float32([[0, 0], [FLAT_W - 1, 0], [FLAT_W - 1, FLAT_H - 1], [0, FLAT_H - 1]])`.
2. `H = cv2.getPerspectiveTransform(corners, dst)`.
3. Return `cv2.warpPerspective(gray, H, (FLAT_W, FLAT_H)), H`.

**`find_regions(flat)`**

Returns `(flat_map, regions, ink)`.

1. Build the ink mask:
   - `blurred = cv2.GaussianBlur(flat, (5, 5), 0)`.
   - `adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 10)`.
   - `ink = adaptive | np.where(blurred < DARK_LEVEL, 255, 0).astype(np.uint8)`.

   Add the comment `# Adaptive alone hollows out large solid boxes, so add a global dark test.`
2. Zero the ink mask within `BORDER_PX` of all four edges.
3. Remove specks:
   - Run `connectedComponentsWithStats(ink, connectivity=8)`.
   - Build `small = stats[:, cv2.CC_STAT_AREA] < SPECK_AREA` and set `small[0] = False`.
   - Clear them with `ink[small[labels]] = 0`.
4. Find solid regions:
   - `opened = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((LINE_KERNEL, LINE_KERNEL), np.uint8))`.
   - Every connected component of `opened` with area `>= MIN_REGION_AREA` is a region of kind `"solid"`.
5. Find outlined regions:
   - `closed = cv2.dilate(ink, np.ones((3, 3), np.uint8))` and `white = np.where(closed == 0, 255, 0).astype(np.uint8)`.
   - Run `connectedComponentsWithStats(white, connectivity=4)`.
   - Skip label 0, skip any component whose bounding box touches an image edge (`x == 0` or `y == 0` or `x + w == FLAT_W` or `y + h == FLAT_H`; this is the paper background), and skip any with area `< MIN_REGION_AREA`.
   - The rest are kind `"outlined"`.
6. Paint `flat_map = np.zeros((FLAT_H, FLAT_W), np.uint16)`:
   - Paint all outlined regions first, then all solid regions, using temporary IDs 1..K.
   - A solid region painted second wins where they overlap.
7. Number the regions left to right:
   - For each temporary ID, compute the centroid from the painted pixels (`ys, xs = np.nonzero(flat_map == t)`, giving `(xs.mean(), ys.mean())`).
   - Sort by `(cx, cy)`.
   - Build a `lut = np.zeros(K + 1, np.uint16)` mapping temporary ID to final ID 1..K, then set `flat_map = lut[flat_map]`.
   - Build `regions` as a list, sorted by ID, of dicts:

     ```python
     {
         "id": int,
         "kind": "solid" | "outlined",
         "centroid": [float, float],
         "bbox": [x, y, w, h],
         "area": int,
     }
     ```

     All values are plain Python types so they are JSON-safe. Compute these before snapping.
8. Snap gaps so a fingertip on a line or near a box still maps:

   ```python
   for _ in range(SNAP_PX):
       grown = cv2.dilate(flat_map, np.ones((3, 3), np.uint8))
       flat_map = np.where(flat_map == 0, grown, flat_map)
   ```

9. Return `flat_map, regions, ink`.

**`region_outlines(flat_map, H_inv)`**
- Returns a dict of region ID → int32 contour in camera pixels.
- For each ID in `np.unique(flat_map)` except 0:
  1. Find the external contours of `(flat_map == id).astype(np.uint8)` and take the largest.
  2. Map it with `cv2.perspectiveTransform(c.reshape(-1, 1, 2).astype(np.float32), H_inv)`.
  3. Store the result as int32.

**`build_calibration(frames)`**
- `frames` is a list of BGR images, all the same size.
- `reference = np.median(np.stack(frames), axis=0).astype(np.uint8)`.
- `corners = find_paper_corners(reference)`. If it is `None`, raise `ValueError("Can't see the whole paper (need 4 clear corners).")`.
- `flat, H = flatten(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), corners)`.
- `flat_map, regions, _ = find_regions(flat)`. If `regions` is empty, raise `ValueError("No black boxes or outlines found on the paper.")`.
- `H_inv = np.linalg.inv(H)`, with `h, w = reference.shape[:2]`.
- `key_map = cv2.warpPerspective(flat_map, H_inv, (w, h), flags=cv2.INTER_NEAREST)`. Add the comment `# Nearest only: blending would invent region IDs.`
- Return this dict:

  ```python
  {
      "key_map": key_map,
      "flat_map": flat_map,
      "H": H,
      "H_inv": H_inv,
      "corners": corners,
      "frame_size": (w, h),
      "regions": regions,
      "outlines": region_outlines(flat_map, H_inv),
      "reference": reference,
      "timestamp": time.time(),
  }
  ```

**`region_at(cal, x_norm, y_norm)`**
- `w, h = cal["frame_size"]`.
- Convert to pixels with `int(x_norm * w)` and `int(y_norm * h)`, then clamp to `[0, w-1]` and `[0, h-1]`.
- Return `int(cal["key_map"][y, x])`.

**`save_calibration(cal, directory)`**
- Create the directory: `Path(directory).mkdir(parents=True, exist_ok=True)`.
- Write `calibration.npz` with `np.savez_compressed`. It holds `key_map`, `flat_map`, `H`, `H_inv`, `corners`, `frame_size=np.array(cal["frame_size"])`, `reference`, and `timestamp=np.array(cal["timestamp"])`.
- Write `regions.json` containing `cal["regions"]` with `json.dump(..., indent=2)`.

**`load_calibration(directory, frame_shape)`**
- Return `None` if `calibration.npz` or `regions.json` is missing.
- Return `None` if `tuple(int(v) for v in data["frame_size"]) != (frame_shape[1], frame_shape[0])`.
- Otherwise rebuild the same dict as `build_calibration` returns:
  - `frame_size` becomes a tuple and `timestamp` a float.
  - `regions` comes from the JSON file.
  - `outlines` is recomputed with `region_outlines`.

**`region_color(region_id)`**
- `rng = np.random.default_rng(region_id)`.
- Return `tuple(int(v) for v in rng.integers(64, 256, 3))`.

**`draw_calibration(frame, cal, active_ids)`**
1. `overlay = frame.copy()`.
2. For each ID and contour in `cal["outlines"]`, fill the contour on `overlay` with `(0, 255, 255)` if the ID is in `active_ids`, otherwise with `region_color(id)`.
3. `frame = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)`.
4. Draw every outline with `cv2.polylines(frame, [contour], True, (255, 255, 255), 1)`.
5. Put the ID text (`cv2.FONT_HERSHEY_SIMPLEX`, 0.4, white) at the contour's mean point.
6. Return `frame`.

**`render_flat_regions(flat_map, regions)`**
- Return a BGR image of size FLAT_H × FLAT_W.
- Pixels with ID 0 are dark grey `(40, 40, 40)`. Every other pixel takes `region_color(id)`.
- Draw each region's ID with `cv2.putText` at its `centroid`, using scale 1.0, black, thickness 2.

## Step 2 — `calibrate_image.py`

This is a command-line debug tool, used as `python calibrate_image.py IMAGE [OUT]`. Read `sys.argv` directly; no argparse.

1. Read the image with `cv2.imread`. If that returns `None`, print `Can't read IMAGE` and exit with code 1.
2. `OUT` defaults to `<image path without extension>_debug.png`.
3. `corners = find_paper_corners(img)`. If it is `None`:
   - Write `np.hstack([img, cv2.cvtColor(detect_paper(img)[1], cv2.COLOR_GRAY2BGR)])` to `OUT`.
   - Print `No paper found; wrote OUT`.
   - Exit with code 1.
4. Otherwise run `flatten` on the grayscale image, then `find_regions`.
5. Build `debug = np.hstack([cv2.cvtColor(flat, cv2.COLOR_GRAY2BGR), cv2.cvtColor(ink, cv2.COLOR_GRAY2BGR), render_flat_regions(flat_map, regions)])` and resize it by 0.5 with `cv2.resize(debug, None, fx=0.5, fy=0.5)`.
6. Write the result to `OUT`.
7. Print `N regions`, then one line per region: `id kind centroid area`. Finally print `wrote OUT`.

## Step 3 — wire into `phone_server.py`

Add these imports:

```python
from calibration import (
    FINGERTIPS,
    build_calibration,
    draw_calibration,
    load_calibration,
    region_at,
    save_calibration,
)
```

Add these globals next to the existing ones:

```python
CALIBRATION_DIR = BASE_DIR / "calibration"
SAMPLES_DIR = BASE_DIR / "samples"
CALIBRATION_FRAMES = 15

calibration = None
calibration_checked = False
calibrating = False
calibration_frames = []
latest_raw = None
latest_fingers = {}
status_text = "Press C to calibrate."
```

### In `receive_frame`

1. Extend the `global` line with all the new mutable names.
2. Keep the decode step, `detect_paper`, and the landmarker block as they are.
3. Then, **before** drawing the hand landmarks, do all calibration work inside one `with frame_lock:` block:
   - Set `latest_raw = frame`.
   - If `not calibration_checked`:
     - Set `calibration = load_calibration(CALIBRATION_DIR, frame.shape)` and `calibration_checked = True`.
     - If a calibration was loaded, set `status_text = f"Loaded calibration: {len(calibration['regions'])} regions."`.
   - If `calibrating`:
     - If `result.hand_landmarks` is non-empty: clear `calibration_frames` and set `status_text = "Calibrating: keep your hands out of view."`.
     - Otherwise append `frame` to `calibration_frames`.
     - Once there are `CALIBRATION_FRAMES` frames:
       - `try`: build the calibration, `save_calibration` it to `CALIBRATION_DIR`, assign it to `calibration`, and set `status_text = f"Calibrated: {n} regions."`.
       - `except ValueError as error`: set `status_text = f"Calibration failed: {error} Press C to retry."`.
       - `finally`: set `calibrating = False` and clear `calibration_frames`.
   - Set `cal = calibration if not calibrating else None`.
4. Outside the lock:
   - If `cal` is set:
     - For the **first** hand only (if any), build `fingers = {name: region_at(cal, hand[i].x, hand[i].y) for name, i in FINGERTIPS.items()}`. Otherwise `fingers = {}`.
     - Set `annotated = draw_calibration(annotated, cal, {r for r in fingers.values() if r})`.
   - Otherwise set `fingers = {}`.
5. Then draw the hand landmarks, as the code already does, so they sit on top of the overlay.
6. In the final `with frame_lock:` block, also set `latest_fingers = fingers`.

### In the `__main__` loop

1. Under the lock, also copy `status_text` and `dict(latest_fingers)`.
2. Before `imshow`:
   - Draw `status_text` at `(5, 15)`, scale 0.45, colour `(0, 255, 255)`, thickness 1.
   - If there are fingers, draw `"  ".join(f"{name[0]}:{rid or '-'}" for name, rid in fingers.items())` at `(5, frame.shape[0] - 8)` in the same style.
3. Store `key = cv2.waitKey(1) & 0xFF` once and branch on it:
   - `ord("q")` → break, as before.
   - `ord("c")` → under the lock, set `calibrating = True`, clear `calibration_frames`, and set `status_text = "Calibrating: keep your hands out of view."`.
   - `ord("s")` → under the lock, copy `latest_raw`. If it is not `None`:
     - `SAMPLES_DIR.mkdir(exist_ok=True)`.
     - Write it to `SAMPLES_DIR / f"frame_{time.strftime('%Y%m%d_%H%M%S')}.jpg"` with `cv2.imwrite(str(path), raw)`.
     - Print the path and set `status_text = f"Saved {path.name}"` under the lock.
4. Update the startup print to `"Waiting for phone camera frames. C = calibrate, S = save frame, Q = quit."`.

## Step 4 — `.gitignore` and README

- **`.gitignore`:** append the line `calibration/`. Do not ignore `samples/`, because real photos will become test fixtures.
- **`README.md`:** add a `## Calibration` section before `## Tests`. Explain:
  - The template is black solid boxes or black outlines on white Letter paper, landscape.
  - Press C with your hands out of view.
  - Regions are numbered left to right.
  - S saves a frame to `samples/`.
  - `python calibrate_image.py samples/<file>.jpg` writes a `_debug.png` image showing the flattened paper, the ink mask and the numbered regions.

Keep it under 15 lines.

## Step 5 — `tests/test_calibration.py`

Use the same `sys.path` header as `tests/test_server.py`. Add these helpers:

```python
STRAIGHT = np.float32([[60, 40], [580, 40], [580, 442], [60, 442]])
TILTED = np.float32([[80, 30], [590, 55], [570, 450], [50, 420]])
BOXES = [(150, 250, 310, 600), (350, 250, 510, 600), (550, 250, 710, 600), (750, 250, 910, 600)]


def make_sheet(draw, quad):
    # Draw on a canonical white sheet, then warp it onto a dark 640x480 desk.
    paper = np.full((850, 1100), 255, np.uint8)
    draw(paper)
    src = np.float32([[0, 0], [1099, 0], [1099, 849], [0, 849]])
    M = cv2.getPerspectiveTransform(src, quad)
    warped = cv2.warpPerspective(cv2.cvtColor(paper, cv2.COLOR_GRAY2BGR), M, (640, 480))
    inside = cv2.warpPerspective(np.full((850, 1100), 255, np.uint8), M, (640, 480))
    canvas = np.full((480, 640, 3), 40, np.uint8)
    canvas[inside > 0] = warped[inside > 0]
    return canvas, M


def solid(paper):
    for x0, y0, x1, y1 in BOXES:
        cv2.rectangle(paper, (x0, y0), (x1, y1), 0, -1)


def outlined(paper):
    for x0, y0, x1, y1 in BOXES:
        cv2.rectangle(paper, (x0, y0), (x1, y1), 0, 8)


def piano(paper):
    # One octave C..B: white keys 100 wide from x=200, black keys over boundaries.
    cv2.rectangle(paper, (200, 200), (900, 650), 0, 10)
    for x in range(300, 900, 100):
        cv2.line(paper, (x, 200), (x, 650), 0, 10)
    for x in (300, 400, 600, 700, 800):
        cv2.rectangle(paper, (x - 30, 200), (x + 30, 470), 0, -1)


def at(cal, M, x, y):
    u, v = cv2.perspectiveTransform(np.float32([[[x, y]]]), M)[0, 0]
    return region_at(cal, u / 640, v / 480)
```

Write these tests, all in one `CalibrationTests(unittest.TestCase)`:

1. **`test_solid_boxes`:** `build_calibration([make_sheet(solid, STRAIGHT)[0]])` gives 4 regions. Every `kind` is `"solid"`, and IDs 1..4 have strictly increasing centroid x.
2. **`test_outlined_boxes`:** same as test 1, with `outlined`, and every `kind` is `"outlined"`.
3. **`test_piano_is_chromatic`:** the `piano` sheet gives 12 regions, and the kinds in ID order are exactly `O S O S O O S O S O S O` (O = outlined, S = solid).
4. **`test_tilted`:** the `solid` sheet with `TILTED` gives 4 regions.
5. **`test_region_lookup`:** on the straight solid sheet (keep `M`):
   - `at(cal, M, 430, 425) == 2`, the centre of box 2.
   - `at(cal, M, 325, 425)` is in `{1, 2}`, a gap within snap distance.
   - `at(cal, M, 550, 120) == 0`, plain paper far from any box.
6. **`test_save_load_roundtrip`:** inside `tempfile.TemporaryDirectory()`:
   - Save, then load with `(480, 640, 3)`. The loaded `key_map` is `np.array_equal` to the original, and the `regions` are equal.
   - Loading with `(240, 320, 3)` returns `None`.
7. **`test_no_paper_raises`:** `build_calibration([np.full((480, 640, 3), 40, np.uint8)])` raises `ValueError`.

## Verification (done criteria)

Python: `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe`. Install nothing.

1. `<python> -m unittest discover -s tests -t . -v` passes all tests: 6 old and 7 new.
2. Write a piano sheet to a temporary file and run the debug tool on it. It prints `12 regions`, and the `_debug.png` file exists:

   ```
   <python> -c "import cv2,sys; sys.path.insert(0,'tests'); from test_calibration import make_sheet, piano, STRAIGHT; cv2.imwrite('piano_test.jpg', make_sheet(piano, STRAIGHT)[0])"
   <python> calibrate_image.py piano_test.jpg
   ```

   Delete `piano_test.jpg` and `piano_test_debug.png` afterwards, and do not commit them.
3. `<python> -c "import phone_server"` exits with code 0.
4. `git diff --stat 3e0f1a1` lists only in-scope files.

## STOP conditions

- If a synthetic test fails, you may tune only these constants: `DARK_LEVEL`, `LINE_KERNEL`, `MIN_REGION_AREA`, `BORDER_PX`, and the adaptive `C` / `blockSize`. Make at most 3 tuning attempts.
- If tests still fail after that, STOP. Report which test fails, the region count and kinds it got, and what you tried.
- Do not change the test expectations to make them pass.
- If `cv2.dilate` or `cv2.warpPerspective` rejects uint16 input, STOP and report the error verbatim.

## Maintenance note

- **Plan 003** adds a stillness check, a "camera moved" watcher, and smoothing at region edges across frames. It will touch `receive_frame`'s calibration block and `region_at`'s callers.
- **The paper finder is the weak point.** `find_paper_corners` reuses the HSV white mask from `paper_detector.py`, so a light-coloured desk will confuse it; that is a known, deferred issue. ArUco corner markers are the long-term replacement.
- **Real photos** from `samples/` should become fixtures in `tests/` once the user takes them (normal light, dim light, slight tilt).
