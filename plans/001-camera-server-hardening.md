# 001 — Camera server hardening + test baseline

- **Written against:** commit `6c76881` (repo `CongAlex/Instrument-Translation-Camera`)
- **Status:** TODO
- **Effort:** S
- **Drift check:** before starting, run `git diff 6c76881 -- phone_server.py paper_detector.py requirements.txt`. If it shows changes, STOP and report back.

## Why

The Flask server in `phone_server.py` receives JPEG frames from a phone, runs paper detection and MediaPipe hand tracking on them, and displays the results in OpenCV windows. It has six small defects:

1. **No request size limit.** `/frame` reads the whole body into memory (`request.get_data()`). The server is reachable through a public tunnel, so anyone can send it an arbitrarily large body.
2. **Unneeded CORS.** `CORS(app)` allows every origin to call the server. The page is served by the same server, so CORS is not needed.
3. **Unsafe hand-landmarker calls.** Flask runs with `threaded=True`, and one shared `HandLandmarker` in VIDEO mode is called with no lock. VIDEO mode requires strictly increasing timestamps. Two requests in the same millisecond, or out of order, make MediaPipe raise an error, which returns a 500.
4. **Annotated frame sent to hand tracking.** `detect_paper` draws a green outline onto the frame passed in, and that annotated frame then goes to MediaPipe.
5. **Working-directory-relative paths.** The model path and the static file paths only work when the server is started from the repo root.
6. **Q can't quit before the first frame.** Until the first frame arrives, no OpenCV window exists, so the "press Q to quit" key is never received.

There are also no tests, and `requirements.txt` has no version pins. `numpy` is imported but not listed.

## Conventions to match

Plain functions, module-level globals, 4-space indent, short `# Comment.` lines ending in a period, and line-wrapped call arguments as in the existing code. No type hints, no classes, and no new dependencies.

## Scope

- **In scope:** `phone_server.py`, `paper_detector.py`, `requirements.txt`, new `tests/test_server.py`, new `tests/__init__.py` (empty), `README.md` (one short "Tests" section only).
- **Out of scope (do not touch):** `phone_camera.js/.html/.css`, `models/`, `main.py`, `.gitignore`. Do NOT change `host="0.0.0.0"`, because the transport is being redesigned separately. Do NOT add classes, logging frameworks, or refactor anything beyond the steps below.

## Steps

### 1. `paper_detector.py`: stop changing the caller's frame

Inside `detect_paper`, draw onto a copy. Add `frame = frame.copy()` as the first line of the function body. Keep the return value `(frame, mask)` unchanged, so existing callers keep working.

### 2. `phone_server.py`: absolute paths

Add `from pathlib import Path` and `BASE_DIR = Path(__file__).resolve().parent`.

- Set `model_path = str(BASE_DIR / "models" / "hand_landmarker.task")`.
- In the three `send_from_directory(".", ...)` calls, replace `"."` with `BASE_DIR`.

### 3. `phone_server.py`: remove CORS and add a size limit

- Delete `from flask_cors import CORS` and `CORS(app)`.
- After `app = Flask(__name__)`, add `app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024` with a comment along the lines of `# Frames are small JPEGs; reject anything larger.`

Flask then returns 413 automatically for larger bodies.

### 4. `phone_server.py`: serialise the landmarker

- Add globals `landmarker_lock = threading.Lock()` and `last_timestamp_ms = 0`.
- In `receive_frame`, add `last_timestamp_ms` to the `global` line.
- Replace the timestamp and `detect_for_video` lines with:

```python
    # VIDEO mode needs strictly increasing timestamps and is not thread-safe.
    with landmarker_lock:
        timestamp_ms = max(int(time.monotonic() * 1000), last_timestamp_ms + 1)
        last_timestamp_ms = timestamp_ms
        result = hand_landmarker.detect_for_video(mp_image, timestamp_ms)
```

### 5. `phone_server.py`: send the clean frame to MediaPipe

Change `frame, mask = detect_paper(frame)` to `annotated, mask = detect_paper(frame)`.

- Build `rgb_frame` from `frame`, which is now unannotated.
- Draw landmarks onto `annotated`: `annotated = draw_hand_landmarks(annotated, result)`.
- Store `latest_frame = annotated`.

### 6. `phone_server.py`: make Q work before the first frame

In the `__main__` loop, when `frame is None`, show a placeholder instead of nothing:

```python
            if frame is None:
                frame = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.imshow("Phone Camera Feed", frame)
```

This replaces the existing `if frame is not None:` block. Leave the mask block as is.

### 7. `requirements.txt`: pin versions

Replace the file contents with:

```
opencv-python==5.0.0.93
mediapipe==1.1.1
numpy==2.5.4
flask==3.1.3
```

`flask-cors` is removed.

### 8. Tests

Use stdlib `unittest` only, and do not install pytest. Create `tests/__init__.py` (empty) and `tests/test_server.py`.

The tests must run from the repo root with `python -m unittest discover -s tests -t .`. Add the repo root to `sys.path` at the top of the test file (`sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`) before importing `phone_server` and `paper_detector`.

Write these tests:

- `test_detect_paper_does_not_mutate_input`: make a 240×320 black image with a white 200×150 rectangle drawn by `cv2.rectangle(..., -1)`, keep a `.copy()`, and call `detect_paper`. Assert that the input still equals the copy (`np.array_equal`) and that the returned frame differs from it (the outline was drawn).
- `test_index_served`: `phone_server.app.test_client().get("/")` returns status 200.
- `test_invalid_frame_rejected`: POST `b"not a jpeg"` to `/frame` and expect 400.
- `test_oversized_frame_rejected`: POST `b"\0" * (3 * 1024 * 1024)` to `/frame` and expect 413.
- `test_valid_frame_accepted`: encode the synthetic image with `cv2.imencode(".jpg", img)[1].tobytes()`, POST it, and expect 200. Then check that `phone_server.latest_frame` is not None.
- `test_timestamps_strictly_increase`: send two valid frames back to back and assert `phone_server.last_timestamp_ms` increased each time. Record the value after the first POST and compare it after the second.

### 9. README

Add a `## Tests` section before `## Notes`, containing one sentence and the command `python -m unittest discover -s tests -t .`.

## Verification (done criteria)

The Python to use is `C:/Users/entit/projects/Instrument-Translation/.venv/Scripts/python.exe`. Do not install anything into it.

1. `<python> -m unittest discover -s tests -t . -v` passes all six tests. Run it from the worktree root.
2. `<python> -c "import ast,sys; [ast.parse(open(f).read()) for f in ['phone_server.py','paper_detector.py']]"` exits with code 0.
3. `git grep -n "flask_cors\|CORS(" -- '*.py' requirements.txt` prints nothing.
4. `git diff --stat` lists only the in-scope files.

## STOP conditions

- If importing `phone_server` fails because of something other than your edits (for example, the model fails to load), STOP and report the error verbatim.
- If any test needs more than the code changes listed above to pass, STOP and report back. Do not improvise refactors.

## Maintenance note

Plan 002 (calibration and key map) will replace `detect_paper`'s drawing behaviour and add geometry output. The transport redesign (local HTTPS / WebSocket, LIVE_STREAM mode) will replace the lock and timestamp logic, but the strictly-increasing rule still applies in LIVE_STREAM mode.
