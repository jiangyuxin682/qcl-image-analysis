"""Track horizontal gold-strip motion and translate fixed-size crop rectangles.

A median column profile over the reference ROI's rows suppresses isolated bright
pixels. The brightest contiguous plateau on each requested side anchors the
reference. Each frame searches only within max_shift pixels of that anchor.
Both-side mode averages the two displacements and rejects inconsistent motion.
Coordinates are rounded to integer pixels; no interpolation, scaling or Y shift
is applied. Search settings and measured positions should be reviewed visually.
"""
import numpy as np
from qcl_analysis.roi import ROI
from qcl_analysis.cropping import validate_roi


def _gold_position(profile, lo, hi):
    segment = profile[lo:hi]
    if segment.size < 3 or not np.isfinite(segment).all():
        raise ValueError("Gold search region must contain at least three finite columns.")
    floor, peak = float(np.min(segment)), float(np.max(segment))
    if peak - floor <= max(abs(peak), 1.0) * 1e-8:
        raise ValueError("Gold strip cannot be distinguished in the search region.")
    index = int(np.argmax(segment))
    threshold = floor + 0.8 * (peak - floor)
    left = right = index
    while left > 0 and segment[left - 1] >= threshold:
        left -= 1
    while right + 1 < segment.size and segment[right + 1] >= threshold:
        right += 1
    if left == 0 or right == segment.size - 1:
        raise ValueError("Gold strip touches the search boundary; adjust ROI or maximum drift.")
    return lo + (left + right) / 2


def gold_drift_rois(images, reference_pattern, roi, side="both", max_shift=20, tolerance=3):
    """Return per-pattern ROIs and diagnostics from one common spectral band."""
    if side not in {"left", "right", "both"}:
        raise ValueError("Gold side must be left, right, or both.")
    if not isinstance(max_shift, int) or max_shift < 1:
        raise ValueError("Maximum drift must be a positive integer.")
    reference = images[reference_pattern]
    validate_roi(reference, roi)
    width = reference.shape[1]
    sides = ["left", "right"] if side == "both" else [side]
    profile = np.median(reference[roi.y_min:roi.y_max], axis=0)
    bounds = {"left": (0, roi.x_min), "right": (roi.x_max, width)}
    anchors = {s: _gold_position(profile, *bounds[s]) for s in sides}
    rois, records = {}, []
    for pattern, image in images.items():
        try:
            if image.shape != reference.shape:
                raise ValueError("Reference-band image shapes differ.")
            current = np.median(image[roi.y_min:roi.y_max], axis=0)
            positions = {}
            for s, anchor in anchors.items():
                lo = max(0, int(np.floor(anchor)) - max_shift - 3)
                hi = min(width, int(np.ceil(anchor)) + max_shift + 4)
                positions[s] = anchor if pattern == reference_pattern else _gold_position(current, lo, hi)
            shifts = [positions[s] - anchors[s] for s in sides]
            if max(abs(v) for v in shifts) > max_shift:
                raise ValueError("Gold displacement exceeds maximum drift.")
            if len(shifts) == 2 and abs(shifts[0] - shifts[1]) > tolerance:
                raise ValueError("Left and right gold displacements disagree by more than 3 pixels.")
            dx = int(np.rint(np.mean(shifts)))
            moved = ROI(roi.x_min + dx, roi.x_max + dx, roi.y_min, roi.y_max)
            validate_roi(image, moved)
            rois[pattern] = moved
            records.append({"pattern": pattern, "dx": dx, "dy": 0,
                            "left_gold_x": positions.get("left"),
                            "right_gold_x": positions.get("right")})
        except ValueError as exc:
            raise ValueError(f"Drift correction failed for {pattern}: {exc}") from exc
    return rois, records
