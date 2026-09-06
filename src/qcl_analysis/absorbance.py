"""Absorbance calculation utilities for QCL image analysis.

This module calculates a per-image reference reflectance R0 from a
cell-free metasurface region of interest (ROI), and converts relative
reflectance images into absorbance images.
"""

import numpy as np
from numpy.typing import NDArray

from qcl_analysis.roi import ROI


def calculate_r0(
    reflectance: NDArray[np.float64],
    roi: ROI,
) -> float:
    """Calculate R0 from a cell-free metasurface ROI.

    R0 is defined as the mean reflectance inside the selected ROI.

    Parameters
    ----------
    reflectance
        Two-dimensional relative reflectance image.

    roi
        Rectangular cell-free metasurface region.

    Returns
    -------
    float
        Mean reflectance inside the ROI.
    """

    if reflectance.ndim != 2:
        raise ValueError(
            f"Expected a 2D reflectance image, got shape {reflectance.shape}."
        )

    height, width = reflectance.shape

    if roi.x_max > width or roi.y_max > height:
        raise ValueError(f"ROI {roi} exceeds image shape {reflectance.shape}.")

    roi_data = reflectance[roi.as_slices()]

    if roi_data.size == 0:
        raise ValueError("R0 ROI contains no pixels.")

    if not np.isfinite(roi_data).all():
        raise ValueError("R0 ROI contains NaN or infinite values.")

    r0 = float(np.mean(roi_data))

    if not np.isfinite(r0):
        raise ValueError("Calculated R0 is not finite.")

    if r0 <= 0:
        raise ValueError("Calculated R0 must be positive.")

    return r0


def calculate_absorbance(
    reflectance: NDArray[np.float64],
    r0: float,
) -> NDArray[np.float64]:
    """Calculate absorbance from reflectance and R0.

    Absorbance is defined as:

        A = -log10(R / R0)

    Pixels where R <= 0 or R is non-finite are returned as NaN.

    Parameters
    ----------
    reflectance
        Two-dimensional relative reflectance image.

    r0
        Reference reflectance for this image.

    Returns
    -------
    NDArray[np.float64]
        Two-dimensional absorbance image.
    """

    if reflectance.ndim != 2:
        raise ValueError(
            f"Expected a 2D reflectance image, got shape {reflectance.shape}."
        )

    if not np.isfinite(r0):
        raise ValueError("R0 must be finite.")

    if r0 <= 0:
        raise ValueError("R0 must be positive.")

    absorbance = np.full(
        reflectance.shape,
        np.nan,
        dtype=np.float64,
    )

    valid_pixels = np.isfinite(reflectance) & (reflectance > 0)

    absorbance[valid_pixels] = -np.log10(reflectance[valid_pixels] / r0)

    return absorbance


def calculate_absorbance_from_roi(
    reflectance: NDArray[np.float64],
    roi: ROI,
) -> tuple[
    NDArray[np.float64],
    float,
]:
    """Calculate R0 and absorbance from a selected metasurface ROI.

    This is a convenience function that performs both steps:

        R0 = mean(R inside ROI)

        A = -log10(R / R0)

    Returns
    -------
    absorbance
        Two-dimensional absorbance image.

    r0
        Reference reflectance calculated from the ROI.
    """

    r0 = calculate_r0(
        reflectance,
        roi,
    )

    absorbance = calculate_absorbance(
        reflectance,
        r0,
    )

    return (
        absorbance,
        r0,
    )
