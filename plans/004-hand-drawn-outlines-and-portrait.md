# 004 — Hand-drawn outlines and portrait paper

- **Written against:** commit `5545349` (on `main`)
- **Status:** TODO
- **Effort:** S
- **Drift check:** run `git diff 5545349 -- calibration.py tests/test_calibration.py`. It must print nothing; otherwise STOP and report.

## Why

The user's first real photo is `samples/frame_20261029_212115.jpg`: a 240×320 **portrait** phone frame of a pen-drawn rectangle on portrait lined paper, with a pen lying on the paper. Calibration found only the pen (as a `"solid"` region) and missed the drawn box. There are two causes.

1. **Gaps in the outline.** A pen line is about 1 camera pixel wide. Once the image is flattened and enlarged about 4.5×, a 1-pixel gap in the line becomes roughly a 5-pixel gap. In `calibration.find_regions`, the outlined-region pass only closes gaps with a 3×3 dilation, so the white inside the box leaks out to the paper background. It is then discarded as background.

   This has been verified: adding a `MORPH_CLOSE` step with a kernel of 7 or more before that dilation recovers the box as `"outlined"`, with its centroid near (273, 215).
2. **Portrait paper.** `flatten` always warps to a landscape 1100×850 image, so portrait paper gets stretched.

The pen being detected as a `"solid"` region is correct behaviour. Do not change it.

## Current code (`calibration.py`)

```python
FLAT_W, FLAT_H = 1100, 850   # US Letter landscape, 100 px per inch.
...
def flatten(gray, corners):
    dst = np.float32(
        [[0, 0], [FLAT_W - 1, 0], [FLAT_W - 1, FLAT_H - 1], [0, FLAT_H - 1]]
    )
    H = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(gray, H, (FLAT_W, FLAT_H)), H
...
    # Outlined regions: white areas enclosed by ink.
    closed = cv2.dilate(ink, np.ones((3, 3), np.uint8))
```

`find_regions` and `render_flat_regions` also use `FLAT_W` / `FLAT_H` directly: for the zero-filled map, the edge-touch check, and the output image size. `corners` are ordered TL, TR, BR, BL.

## Scope

- **In scope:**
  - `calibration.py`
  - `tests/test_calibration.py`
  - new `tests/fixtures/pen_box_portrait.jpg`, a byte-for-byte copy of `samples/frame_20261029_212115.jpg`
- **Out of scope:** everything else. Do not change any other constant, and do not change how `"solid"` regions are detected.

## Steps

1. **Add a gap constant.** Add `GAP_KERNEL = 11            # Closes small breaks in hand-drawn outlines.` next to the other constants.
2. **Close gaps in the outlined pass.** In `find_regions`, replace the `closed = ...` line with:

   ```python
   closed = cv2.morphologyEx(
       ink, cv2.MORPH_CLOSE, np.ones((GAP_KERNEL, GAP_KERNEL), np.uint8)
   )
   closed = cv2.dilate(closed, np.ones((3, 3), np.uint8))
   ```
3. **Make `flatten` follow the paper's orientation.**
   - Compute `tl, tr, br, bl = corners`.
   - `width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2`, and the same for `height` using the sides (TL to BL and TR to BR).
   - Set `w, h = (FLAT_H, FLAT_W) if height > width else (FLAT_W, FLAT_H)`.
   - Build `dst` from `w` and `h`, and warp to `(w, h)`.
   - Add the comment `# Portrait paper flattens to a portrait image.`
4. **Use the flattened image's own size.**
   - In `find_regions`, set `fh, fw = flat.shape` at the top. Use `fh` and `fw` instead of `FLAT_H` and `FLAT_W` everywhere in that function.
   - In `render_flat_regions`, use `flat_map.shape` for the output size.
   - After this step, `FLAT_W` and `FLAT_H` appear only in the constants and in `flatten`.
5. **Add the fixture.** Copy `samples/frame_20261029_212115.jpg` to `tests/fixtures/pen_box_portrait.jpg`, using `shutil` or `cp`.
6. **Add tests** to `CalibrationTests`:
   - `test_hand_drawn_box_portrait`:
     - `build_calibration([cv2.imread(<path>)])`, where the path is built from the test file's directory.
     - Assert that the regions include exactly one `"outlined"` and at least one `"solid"`.
     - Assert that the `flat_map` shape is `(1100, 850)` (portrait).
   - `test_landscape_stays_landscape`: the straight solid synthetic sheet still gives `flat_map.shape == (850, 1100)`.

## Verification

Python: `.venv/Scripts/python.exe` in the repo root. Install nothing.

1. `python -m unittest discover -s tests -t .` runs 15 tests and they all pass.
2. `python calibrate_image.py tests/fixtures/pen_box_portrait.jpg <scratch>/out.png` prints `2 regions`: one outlined, one solid. Write the output image outside the repo.
3. `git diff --stat 5545349` lists only the in-scope files.

## STOP conditions

- If an existing synthetic test (especially the piano test) fails after step 2, try `GAP_KERNEL = 7` once.
- If tests still fail, STOP and report which test failed and what it got.

## Maintenance note

- A bigger `GAP_KERNEL` closes wider breaks, but it can also merge two outlined regions whose white interiors are narrower than the kernel. Keep it well below the width of the smallest key.
- Higher camera resolution (`phone_camera.js` asks for 320×240) would make pen lines thicker in pixels. That decision is pending with the user.
