import json
import time
from pathlib import Path

import cv2
import numpy as np

from paper_detector import detect_paper

FLAT_W, FLAT_H = 1100, 850   # US Letter landscape, 100 px per inch.
FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}
BORDER_PX = 12               # Ignore ink this close to the paper edge.
DARK_LEVEL = 100             # Anything darker than this is ink.
SPECK_AREA = 50
LINE_KERNEL = 15             # Wider than outlines, narrower than solid boxes.
MIN_REGION_AREA = 1000
SNAP_PX = 20                 # About 0.5 cm.


def order_corners(pts):
    # Order as top-left, top-right, bottom-right, bottom-left.
    s = pts.sum(axis=1)
    d = pts[:, 1] - pts[:, 0]
    return np.float32([
        pts[np.argmin(s)],
        pts[np.argmin(d)],
        pts[np.argmax(s)],
        pts[np.argmax(d)],
    ])


def find_paper_corners(frame_bgr):
    _, mask = detect_paper(frame_bgr)
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    h, w = frame_bgr.shape[:2]
    if cv2.contourArea(c) < 0.2 * h * w:
        return None
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(approx) != 4:
        return None
    return order_corners(approx.reshape(4, 2).astype(np.float32))


def flatten(gray, corners):
    dst = np.float32(
        [[0, 0], [FLAT_W - 1, 0], [FLAT_W - 1, FLAT_H - 1], [0, FLAT_H - 1]]
    )
    H = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(gray, H, (FLAT_W, FLAT_H)), H


def find_regions(flat):
    blurred = cv2.GaussianBlur(flat, (5, 5), 0)
    adaptive = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 51, 10,
    )
    # Adaptive alone hollows out large solid boxes, so add a global dark test.
    ink = adaptive | np.where(blurred < DARK_LEVEL, 255, 0).astype(np.uint8)

    ink[:BORDER_PX] = 0
    ink[-BORDER_PX:] = 0
    ink[:, :BORDER_PX] = 0
    ink[:, -BORDER_PX:] = 0

    # Remove specks.
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    small = stats[:, cv2.CC_STAT_AREA] < SPECK_AREA
    small[0] = False
    ink[small[labels]] = 0

    # Solid regions: ink that survives opening with a kernel wider than lines.
    opened = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((LINE_KERNEL, LINE_KERNEL), np.uint8)
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    solids = [
        labels == i for i in range(1, n)
        if stats[i, cv2.CC_STAT_AREA] >= MIN_REGION_AREA
    ]

    # Outlined regions: white areas enclosed by ink.
    closed = cv2.dilate(ink, np.ones((3, 3), np.uint8))
    white = np.where(closed == 0, 255, 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    outlined = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w == FLAT_W or y + h == FLAT_H:
            continue
        if area < MIN_REGION_AREA:
            continue
        outlined.append(labels == i)

    # Paint outlined first, then solid on top, with temporary IDs.
    flat_map = np.zeros((FLAT_H, FLAT_W), np.uint16)
    kinds = {}
    t = 0
    for kind, masks in (("outlined", outlined), ("solid", solids)):
        for m in masks:
            t += 1
            flat_map[m] = t
            kinds[t] = kind

    # Number left to right.
    cents = {}
    for t in kinds:
        ys, xs = np.nonzero(flat_map == t)
        cents[t] = (xs.mean(), ys.mean())
    order = sorted(kinds, key=lambda t: cents[t])
    lut = np.zeros(len(kinds) + 1, np.uint16)
    regions = []
    for new_id, old in enumerate(order, 1):
        lut[old] = new_id
        ys, xs = np.nonzero(flat_map == old)
        x0, y0 = int(xs.min()), int(ys.min())
        regions.append({
            "id": new_id,
            "kind": kinds[old],
            "centroid": [float(cents[old][0]), float(cents[old][1])],
            "bbox": [x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1],
            "area": int(xs.size),
        })
    flat_map = lut[flat_map]

    # Snap gaps so a fingertip on a line or near a box still maps.
    for _ in range(SNAP_PX):
        grown = cv2.dilate(flat_map, np.ones((3, 3), np.uint8))
        flat_map = np.where(flat_map == 0, grown, flat_map)

    return flat_map, regions, ink


def region_outlines(flat_map, H_inv):
    outlines = {}
    for rid in np.unique(flat_map):
        if rid == 0:
            continue
        contours, _ = cv2.findContours(
            (flat_map == rid).astype(np.uint8),
            cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        c = max(contours, key=cv2.contourArea)
        mapped = cv2.perspectiveTransform(
            c.reshape(-1, 1, 2).astype(np.float32), H_inv
        )
        outlines[int(rid)] = mapped.astype(np.int32)
    return outlines


def build_calibration(frames):
    reference = np.median(np.stack(frames), axis=0).astype(np.uint8)
    corners = find_paper_corners(reference)
    if corners is None:
        raise ValueError("Can't see the whole paper (need 4 clear corners).")
    flat, H = flatten(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), corners)
    flat_map, regions, _ = find_regions(flat)
    if not regions:
        raise ValueError("No black boxes or outlines found on the paper.")
    H_inv = np.linalg.inv(H)
    h, w = reference.shape[:2]
    # Nearest only: blending would invent region IDs.
    key_map = cv2.warpPerspective(
        flat_map, H_inv, (w, h), flags=cv2.INTER_NEAREST
    )
    return {
        "key_map": key_map,
        "flat_map": flat_map,
        "H": H,
        "H_inv": H_inv,
        "corners": corners,
        "frame_size": (w, h),
        "regions": regions,
        "outlines": region_outlines(flat_map, H_inv),
        "reference": reference,
        "timestamp": time.time(),
    }


def region_at(cal, x_norm, y_norm):
    w, h = cal["frame_size"]
    x = min(max(int(x_norm * w), 0), w - 1)
    y = min(max(int(y_norm * h), 0), h - 1)
    return int(cal["key_map"][y, x])


def save_calibration(cal, directory):
    Path(directory).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        Path(directory) / "calibration.npz",
        key_map=cal["key_map"],
        flat_map=cal["flat_map"],
        H=cal["H"],
        H_inv=cal["H_inv"],
        corners=cal["corners"],
        frame_size=np.array(cal["frame_size"]),
        reference=cal["reference"],
        timestamp=np.array(cal["timestamp"]),
    )
    with open(Path(directory) / "regions.json", "w") as f:
        json.dump(cal["regions"], f, indent=2)


def load_calibration(directory, frame_shape):
    npz_path = Path(directory) / "calibration.npz"
    json_path = Path(directory) / "regions.json"
    if not npz_path.exists() or not json_path.exists():
        return None
    data = np.load(npz_path)
    size = tuple(int(v) for v in data["frame_size"])
    if size != (frame_shape[1], frame_shape[0]):
        return None
    with open(json_path) as f:
        regions = json.load(f)
    return {
        "key_map": data["key_map"],
        "flat_map": data["flat_map"],
        "H": data["H"],
        "H_inv": data["H_inv"],
        "corners": data["corners"],
        "frame_size": size,
        "regions": regions,
        "outlines": region_outlines(data["flat_map"], data["H_inv"]),
        "reference": data["reference"],
        "timestamp": float(data["timestamp"]),
    }


def region_color(region_id):
    rng = np.random.default_rng(region_id)
    return tuple(int(v) for v in rng.integers(64, 256, 3))


def draw_calibration(frame, cal, active_ids):
    overlay = frame.copy()
    for rid, contour in cal["outlines"].items():
        color = (0, 255, 255) if rid in active_ids else region_color(rid)
        cv2.fillPoly(overlay, [contour], color)
    frame = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)
    for rid, contour in cal["outlines"].items():
        cv2.polylines(frame, [contour], True, (255, 255, 255), 1)
        cx, cy = contour.reshape(-1, 2).mean(axis=0)
        cv2.putText(
            frame, str(rid), (int(cx), int(cy)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
        )
    return frame


def render_flat_regions(flat_map, regions):
    out = np.full((FLAT_H, FLAT_W, 3), (40, 40, 40), np.uint8)
    for rid in np.unique(flat_map):
        if rid:
            out[flat_map == rid] = region_color(int(rid))
    for r in regions:
        cx, cy = r["centroid"]
        cv2.putText(
            out, str(r["id"]), (int(cx), int(cy)),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2,
        )
    return out
