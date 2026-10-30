import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from flask import Flask, request, send_from_directory
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

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

    # Draw detected hand landmarks.
    annotated = draw_hand_landmarks(annotated, result)

    with frame_lock:
        latest_frame = annotated
        latest_mask = mask

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

    print("Waiting for phone camera frames. Press Q to quit.")

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

            if frame is None:
                frame = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.imshow("Phone Camera Feed", frame)

            if mask is not None:
                cv2.imshow("Paper Detection Mask", mask)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        hand_landmarker.close()
        cv2.destroyAllWindows()