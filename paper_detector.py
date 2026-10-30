import cv2
import numpy as np


def detect_paper(frame):
    frame = frame.copy()
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    lower_white = np.array([0, 0, 120])
    upper_white = np.array([180, 80, 255])

    mask = cv2.inRange(hsv, lower_white, upper_white)

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if contours:
        largest = max(contours, key=cv2.contourArea)

        if cv2.contourArea(largest) > 1000:
            cv2.drawContours(frame, [largest], -1, (0, 255, 0), 2)

    return frame, mask