import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from calibration import (
    build_calibration,
    load_calibration,
    region_at,
    save_calibration,
)

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


def increasing_x(regions):
    xs = [r["centroid"][0] for r in regions]
    return all(a < b for a, b in zip(xs, xs[1:]))


class CalibrationTests(unittest.TestCase):
    def test_solid_boxes(self):
        regions = build_calibration([make_sheet(solid, STRAIGHT)[0]])["regions"]
        self.assertEqual(len(regions), 4)
        self.assertTrue(all(r["kind"] == "solid" for r in regions))
        self.assertEqual([r["id"] for r in regions], [1, 2, 3, 4])
        self.assertTrue(increasing_x(regions))

    def test_outlined_boxes(self):
        regions = build_calibration([make_sheet(outlined, STRAIGHT)[0]])["regions"]
        self.assertEqual(len(regions), 4)
        self.assertTrue(all(r["kind"] == "outlined" for r in regions))
        self.assertEqual([r["id"] for r in regions], [1, 2, 3, 4])
        self.assertTrue(increasing_x(regions))

    def test_piano_is_chromatic(self):
        regions = build_calibration([make_sheet(piano, STRAIGHT)[0]])["regions"]
        kinds = "".join(r["kind"][0].upper() for r in regions)
        self.assertEqual(len(regions), 12)
        self.assertEqual(kinds, "OSOSOOSOSOSO")

    def test_tilted(self):
        cal = build_calibration([make_sheet(solid, TILTED)[0]])
        self.assertEqual(len(cal["regions"]), 4)

    def test_region_lookup(self):
        img, M = make_sheet(solid, STRAIGHT)
        cal = build_calibration([img])
        self.assertEqual(at(cal, M, 430, 425), 2)
        self.assertIn(at(cal, M, 325, 425), {1, 2})
        self.assertEqual(at(cal, M, 550, 120), 0)

    def test_save_load_roundtrip(self):
        cal = build_calibration([make_sheet(solid, STRAIGHT)[0]])
        with tempfile.TemporaryDirectory() as d:
            save_calibration(cal, d)
            loaded = load_calibration(d, (480, 640, 3))
            self.assertTrue(np.array_equal(loaded["key_map"], cal["key_map"]))
            self.assertEqual(loaded["regions"], cal["regions"])
            self.assertIsNone(load_calibration(d, (240, 320, 3)))

    def test_no_paper_raises(self):
        with self.assertRaises(ValueError):
            build_calibration([np.full((480, 640, 3), 40, np.uint8)])


if __name__ == "__main__":
    unittest.main()
