"""Subtract pixelwise linear spectral baselines from absorbance images.

Images must be spatially aligned and share a pixel grid. Two reference
wavenumbers define an interpolating line; three or more define an unweighted
least-squares line at each pixel. The center band is excluded from its fit.
NaN/Inf at any selected reference invalidates that pixel's baseline. No
partial-reference fitting or clipping of negative corrected values is used.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class LinearBaselineResult:
    """Store the estimated baseline at the center and its corrected image.

    slope has units of absorbance per cm^-1. valid_mask requires finite values
    at the center and every reference; baseline can be finite when only the
    center is invalid. All image arrays retain the original spatial shape.
    """

    center_wavenumber: float
    reference_wavenumbers: tuple[float, ...]
    baseline: NDArray[np.float64]
    corrected: NDArray[np.float64]
    slope: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]


def _wavenumber(value: float) -> float:
    """Require a finite positive numeric spectral coordinate in cm^-1."""
    if isinstance(value, (str, bool)) or not np.isscalar(value):
        raise ValueError("Wavenumbers must be positive finite numbers.")
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise ValueError("Wavenumbers must be positive finite numbers.")
    return number


def linear_baseline_correction(
    absorbance_images: Mapping[float, ArrayLike],
    center_wavenumber: float,
    reference_wavenumbers: Sequence[float],
    *,
    allow_extrapolation: bool = False,
) -> LinearBaselineResult:
    """Fit a line using reference images and subtract it at the center band.

    Each mapping key is a wavenumber in cm^-1; each value is a real nonempty
    2D absorbance array. All selected images must have identical shapes.
    At least two DISTINCT references are required and none may be the center.
    By default references must bracket the center; enable allow_extrapolation
    explicitly to evaluate outside their range.

    For two references v1<v2, baseline at vc equals
    A1*(v2-vc)/(v2-v1) + A2*(vc-v1)/(v2-v1).
    For more references, fit one unweighted least-squares line per pixel,
    using centered spectral coordinates for numerical stability. This is not
    piecewise interpolation or averaging of the two endpoint absorbances.
    """
    center = _wavenumber(center_wavenumber)
    refs = tuple(_wavenumber(v) for v in reference_wavenumbers)
    if len(refs) < 2 or len(set(refs)) != len(refs):
        raise ValueError("Provide at least two distinct reference wavenumbers.")
    if center in refs:
        raise ValueError("The center wavenumber cannot be its own baseline reference.")
    refs = tuple(sorted(refs))
    if not allow_extrapolation and not refs[0] < center < refs[-1]:
        raise ValueError("References must bracket the center; extrapolation is disabled.")
    arrays = {}
    shape = None
    for wn in (center, *refs):
        if wn not in absorbance_images:
            raise ValueError(f"Missing absorbance image for {wn:g} cm^-1.")
        image = absorbance_images[wn]
        if np.iscomplexobj(image):
            raise ValueError("Absorbance images must be real-valued.")
        array = np.asarray(image, dtype=float)
        if array.ndim != 2 or array.size == 0:
            raise ValueError("Absorbance images must be nonempty 2D arrays.")
        if shape is not None and array.shape != shape:
            raise ValueError("Selected absorbance images must have identical shapes.")
        shape = array.shape
        arrays[wn] = array

    stack = np.stack([arrays[wn] for wn in refs])
    reference_valid = np.isfinite(stack).all(axis=0)
    valid = reference_valid & np.isfinite(arrays[center])
    x = np.asarray(refs)
    x_mean = x.mean()
    dx = x - x_mean
    values = stack[:, reference_valid]
    mean_values = values.mean(axis=0)
    fitted_slope = np.sum(dx[:, None] * (values - mean_values), axis=0) / np.sum(dx**2)
    baseline = np.full(shape, np.nan)
    slope = np.full(shape, np.nan)
    baseline[reference_valid] = mean_values + fitted_slope * (center - x_mean)
    slope[reference_valid] = fitted_slope
    corrected = np.full(shape, np.nan)
    corrected[valid] = arrays[center][valid] - baseline[valid]
    return LinearBaselineResult(
        center_wavenumber=center, reference_wavenumbers=refs,
        baseline=baseline, corrected=corrected, slope=slope, valid_mask=valid,
    )


def correct_absorbance_baselines(
    absorbance_images: Mapping[float, ArrayLike],
    references_by_center: Mapping[float, Sequence[float]],
    *,
    allow_extrapolation: bool = False,
) -> dict[float, LinearBaselineResult]:
    """Correct multiple center bands, each with its own reference selection.

    Returns new results without mutating the input mapping or its arrays.
    An empty configuration is rejected rather than silently producing no data.
    """
    if not references_by_center:
        raise ValueError("Configure at least one center wavenumber.")
    return {
        _wavenumber(center): linear_baseline_correction(
            absorbance_images, center, refs, allow_extrapolation=allow_extrapolation,
        )
        for center, refs in references_by_center.items()
    }
