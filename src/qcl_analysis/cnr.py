"""Compare ROI contrast-to-noise ratios on a shared spatial pixel selection.

CNR = abs(mean(target) - mean(background)) / sample_std(background), ddof=1.
The background standard deviation measures spatial variation in the selected
patch; smoothing can increase this CNR without improving spatial resolution.
For stage comparisons, use the intersection of finite pixels across available
stages so processing does not silently change which pixels enter the statistic.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import ArrayLike

from qcl_analysis.cropping import validate_roi
from qcl_analysis.roi import ROI


@dataclass(frozen=True)
class CNRResult:
    """Store CNR and diagnostics; an undefined CNR is NaN with a status reason."""

    cnr: float
    signed_contrast: float
    target_mean: float
    background_mean: float
    background_std: float
    target_pixels: int
    background_pixels: int
    excluded_target_pixels: int
    excluded_background_pixels: int
    status: str


def _array(image: ArrayLike) -> np.ndarray:
    """Accept real nonempty 2D arrays, retaining invalid values for masking."""
    if np.iscomplexobj(image):
        raise ValueError("CNR images must be real-valued.")
    array = np.asarray(image, dtype=float)
    if array.ndim != 2 or array.size == 0:
        raise ValueError("CNR images must be nonempty 2D arrays.")
    return array


def calculate_roi_cnr(
    image: ArrayLike,
    background_roi: ROI,
    target_roi: ROI,
    *,
    valid_mask: ArrayLike | None = None,
) -> CNRResult:
    """Compute target/background CNR without changing or rescaling the image.

    Both rectangles use half-open image coordinates and must not overlap.
    Nonfinite values are excluded; an optional boolean mask further restricts
    sampling. At least two background pixels and one target pixel are needed.
    A zero or numerically negligible background standard deviation gives NaN
    (not infinity). Means and sample sizes are returned even when CNR is invalid.
    The signed contrast is retained alongside the nonnegative CNR magnitude.
    """
    array = _array(image)
    validate_roi(array, background_roi)
    validate_roi(array, target_roi)
    if not (
        background_roi.x_max <= target_roi.x_min
        or target_roi.x_max <= background_roi.x_min
        or background_roi.y_max <= target_roi.y_min
        or target_roi.y_max <= background_roi.y_min
    ):
        raise ValueError("Background and target ROIs must not overlap.")
    valid = np.isfinite(array)
    if valid_mask is not None:
        mask = np.asarray(valid_mask)
        if mask.shape != array.shape or mask.dtype != np.bool_:
            raise ValueError("valid_mask must be boolean and match the image shape.")
        valid &= mask
    bg_all = array[background_roi.as_slices()]
    target_all = array[target_roi.as_slices()]
    bg = bg_all[valid[background_roi.as_slices()]]
    target = target_all[valid[target_roi.as_slices()]]
    bg_mean = float(bg.mean()) if bg.size else np.nan
    target_mean = float(target.mean()) if target.size else np.nan
    bg_std = float(bg.std(ddof=1)) if bg.size >= 2 else np.nan
    contrast = target_mean - bg_mean
    cnr = np.nan
    if bg.size < 2:
        status = "insufficient_background_pixels"
    elif not target.size:
        status = "insufficient_target_pixels"
    elif bg_std <= np.finfo(float).eps * max(float(np.max(np.abs(bg))), np.finfo(float).tiny):
        status = "zero_background_noise"
    else:
        cnr = float(abs(contrast) / bg_std)
        status = "valid"
    return CNRResult(
        cnr=cnr, signed_contrast=contrast, target_mean=target_mean,
        background_mean=bg_mean, background_std=bg_std,
        target_pixels=int(target.size), background_pixels=int(bg.size),
        excluded_target_pixels=int(target_all.size - target.size),
        excluded_background_pixels=int(bg_all.size - bg.size), status=status,
    )


def compare_stage_cnr(
    stages: Mapping[str, ArrayLike | None],
    background_roi: ROI,
    target_roi: ROI,
) -> list[dict]:
    """Measure stages on identical finite pixels with the same two rectangles.

    Available stages must have identical shapes. The common validity mask is
    the intersection across all available stages, applied separately within
    both ROIs. Missing stages (None) produce explicit unavailable rows.
    """
    available = {name: _array(image) for name, image in stages.items() if image is not None}
    if not available:
        raise ValueError("At least one processing stage must be available.")
    if len({a.shape for a in available.values()}) != 1:
        raise ValueError("All stages must share the same spatial shape.")
    common = np.logical_and.reduce([np.isfinite(a) for a in available.values()])
    records = []
    for name, image in stages.items():
        if image is None:
            record = asdict(CNRResult(
                np.nan, np.nan, np.nan, np.nan, np.nan, 0, 0, 0, 0, "unavailable",
            ))
        else:
            record = asdict(calculate_roi_cnr(
                available[name], background_roi, target_roi, valid_mask=common,
            ))
        records.append({"stage": name, **record})
    return records
