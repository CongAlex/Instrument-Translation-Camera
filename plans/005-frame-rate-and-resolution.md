# 005 — Frame rate and 640×480 capture

- **Written against:** commit `b9ff427` (plan 004, on top of `5545349`).
- **Status:** TODO
- **Effort:** M
- **Depends on:** 004
- **Setup:** first run `git merge --ff-only b9ff427` in your worktree, then confirm that `git log --oneline -1` shows `b9ff427`. If either fails, STOP.

## Why

The user sees under 10 fps, and sometimes under 5. There are two causes, both in our code:

1. **The client caps itself at 10 fps.** `phone_camera.js` calls `setInterval(sendFrame, 100)`.
2. **Only one frame is in flight, and it waits for a full round trip.** A `sending` flag blocks new sends until the previous `fetch` returns. The round trip covers the phone, ngrok on the internet, the laptop, and then *all* the processing in `receive_frame` (`detect_paper`, MediaPipe, the calibration overlay) before the response goes back. So fps ≈ 1000 / round-trip time.

The user also wants 640×480 capture, which is currently 320×240.

## Current code (relevant parts)

**`phone_camera.js`:**
- Has globals `stream`, `timer`, `sending`, and `running`.
- `sendFrame()` returns early `if (!running || sending || video.readyState < 2 || !canvas.width || !canvas.height)`. It then sets `sending = true`, draws the video to the canvas, `toBlob` as JPEG 0.7, and POSTs to `/frame`. On success it calls `updateFps()`. In `finally` it sets `sending = false`.
- `getUserMedia` asks for `width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 15, max: 20 }`.
- `timer = setInterval(sendFrame, 100);` comes after the comment `// Attempt to send up to 10 frames per second.`
- `updateFps()` counts successful frames and every 500 ms writes `Sending FPS: x.x` to `#fps-label`. The bar is full at 15 fps, green at 12 or more, yellow at 6 or more.

**`phone_server.py`, `receive_frame()`:**
1. Decodes the body into `frame` and returns 400 if it is `None`.
2. Runs `detect_paper`, then the MediaPipe call inside `landmarker_lock` with strictly increasing timestamps.
3. Runs the calibration block under `frame_lock` (sets `latest_raw`, loads or builds the calibration).
4. Builds the fingertip lookup, the overlay and the landmarks.
5. Stores `latest_frame`, `latest_mask` and `latest_fingers` under `frame_lock`.
6. Returns `"OK", 200`.

The `__main__` block:
- starts `run_server` in a daemon thread;
- loops showing frames and drawing `status_text` at the top and the finger line at the bottom;
- handles the C, S and Q keys.

**`tests/test_server.py`:**
- `test_valid_frame_accepted` POSTs a JPEG and asserts that `phone_server.latest_frame` is not None.
- `test_timestamps_strictly_increase` POSTs twice and compares `phone_server.last_timestamp_ms`.

Read both files fully before editing.

## Scope

- **In scope:** `phone_camera.js`, `phone_server.py`, and `tests/test_server.py`. In the test file, only the two tests named above may change, as described in step 4.
- **Out of scope:** `calibration.py`, `paper_detector.py`, the HTML and CSS, the transport (keep plain HTTP POST; no WebSockets, no new dependencies), and the calibration logic itself.

## Steps

### 1. Server: answer immediately and process in the background

- **Move processing out of the request.** Move everything after the 400 check in `receive_frame` into a new function `process_frame(frame)`, unchanged apart from moving. The `global` declarations move with it.
- **New globals:**

  ```python
  pending_frame = None
  pending_lock = threading.Lock()
  pending_event = threading.Event()
  frames_received = 0
  process_ms = 0.0
  ```

- **`receive_frame`:**
  - Decode the frame and return 400 if it is `None`.
  - Then, under `pending_lock`:
    - set `pending_frame = frame`;
    - increment `frames_received`.
  - Call `pending_event.set()` and return `"OK", 200`.
  - Add a comment explaining that a newer frame replaces an unprocessed older one, so the server never falls behind.
- **New `process_pending()`:**
  - Under `pending_lock`, take `frame = pending_frame`, set `pending_frame = None`, and call `pending_event.clear()`.
  - If `frame` is `None`, return `False`.
  - Otherwise:
    - time `process_frame(frame)` with `time.perf_counter()`;
    - update `process_ms = 0.9 * process_ms + 0.1 * elapsed_ms`;
    - return `True`.
- **New `process_loop()`:**

  ```python
  while True:
      pending_event.wait(); process_pending()
  ```

- **In `__main__`:** start `threading.Thread(target=process_loop, daemon=True).start()` next to the server thread.
- **Receive FPS in the main display loop:**
  - Once per second, read `frames_received` under `pending_lock`.
  - Compute `rx_fps` from the difference to the previous reading.
  - Draw `f"rx {rx_fps:.1f} fps  proc {process_ms:.0f} ms"` at `(5, 32)`, in the same font and colour as the status text.

### 2. Client: 640×480 and up to 2 frames in flight

- **`getUserMedia` constraints:** `width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30 }`.
- **In-flight counter:**
  - Replace `let sending = false;` with `let inFlight = 0;` and `const MAX_IN_FLIGHT = 2;`.
  - In `sendFrame`, the guard becomes `inFlight >= MAX_IN_FLIGHT` instead of `sending`.
  - Increment `inFlight` where it used to set `sending = true`, and decrement it in `finally`.
- **Send rate:** change the interval to `setInterval(sendFrame, 33)` and the comment to `// Attempt to send up to 30 frames per second.`
- **Round-trip time:**
  - Measure `performance.now()` before and after the `fetch`.
  - Keep `let rttMs = 0;` and update it with `rttMs = 0.8 * rttMs + 0.2 * elapsed;` on success.
  - In `updateFps`, write `` `Sending FPS: ${fps.toFixed(1)} · RTT ${rttMs.toFixed(0)} ms` ``.
- **FPS bar:** full at 30 fps, green at 20 or more, yellow at 10 or more. In `resetFps`, also reset `rttMs = 0`.
- **Stop button:** set `inFlight` is not reset there, since in-flight requests finish on their own. Leave the existing `running` checks in place.

### 3. Size limit

Keep `MAX_CONTENT_LENGTH` at 2 MB, which is plenty for a 640×480 JPEG at quality 0.7. Don't change it.

### 4. Tests (`tests/test_server.py`)

Only these two tests change:
- **`test_valid_frame_accepted`:** after the POST returns 200, call `phone_server.process_pending()` and assert it returns `True`. Then assert that `latest_frame` is not None.
- **`test_timestamps_strictly_increase`:** call `process_pending()` after each POST.

Add two new tests:
- **`test_newer_frame_replaces_pending`:** POST twice without processing, then assert that `process_pending()` returns `True` once and `False` on a second call.
- **`test_frame_counter`:** `frames_received` increases by 2 after 2 valid POSTs.

## Verification

Use `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe` and install nothing.

1. `python -m unittest discover -s tests -t .` runs 17 tests, all passing.
2. `python -c "import phone_server"` exits with code 0.
3. Check `phone_camera.js` with `node --check phone_camera.js` if node is available; otherwise say that you skipped it.
4. `git diff --stat b9ff427` lists only the in-scope files.

## STOP conditions

If moving the body into `process_frame` needs anything beyond moving code and adjusting `global` statements, STOP and report.

## Maintenance note

- **Reading the new numbers:**
  - If phone RTT is high but `proc` is low, the network or tunnel is the bottleneck. The next decision is transport: LAN HTTPS (mkcert) or a different tunnel.
  - If `proc` is above about 30 ms, the processing is the bottleneck.
- **Load on the laptop:** 640×480 roughly quadruples the JPEG size and MediaPipe's input. Watch `proc`.
