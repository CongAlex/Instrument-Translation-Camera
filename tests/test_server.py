import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

import phone_server
from paper_detector import detect_paper


def make_image():
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(img, (60, 40), (260, 190), (255, 255, 255), -1)
    return img


def jpeg_bytes():
    return cv2.imencode(".jpg", make_image())[1].tobytes()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = phone_server.app.test_client()

    def test_detect_paper_does_not_mutate_input(self):
        img = make_image()
        original = img.copy()
        out, _ = detect_paper(img)
        self.assertTrue(np.array_equal(img, original))
        self.assertFalse(np.array_equal(out, original))

    def test_index_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_invalid_frame_rejected(self):
        self.assertEqual(self.client.post("/frame", data=b"not a jpeg").status_code, 400)

    def test_oversized_frame_rejected(self):
        resp = self.client.post("/frame", data=b"\0" * (3 * 1024 * 1024))
        self.assertEqual(resp.status_code, 413)

    def test_valid_frame_accepted(self):
        resp = self.client.post("/frame", data=jpeg_bytes())
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(phone_server.latest_frame)

    def test_timestamps_strictly_increase(self):
        self.client.post("/frame", data=jpeg_bytes())
        first = phone_server.last_timestamp_ms
        self.client.post("/frame", data=jpeg_bytes())
        self.assertGreater(phone_server.last_timestamp_ms, first)


if __name__ == "__main__":
    unittest.main()
