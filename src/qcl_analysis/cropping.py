"""Spatial cropping utilities for QCL image analysis.

This module provides functions for cropping two-dimensional QCL images
using rectangular regions of interest (ROIs).

ROI coordinates follow NumPy slicing conventions:

    x in [x_min, x_max)
    y in [y_min, y_max)

The upper bounds are therefore exclusive.
"""

import numpy as np
from numpy.typing import NDArray

from qcl_analysis.roi import ROI


def validate_roi(
    image: NDArray,
    roi: ROI,
) -> None:
    """Validate that an ROI is compatible with a 2D image.

    Parameters
    ----------
    image
        Two-dimensional image.

    roi
        Rectangular region of interest.

    Raises
    ------
    ValueError
        If the image is not 2D or the ROI lies outside the image.
    """

    if image.ndim != 2:
        raise ValueError(f"Expected a 2D image, got shape {image.shape}.")

    height, width = image.shape

    if roi.x_min < 0 or roi.y_min < 0:
        raise ValueError(f"ROI coordinates must be non-negative: {roi}.")

    if roi.x_max > width or roi.y_max > height:
        raise ValueError(f"ROI {roi} exceeds image shape {image.shape}.")

    if roi.x_max <= roi.x_min:
        raise ValueError(f"ROI x_max must be greater than x_min: {roi}.")

    if roi.y_max <= roi.y_min:
        raise ValueError(f"ROI y_max must be greater than y_min: {roi}.")


def crop_image(
    image: NDArray,
    roi: ROI,
    *,
    copy: bool = True,
) -> NDArray:
    """Crop a 2D image using a rectangular ROI.

    Parameters
    ----------
    image
        Two-dimensional image to crop.

    roi
        Region to extract.

    copy
        If True, return an independent copy of the cropped image.
        If False, NumPy may return a view into the original image.

    Returns
    -------
    NDArray
        Cropped image.
    """

    validate_roi(
        image,
        roi,
    )

    cropped = image[roi.as_slices()]

    if copy:
        cropped = cropped.copy()

    return cropped


def crop_on_ms(
    image: NDArray,
    on_ms_roi: ROI,
    *,
    copy: bool = True,
) -> NDArray:
    """Crop the metasurface region from an image."""

    return crop_image(
        image,
        on_ms_roi,
        copy=copy,
    )


def crop_out_ms(
    image: NDArray,
    out_ms_roi: ROI,
    *,
    copy: bool = True,
) -> NDArray:
    """Crop the region outside the metasurface from an image."""

    return crop_image(
        image,
        out_ms_roi,
        copy=copy,
    )


def crop_ms_regions(
    image: NDArray,
    on_ms_roi: ROI,
    out_ms_roi: ROI,
    *,
    copy: bool = True,
) -> tuple[
    NDArray,
    NDArray,
]:
    """Crop both on-MS and out-MS regions from the same image.

    Parameters
    ----------
    image
        Two-dimensional image.

    on_ms_roi
        ROI defining the metasurface region.

    out_ms_roi
        ROI defining the region outside the metasurface.

    copy
        If True, return independent copies of both cropped images.

    Returns
    -------
    on_ms
        Cropped metasurface image.

    out_ms
        Cropped image outside the metasurface.
    """

    on_ms = crop_on_ms(
        image,
        on_ms_roi,
        copy=copy,
    )

    out_ms = crop_out_ms(
        image,
        out_ms_roi,
        copy=copy,
    )

    return (
        on_ms,
        out_ms,
    )
