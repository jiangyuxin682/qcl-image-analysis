"""Estimate a rolling-ball field and correct multiplicative reflectance shading.

The rolling-ball surface is estimated from a Fourier-filtered on-MS image.
Spatial radius (pixels) and kernel height (reflectance units) are independent,
so normalized float images do not inherit an inappropriate intensity scale.
Flat-field correction divides by the estimated field and multiplies by a
reference level. This is a single-image shading estimate, not a measured
blank-field calibration, and specimen structure may enter the estimate.
"""

from dataclasses import dataclass
from numbers import Integral

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.ndimage import gaussian_filter
from skimage.restoration import rolling_ball


@dataclass(frozen=True)
class FlatFieldResult:
    """Correction arrays retain the input shape; invalid divisors yield NaNs.

    gain = reference_level/background on valid pixels, corrected = image*gain,
    and change = corrected-image. The background is not silently floored.
    """

    corrected: NDArray[np.float64]
    background: NDArray[np.float64]
    gain: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]
    change: NDArray[np.float64]
    reference_level: float


def _image(image: ArrayLike) -> NDArray[np.float64]:
    """Accept only real, finite, nonempty 2D images with both axes >= 2."""
    if np.iscomplexobj(image):
        raise ValueError("image must be real-valued.")
    array = np.asarray(image, dtype=float)
    if array.ndim != 2 or min(array.shape) < 2:
        raise ValueError("image must be 2D with at least two pixels per axis.")
    if not np.isfinite(array).all():
        raise ValueError("image must contain only finite values.")
    return array


def estimate_rolling_ball_background(
    image: ArrayLike,
    *,
    radius: int = 30,
    kernel_height: float = 0.05,
    feature_polarity: str = "dark",
    smooth_sigma: float = 1.0,
    pad_pixels: int = 0,
) -> NDArray[np.float64]:
    """Estimate an illumination field with an intensity-scaled rolling ball.

    radius is the circular spatial support radius in pixels (integer >= 1).
    Choose it larger than the radius of features you want to retain. Larger
    radii bridge wider features but are slower and can miss shading changes.
    kernel_height is the cap height in the same units as reflectance. A lower
    cap is flatter and bridges more variation; a higher cap follows the image
    more locally. Radius and height must be tuned together.
    feature_polarity='bright' estimates a lower envelope. 'dark' transforms
    image to max(image)-image, estimates its lower envelope and inverts back,
    producing an upper-envelope estimate suitable for dark cells.
    smooth_sigma is Gaussian pre-smoothing in pixels, used ONLY for background
    estimation; zero disables it. pad_pixels optionally reflection-pads this
    smoothed image before rolling-ball estimation and crops the result back.
    The input is never normalized, clipped or modified.
    """
    array = _image(image)
    for name, value, minimum in (("radius", radius, 1), ("pad_pixels", pad_pixels, 0)):
        if not isinstance(value, Integral) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}.")
    if not np.isfinite(kernel_height) or kernel_height <= 0:
        raise ValueError("kernel_height must be finite and positive.")
    if not np.isfinite(smooth_sigma) or smooth_sigma < 0:
        raise ValueError("smooth_sigma must be finite and non-negative.")
    if feature_polarity not in {"dark", "bright"}:
        raise ValueError("feature_polarity must be 'dark' or 'bright'.")

    work = gaussian_filter(array, smooth_sigma, mode="reflect") if smooth_sigma else array
    if pad_pixels:
        work = np.pad(work, pad_pixels, mode="reflect")
    offset = float(work.max()) if feature_polarity == "dark" else 0.0
    surface = offset - work if feature_polarity == "dark" else work
    y, x = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    squared_distance = (x / radius) ** 2 + (y / radius) ** 2
    support = squared_distance <= 1
    kernel = np.full(squared_distance.shape, np.inf)
    kernel[support] = kernel_height * np.sqrt(1 - squared_distance[support])
    background = rolling_ball(surface, kernel=kernel)
    if feature_polarity == "dark":
        background = offset - background
    if pad_pixels:
        background = background[pad_pixels:-pad_pixels, pad_pixels:-pad_pixels]
    return background.copy()


def correct_flat_field(
    image: ArrayLike,
    background: ArrayLike,
    *,
    min_background: float = 1e-6,
    reference_level: float | None = None,
) -> FlatFieldResult:
    """Correct multiplicative shading as image/background * reference_level.

    min_background is an absolute positive threshold in reflectance units.
    Nonfinite or <= threshold background pixels yield NaNs, not huge gains.
    reference_level defaults to the median of valid background pixels. This
    retains a representative reflectance scale, not the exact input mean.
    A supplied positive reference_level allows a common scale across images.
    Negative input values are retained; no clipping is performed.
    """
    array = _image(image)
    if np.iscomplexobj(background):
        raise ValueError("background must be real-valued.")
    field = np.asarray(background, dtype=float)
    if field.shape != array.shape:
        raise ValueError("background must have the same shape as image.")
    if not np.isfinite(min_background) or min_background <= 0:
        raise ValueError("min_background must be finite and positive.")
    valid = np.isfinite(field) & (field > min_background)
    if not valid.any():
        raise ValueError("No background pixels exceed min_background.")
    level = float(np.median(field[valid])) if reference_level is None else float(reference_level)
    if not np.isfinite(level) or level <= 0:
        raise ValueError("reference_level must be finite and positive.")
    gain = np.full(array.shape, np.nan)
    gain[valid] = level / field[valid]
    corrected = array * gain
    return FlatFieldResult(
        corrected=corrected, background=field.copy(), gain=gain,
        valid_mask=valid, change=corrected - array, reference_level=level,
    )


def rolling_ball_flat_field(
    image: ArrayLike,
    *,
    radius: int = 30,
    kernel_height: float = 0.05,
    feature_polarity: str = "dark",
    smooth_sigma: float = 1.0,
    pad_pixels: int = 0,
    min_background: float = 1e-6,
    reference_level: float | None = None,
) -> FlatFieldResult:
    """Estimate the field and apply correction to the original supplied image.

    Pre-smoothing changes only the background estimate; the numerator remains
    the Fourier-filtered image. See both helper functions for all parameters.
    """
    field = estimate_rolling_ball_background(
        image, radius=radius, kernel_height=kernel_height,
        feature_polarity=feature_polarity, smooth_sigma=smooth_sigma,
        pad_pixels=pad_pixels,
    )
    return correct_flat_field(
        image, field, min_background=min_background, reference_level=reference_level,
    )
