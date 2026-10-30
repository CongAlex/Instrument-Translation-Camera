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
    build_calibration,
    draw_calibration,
    load_calibration,
    region_at,
    save_calibration,
)
from paper_detector import detect_paper

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
# Frames are small JPEGs; reject anything larger.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

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
    global latest_frame, latest_mask, last_timestamp_ms
    global calibration, calibration_checked, calibrating, calibration_frames
    global latest_raw, latest_fingers, status_text

    image_bytes = np.frombuffer(request.get_data(), dtype=np.uint8)
    frame = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)

    if frame is None:
        return "Invalid image", 400

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
                    new_cal = build_calibration(calibration_frames)
                    save_calibration(new_cal, CALIBRATION_DIR)
                    calibration = new_cal
                    status_text = f"Calibrated: {len(new_cal['regions'])} regions."
                except ValueError as error:
                    status_text = f"Calibration failed: {error} Press C to retry."
                finally:
                    calibrating = False
                    calibration_frames = []
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

    return "OK", 200


def run_server():
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()

    print("Waiting for phone camera frames. C = calibrate, S = save frame, Q = quit.")

    try:
        while True:
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

            if frame is None:
                frame = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.putText(
                frame, status, (5, 15),
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
    finally:
        hand_landmarker.close()
        cv2.destroyAllWindows()