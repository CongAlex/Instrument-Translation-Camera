import argparse
import os
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from flask import Flask, request, send_from_directory
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from calibration import (
    FINGERTIPS,
    INK_RATIO,
    LINE_KERNEL,
    build_calibration,
    draw_calibration,
    load_calibration,
    rebuild_calibration,
    region_at,
    save_calibration,
)
from paper_detector import detect_paper

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
# Frames are small JPEGs; reject anything larger.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
# Always revalidate the page and script so phones pick up changes.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

latest_frame = None
latest_mask = None
frame_lock = threading.Lock()
landmarker_lock = threading.Lock()
last_timestamp_ms = 0

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
SETTINGS_WINDOW = "Calibration settings"
ink_ratio_setting = INK_RATIO
line_kernel_setting = LINE_KERNEL

pending_frame = None
pending_lock = threading.Lock()
pending_event = threading.Event()
frames_received = 0
process_ms = 0.0

# Initialize MediaPipe Hand Landmarker.
model_path = str(BASE_DIR / "models" / "hand_landmarker.task")

base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.HandLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2,
)

hand_landmarker = vision.HandLandmarker.create_from_options(options)


def draw_hand_landmarks(frame, result):
    height, width, _ = frame.shape

    connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    for hand_landmarks in result.hand_landmarks:
        # Draw connections between landmarks.
        for connection in connections:
            start = hand_landmarks[connection.start]
            end = hand_landmarks[connection.end]

            start_point = (
                int(start.x * width),
                int(start.y * height),
            )
            end_point = (
                int(end.x * width),
                int(end.y * height),
            )

            cv2.line(
                frame,
                start_point,
                end_point,
                (0, 255, 0),
                2,
            )

        # Draw each landmark.
        for landmark in hand_landmarks:
            point = (
                int(landmark.x * width),
                int(landmark.y * height),
            )

            cv2.circle(frame, point, 4, (0, 0, 255), -1)

    return frame


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "phone_camera.html")


@app.get("/phone_camera.css")
def camera_css():
    return send_from_directory(BASE_DIR, "phone_camera.css")


@app.get("/phone_camera.js")
def camera_js():
    return send_from_directory(BASE_DIR, "phone_camera.js")


@app.post("/frame")
def receive_frame():
    global pending_frame, frames_received

    image_bytes = np.frombuffer(request.get_data(), dtype=np.uint8)
    frame = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)

    if frame is None:
        return "Invalid image", 400

    submit_frame(frame)
    return "OK", 200


def submit_frame(frame):
    global pending_frame, frames_received

    # A newer frame replaces an unprocessed older one, so the server never falls behind.
    with pending_lock:
        pending_frame = frame
        frames_received += 1
    pending_event.set()


def open_camera(index):
    # DirectShow is the Windows backend that lists virtual webcams like Camo.
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def list_cameras(max_index=6):
    for index in range(max_index):
        cap = open_camera(index)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        if ok:
            print(f"  camera {index}: {frame.shape[1]}x{frame.shape[0]}")


def camera_loop(index):
    # Feed a local webcam (e.g. the iPhone via Camo over USB) into the same pipeline.
    cap = open_camera(index)
    if not cap.isOpened():
        print(f"Can't open camera {index}. Try --list-cameras.")
        return
    while True:
        ok, frame = cap.read()
        if ok:
            submit_frame(frame)
        else:
            time.sleep(0.05)


def process_frame(frame):
    global latest_frame, latest_mask, last_timestamp_ms
    global calibration, calibration_checked, calibrating, calibration_frames
    global latest_raw, latest_fingers, status_text
    global ink_ratio_setting, line_kernel_setting

    # Detect the paper.
    annotated, mask = detect_paper(frame)

    # Convert BGR (OpenCV) to RGB (MediaPipe).
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=rgb_frame,
    )

    # VIDEO mode needs strictly increasing timestamps and is not thread-safe.
    with landmarker_lock:
        timestamp_ms = max(int(time.monotonic() * 1000), last_timestamp_ms + 1)
        last_timestamp_ms = timestamp_ms
        result = hand_landmarker.detect_for_video(mp_image, timestamp_ms)

    with frame_lock:
        latest_raw = frame
        if not calibration_checked:
            calibration = load_calibration(CALIBRATION_DIR, frame.shape)
            calibration_checked = True
            if calibration is not None:
                ink_ratio_setting = calibration["settings"]["ink_ratio"]
                line_kernel_setting = calibration["settings"]["line_kernel"]
                status_text = (
                    f"Loaded calibration: {len(calibration['regions'])} regions."
                )
        if calibrating:
            if result.hand_landmarks:
                calibration_frames.clear()
                status_text = "Calibrating: keep your hands out of view."
            else:
                calibration_frames.append(frame)
            if len(calibration_frames) >= CALIBRATION_FRAMES:
                try:
                    new_cal = build_calibration(
                        calibration_frames, ink_ratio_setting, line_kernel_setting
                    )
                    save_calibration(new_cal, CALIBRATION_DIR)
                    calibration = new_cal
                    status_text = f"Calibrated: {len(new_cal['regions'])} regions."
                except ValueError as error:
                    status_text = f"Calibration failed: {error} Press C to retry."
                finally:
                    calibrating = False
                    calibration_frames = []
        frame_size = (frame.shape[1], frame.shape[0])
        if calibration is not None and calibration["frame_size"] != frame_size:
            calibration = None
            status_text = "Frame size changed (phone rotated?): press C to recalibrate."
        cal = calibration if not calibrating else None

    fingers = {}
    if cal is not None:
        if result.hand_landmarks:
            hand = result.hand_landmarks[0]
            fingers = {
                name: region_at(cal, hand[i].x, hand[i].y)
                for name, i in FINGERTIPS.items()
            }
        annotated = draw_calibration(
            annotated, cal, {r for r in fingers.values() if r}
        )

    # Draw detected hand landmarks on top of the overlay.
    annotated = draw_hand_landmarks(annotated, result)

    with frame_lock:
        latest_frame = annotated
        latest_mask = mask
        latest_fingers = fingers


def process_pending():
    global pending_frame, process_ms

    with pending_lock:
        frame = pending_frame
        pending_frame = None
        pending_event.clear()
    if frame is None:
        return False

    start = time.perf_counter()
    process_frame(frame)
    elapsed_ms = (time.perf_counter() - start) * 1000
    process_ms = 0.9 * process_ms + 0.1 * elapsed_ms
    return True


def process_loop():
    while True:
        pending_event.wait()
        process_pending()


SETTINGS_HELP = [
    "Sens = sensitivity (default 50)",
    "  Raise if lines or keys are missed.",
    "  Lower if shadows or paper texture become regions.",
    "Key = min black key size (default 15)",
    "  Lower for small drawings where black keys",
    "  vanish or merge into white keys.",
    "Changes re-detect ~0.3 s after you stop dragging.",
]


def settings_help_image():
    image = np.full((22 * len(SETTINGS_HELP) + 12, 470, 3), 30, np.uint8)
    for i, line in enumerate(SETTINGS_HELP):
        cv2.putText(
            image, line, (8, 22 + 22 * i),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1,
        )
    return image


def run_server():
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--camera", type=int, metavar="N",
        help="read webcam N (e.g. iPhone via Camo over USB) instead of the phone page",
    )
    parser.add_argument(
        "--list-cameras", action="store_true", help="print working camera indices and exit",
    )
    args = parser.parse_args()
    if args.list_cameras:
        list_cameras()
        raise SystemExit

    if args.camera is None:
        threading.Thread(target=run_server, daemon=True).start()
        source = "phone camera frames"
    else:
        threading.Thread(target=camera_loop, args=(args.camera,), daemon=True).start()
        source = f"camera {args.camera}"
    threading.Thread(target=process_loop, daemon=True).start()

    print(f"Waiting for {source}. C = calibrate, S = save frame, Q = quit.")

    cv2.namedWindow(SETTINGS_WINDOW)
    # Trackbars have no tooltips, so the window shows a short guide instead.
    cv2.imshow(SETTINGS_WINDOW, settings_help_image())
    cv2.createTrackbar("Sens", SETTINGS_WINDOW, 50, 100, lambda v: None)
    cv2.createTrackbar("Key", SETTINGS_WINDOW, 15, 31, lambda v: None)
    applied = (None, None)    # Settings the trackbars were last set to.
    pending = None            # (settings, time first seen) while debouncing.

    last_rx_count = 0
    last_rx_time = time.monotonic()
    rx_fps = 0.0

    try:
        while True:
            now = time.monotonic()
            if now - last_rx_time >= 1.0:
                with pending_lock:
                    count = frames_received
                rx_fps = (count - last_rx_count) / (now - last_rx_time)
                last_rx_count, last_rx_time = count, now

            with frame_lock:
                frame = (
                    latest_frame.copy()
                    if latest_frame is not None
                    else None
                )
                mask = (
                    latest_mask.copy()
                    if latest_mask is not None
                    else None
                )
                status = status_text
                fingers = dict(latest_fingers)

            with frame_lock:
                if calibration is not None:
                    cs = calibration["settings"]
                    if (cs["ink_ratio"], cs["line_kernel"]) != applied:
                        applied = (cs["ink_ratio"], cs["line_kernel"])
                        cv2.setTrackbarPos(
                            "Sens", SETTINGS_WINDOW,
                            round((cs["ink_ratio"] - 0.5) / 0.4 * 100),
                        )
                        cv2.setTrackbarPos("Key", SETTINGS_WINDOW, cs["line_kernel"])
            sens = cv2.getTrackbarPos("Sens", SETTINGS_WINDOW)
            kern = max(3, cv2.getTrackbarPos("Key", SETTINGS_WINDOW))
            want = (0.5 + 0.4 * sens / 100, kern)
            if want == (ink_ratio_setting, line_kernel_setting):
                pending = None
            elif pending is None or pending[0] != want:
                pending = (want, now)
            elif now - pending[1] >= 0.3:
                pending = None
                with frame_lock:
                    ink_ratio_setting, line_kernel_setting = want
                    if calibration is not None and not calibrating:
                        try:
                            new_cal = rebuild_calibration(calibration, *want)
                            save_calibration(new_cal, CALIBRATION_DIR)
                            calibration = new_cal
                            applied = want
                            status_text = (
                                f"Re-detected: {len(new_cal['regions'])} regions "
                                f"(sens {sens}, key {kern})"
                            )
                        except ValueError as error:
                            status_text = str(error)

            if frame is None:
                frame = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.putText(
                frame, status, (5, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
            )
            cv2.putText(
                frame, f"rx {rx_fps:.1f} fps  proc {process_ms:.0f} ms", (5, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
            )
            if fingers:
                cv2.putText(
                    frame,
                    "  ".join(f"{name[0]}:{rid or '-'}" for name, rid in fingers.items()),
                    (5, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
                )
            cv2.imshow("Phone Camera Feed", frame)

            if mask is not None:
                cv2.imshow("Paper Detection Mask", mask)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("c"):
                with frame_lock:
                    calibrating = True
                    calibration_frames = []
                    status_text = "Calibrating: keep your hands out of view."
            elif key == ord("s"):
                with frame_lock:
                    raw = latest_raw.copy() if latest_raw is not None else None
                if raw is not None:
                    SAMPLES_DIR.mkdir(exist_ok=True)
                    path = SAMPLES_DIR / f"frame_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                    cv2.imwrite(str(path), raw)
                    print(path)
                    with frame_lock:
                        status_text = f"Saved {path.name}"
    except KeyboardInterrupt:
        pass
    finally:
        # Don't call hand_landmarker.close(): it can block forever while the
        # worker thread is mid-detection, which froze the terminal on Ctrl+C.
        # Exiting the process frees the model, camera and windows anyway.
        cv2.destroyAllWindows()
        os._exit(0)