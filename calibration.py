import json
import time
from pathlib import Path

import cv2
import numpy as np

from paper_detector import detect_paper

FLAT_W, FLAT_H = 1100, 850   # US Letter landscape, 100 px per inch.
FINGERTIPS = {"Thumb": 4, "Index": 8, "Middle": 12, "Ring": 16, "Pinky": 20}
BORDER_PX = 12               # Ignore ink this close to the paper edge.
DARK_RATIO = 0.7             # Darker than this fraction of the wider paper is solid ink.
INK_RATIO = 0.7            # Darker than this fraction of nearby paper is ink.
SPECK_AREA = 50
LINE_KERNEL = 15             # Wider than outlines, narrower than solid boxes.
MIN_REGION_AREA = 300  # About 0.2 cm²; allows small keys.
GAP_KERNEL = 11            # Closes small breaks in hand-drawn outlines.
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
    # The hull ignores torn edges and dents; rounded corners need a looser fit.
    hull = cv2.convexHull(c)
    for eps in (0.02, 0.03, 0.04, 0.05):
        approx = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            return order_corners(approx.reshape(4, 2).astype(np.float32))
    return None


def flatten(gray, corners):
    tl, tr, br, bl = corners
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    # Portrait paper flattens to a portrait image.
    w, h = (FLAT_H, FLAT_W) if height > width else (FLAT_W, FLAT_H)
    dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    H = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(gray, H, (w, h)), H


def order_regions(cents, kinds, flat_map):
    # Pianos: "up" points from each black key's neighbouring white keys toward
    # the black key; number left to right with up at the top. Using only
    # neighbours keeps stray boxes elsewhere on the page from skewing "up".
    # Anything else: plain left to right.
    kernel = np.ones((9, 9), np.uint8)
    pulls = []
    for t in kinds:
        if kinds[t] != "solid":
            continue
        near = cv2.dilate((flat_map == t).astype(np.uint8), kernel) > 0
        whites = [
            n for n in np.unique(flat_map[near])
            if n and kinds.get(int(n)) == "outlined"
        ]
        if whites:
            pulls.append(
                np.subtract(cents[t], np.mean([cents[int(n)] for n in whites], axis=0))
            )
    if pulls:
        up = np.mean(pulls, axis=0)
        norm = np.linalg.norm(up)
        if norm > 5:
            ux, uy = up / norm
            rx, ry = -uy, ux
            return sorted(
                kinds,
                key=lambda t: (cents[t][0] * rx + cents[t][1] * ry,
                               -(cents[t][0] * ux + cents[t][1] * uy)),
            )
    return sorted(kinds, key=lambda t: cents[t])


def find_regions(flat, ink_ratio=INK_RATIO, line_kernel=LINE_KERNEL):
    fh, fw = flat.shape
    blurred = cv2.GaussianBlur(flat, (5, 5), 0)
    # Ink = locally darker (adaptive) AND clearly darker than nearby paper.
    # Faint printed ruled lines pass the first test but sit near 0.8 of the
    # paper's brightness (pen is near 0.3), so the ratio test rejects them.
    # Large solid boxes, which adaptive hollows out, are caught by the dark test.
    adaptive = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 51, 10,
    )
    paper = cv2.dilate(blurred, np.ones((31, 31), np.uint8)).astype(np.float32)
    ratio = blurred / np.maximum(paper, 1)
    # Solid boxes are too big for the 31 px estimate, so compare them with a
    # much wider one. Relative, so a soft shadow never counts as a black box.
    wide = cv2.dilate(blurred, np.ones((151, 151), np.uint8)).astype(np.float32)
    dark = (blurred < 100) & (blurred < DARK_RATIO * wide)
    ink = np.where(
        ((adaptive > 0) & (ratio < ink_ratio)) | dark, 255, 0
    ).astype(np.uint8)

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
        ink, cv2.MORPH_OPEN, np.ones((line_kernel, line_kernel), np.uint8)
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    solids = [
        labels == i for i in range(1, n)
        if stats[i, cv2.CC_STAT_AREA] >= MIN_REGION_AREA
    ]

    # Outlined regions: white areas enclosed by ink.
    closed = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE, np.ones((GAP_KERNEL, GAP_KERNEL), np.uint8)
    )
    closed = cv2.dilate(closed, np.ones((3, 3), np.uint8))
    white = np.where(closed == 0, 255, 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    outlined = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w == fw or y + h == fh:
            continue
        if area < MIN_REGION_AREA:
            continue
        outlined.append(labels == i)

    # Paint outlined first, then solid on top, with temporary IDs.
    flat_map = np.zeros((fh, fw), np.uint16)
    kinds = {}
    t = 0
    for kind, masks in (("outlined", outlined), ("solid", solids)):
        for m in masks:
            t += 1
            flat_map[m] = t
            kinds[t] = kind

    # Number along the keyboard (see order_regions).
    cents = {}
    for t in kinds:
        ys, xs = np.nonzero(flat_map == t)
        cents[t] = (xs.mean(), ys.mean())
    order = order_regions(cents, kinds, flat_map)
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


def build_calibration(frames, ink_ratio=INK_RATIO, line_kernel=LINE_KERNEL):
    reference = np.median(np.stack(frames), axis=0).astype(np.uint8)
    corners = find_paper_corners(reference)
    if corners is None:
        raise ValueError("Can't see the whole paper (need 4 clear corners).")
    flat, H = flatten(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), corners)
    flat_map, regions, _ = find_regions(flat, ink_ratio, line_kernel)
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
        "settings": {"ink_ratio": float(ink_ratio), "line_kernel": int(line_kernel)},
    }


def rebuild_calibration(cal, ink_ratio, line_kernel):
    # Re-detect on the saved reference image; no new frames needed.
    return build_calibration([cal["reference"]], ink_ratio, line_kernel)


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
    with open(Path(directory) / "settings.json", "w") as f:
        json.dump(cal["settings"], f)


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
    settings = {"ink_ratio": INK_RATIO, "line_kernel": LINE_KERNEL}
    if (Path(directory) / "settings.json").exists():
        with open(Path(directory) / "settings.json") as f:
            settings = json.load(f)
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
        "settings": settings,
    }


def region_color(region_id):
    rng = np.random.default_rng(region_id)
    return tuple(int(v) for v in rng.integers(64, 256, 3))


def draw_calibration(frame, cal, active_ids):
    # Idle regions are a faint tint; touched regions are a strong yellow fill.
    overlay = frame.copy()
    for rid, contour in cal["outlines"].items():
        cv2.fillPoly(overlay, [contour], region_color(rid))
    frame = cv2.addWeighted(overlay, 0.25, frame, 0.75, 0)
    if active_ids:
        overlay = frame.copy()
        for rid, contour in cal["outlines"].items():
            if rid in active_ids:
                cv2.fillPoly(overlay, [contour], (0, 255, 255))
        frame = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)
    for rid, contour in cal["outlines"].items():
        active = rid in active_ids
        cv2.polylines(
            frame, [contour], True,
            (0, 255, 255) if active else (255, 255, 255), 3 if active else 1,
        )
        cx, cy = contour.reshape(-1, 2).mean(axis=0)
        cv2.putText(
            frame, str(rid), (int(cx), int(cy)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
        )
    return frame


def render_flat_regions(flat_map, regions):
    out = np.full((*flat_map.shape, 3), (40, 40, 40), np.uint8)
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
