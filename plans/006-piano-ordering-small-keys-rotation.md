# 006 — Piano key ordering, small keys, phone rotation

- **Written against:** commit `0c079cf` (on `main`)
- **Status:** TODO
- **Effort:** M
- **Drift check:** run `git diff 0c079cf -- calibration.py phone_server.py phone_camera.js tests/`. It must print nothing; otherwise STOP and report.

## Why

1. **Piano keys must be numbered along the keyboard.** Today, `find_regions` in `calibration.py` sorts regions by `(centroid x, centroid y)` in flattened paper coordinates. A keyboard drawn sideways on the sheet therefore gets non-chromatic IDs.

   A piano carries its own orientation: the black keys (`"solid"` regions) sit toward the *back* of the keyboard, and the white keys' L/T-shaped masses (`"outlined"` regions) sit toward the front. If "up" means "toward the black keys", then low-to-high runs left to right when the keyboard is viewed with the black keys at the top. This is the standard piano picture.

   White keys with notches already work. An outlined white key's region excludes the black-key pixels painted over it, which gives the L/T shape. Do not change that logic.
2. **Small keys.** The user will draw smaller keys over time. `MIN_REGION_AREA = 1000` canonical px² (about 0.65 cm²) is too strict for keys a few mm wide.
3. **Phone rotation.** `phone_camera.js` sets `canvas.width/height` once, at Start, from `video.videoWidth/Height`. When the iPhone rotates, the video becomes landscape but the canvas stays portrait, so the server keeps receiving portrait frames. The server also never notices when the frame size stops matching the calibration's `frame_size`.

## Current code (read the files fully first)

**`calibration.py`**
- Constants include `MIN_REGION_AREA = 1000`.
- In `find_regions`, after painting the temporary IDs, the numbering block is:

  ```python
  # Number left to right.
  cents = {}
  for t in kinds:
      ys, xs = np.nonzero(flat_map == t)
      cents[t] = (xs.mean(), ys.mean())
  order = sorted(kinds, key=lambda t: cents[t])
  ```

  It is followed by the `lut` / `regions` build, which uses `kinds[old]` and `cents[old]`.

**`phone_camera.js`**
- In the Start handler: `canvas.width = video.videoWidth; canvas.height = video.videoHeight;`, followed by setting `resolution.textContent` to `` `Actual resolution: ${canvas.width} × ${canvas.height}` ``.
- `sendFrame()` draws with `context.drawImage(video, 0, 0, canvas.width, canvas.height)`.

**`phone_server.py`, `process_frame(frame)`**
- Inside `with frame_lock:` it handles `calibration_checked` / `load_calibration` and the `calibrating` block.
- It then sets `cal = calibration if not calibrating else None`.
- `calibration["frame_size"]` is a `(w, h)` tuple.

## Scope

- **In scope:** `calibration.py`, `phone_camera.js`, `phone_server.py`, `tests/test_calibration.py`.
- **Out of scope:** everything else, including the snapping, painting and threshold logic. The only constant change allowed is the one in step 2.

## Steps

### 1. Keyboard-aware ordering (`calibration.py`)

Add this module-level function, after `flatten`:

```python
def order_regions(cents, kinds):
    # Pianos: "up" points from the white keys toward the black keys; number
    # left to right with up at the top. Anything else: plain left to right.
    solid = [cents[t] for t in kinds if kinds[t] == "solid"]
    outlined = [cents[t] for t in kinds if kinds[t] == "outlined"]
    if solid and outlined:
        up = np.mean(solid, axis=0) - np.mean(outlined, axis=0)
        norm = np.linalg.norm(up)
        if norm > 5:
            ux, uy = up / norm
            rx, ry = -uy, ux
            return sorted(
                kinds,
                key=lambda t: (cents[t][0] * rx + cents[t][1] * ry,
                               -(cents[t][0] * ux + cents[t][1] * uy)),
            )
    return sorted(kinds, key=lambda t: cents[t])
```

Replace `order = sorted(kinds, key=lambda t: cents[t])` with `order = order_regions(cents, kinds)`, and change the comment above the block to `# Number along the keyboard (see order_regions).`

Sanity check of the maths, in image coordinates where y points down: `up = (0, -1)` gives `right = (1, 0)`. Do not change the signs.

### 2. Smaller keys (`calibration.py`)

Change `MIN_REGION_AREA = 1000` to `MIN_REGION_AREA = 300`, and add the comment `# About 0.2 cm²; allows small keys.`

### 3. Follow the phone's rotation (`phone_camera.js`)

At the start of the `try` block in `sendFrame()`, before `drawImage`, add:

```js
        // Follow phone rotation: the video swaps width and height.
        if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            resolution.textContent =
                `Actual resolution: ${canvas.width} × ${canvas.height}`;
        }
```

### 4. Notice a frame-size change (`phone_server.py`)

In `process_frame`, inside the first `with frame_lock:` block and just before `cal = calibration if not calibrating else None`, add:

```python
        frame_size = (frame.shape[1], frame.shape[0])
        if calibration is not None and calibration["frame_size"] != frame_size:
            calibration = None
            status_text = "Frame size changed (phone rotated?): press C to recalibrate."
```

The saved files on disk are left alone. Pressing C recalibrates and overwrites them.

### 5. Tests (`tests/test_calibration.py`)

Add a portrait quad and a sideways piano:

```python
PORTRAIT = np.float32([[170, 20], [470, 20], [470, 408], [170, 408]])


def make_portrait_sheet(draw, quad):
    # Draw a landscape layout, then turn the paper a quarter turn (portrait).
    paper = np.full((850, 1100), 255, np.uint8)
    draw(paper)
    paper = np.ascontiguousarray(np.rot90(paper))
    h, w = paper.shape
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    M = cv2.getPerspectiveTransform(src, quad)
    warped = cv2.warpPerspective(cv2.cvtColor(paper, cv2.COLOR_GRAY2BGR), M, (640, 480))
    inside = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (640, 480))
    canvas = np.full((480, 640, 3), 40, np.uint8)
    canvas[inside > 0] = warped[inside > 0]
    return canvas, M
```

Add these tests:

- **`test_sideways_piano_is_chromatic`**: `build_calibration([make_portrait_sheet(piano, PORTRAIT)[0]])` gives 12 regions, and the kinds in ID order are exactly `O S O S O O S O S O S O`. That is the same expectation as `test_piano_is_chromatic`.
- **`test_small_keys`**: draw a piano at 40% scale.
  - Write the drawing function `small_piano(paper)`. It is the same as `piano`, but every coordinate is computed as `int(400 + 0.4 * (v - 200))` for x and `int(300 + 0.4 * (v - 200))` for y, with the outline thickness at 5.
  - The black-key half-width becomes 12 instead of 30, and the black-key bottom maps through the same formula.
  - Assert 12 regions with the same kind pattern.
  - If this test cannot pass with only the step 2 change, see the STOP conditions.

The existing tests must keep passing unchanged, especially `test_piano_is_chromatic`.

## Verification

Use `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe` and install nothing.

1. `python -m unittest discover -s tests -t .` runs 19 tests, all passing.
2. `node --check phone_camera.js` exits with code 0. If node is missing, say so.
3. `python calibrate_image.py tests/fixtures/pen_box_portrait.jpg <scratch>/o.png` still prints `2 regions`. Write the output file outside the repo.
4. `git diff --stat 0c079cf` lists only the in-scope files.

## STOP conditions

- If `test_small_keys` fails, you may try `LINE_KERNEL = 11` once. Report what happens.
  - If it still fails, keep the test, mark it with `@unittest.expectedFailure` plus a comment giving the region count and kinds you observed, and report back.
  - Do not loosen any other test.
- If `test_piano_is_chromatic` or `test_sideways_piano_is_chromatic` fails, STOP and report the kinds that came out, in order.

## Maintenance note

- **The ordering rule assumes black keys sit toward the back of the keyboard.** A page that mixes standalone solid boxes and outlined boxes, but is not a piano, may get a rotated numbering. That is acceptable for now. A future "layout type" setting could force plain left-to-right.
- **Rotating the phone invalidates the calibration**, by design. The key map is tied to the frame size.
