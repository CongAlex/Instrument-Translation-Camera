import sys

import cv2
import numpy as np

from calibration import (
    find_paper_corners,
    find_regions,
    flatten,
    render_flat_regions,
)
from paper_detector import detect_paper

path = sys.argv[1]
img = cv2.imread(path)
if img is None:
    print(f"Can't read {path}")
    sys.exit(1)

out = sys.argv[2] if len(sys.argv) > 2 else path.rsplit(".", 1)[0] + "_debug.png"

corners = find_paper_corners(img)
if corners is None:
    mask = cv2.cvtColor(detect_paper(img)[1], cv2.COLOR_GRAY2BGR)
    cv2.imwrite(out, np.hstack([img, mask]))
    print(f"No paper found; wrote {out}")
    sys.exit(1)

flat, _ = flatten(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), corners)
flat_map, regions, ink = find_regions(flat)
debug = np.hstack([
    cv2.cvtColor(flat, cv2.COLOR_GRAY2BGR),
    cv2.cvtColor(ink, cv2.COLOR_GRAY2BGR),
    render_flat_regions(flat_map, regions),
])
cv2.imwrite(out, cv2.resize(debug, None, fx=0.5, fy=0.5))
print(f"{len(regions)} regions")
for r in regions:
    print(r["id"], r["kind"], r["centroid"], r["area"])
print(f"wrote {out}")
