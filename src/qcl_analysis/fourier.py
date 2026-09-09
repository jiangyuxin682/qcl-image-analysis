"""Filter image spatial frequencies with Gaussian notches or a 2D low-pass.

The image is transformed with a 2D FFT, multiplied by a real, conjugate-
symmetric rejection mask, and inverse transformed. Frequencies are always
(fy, fx) in cycles/pixel, not infrared wavenumbers. A center and its negative
are handled together, including the periodic boundary at the Nyquist frequency.
No clipping or intensity normalization is applied to the filtered image.
"""

from dataclasses import dataclass
from numbers import Integral

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class FourierFilterResult:
    """Store the output and diagnostic arrays without changing the input.

    filtered and removed have the original image shape. mask and both spectra
    have the padded shape and use fftshift ordering (DC at the center).
    removed equals input minus filtered; it may contain real specimen detail.
    """

    filtered: NDArray[np.float64]
    removed: NDArray[np.float64]
    mask: NDArray[np.float64]
    spectrum_before: NDArray[np.complex128]
    spectrum_after: NDArray[np.complex128]
    fy: NDArray[np.float64]
    fx: NDArray[np.float64]


def _image_array(image: ArrayLike) -> NDArray[np.float64]:
    """Validate a finite, real 2D image and return a floating-point array."""
    if np.iscomplexobj(image):
        raise ValueError("image must be real-valued.")
    array = np.asarray(image, dtype=np.float64)
    if array.ndim != 2 or min(array.shape) < 2:
        raise ValueError("image must be 2D with at least two pixels per axis.")
    if not np.isfinite(array).all():
        raise ValueError("image must contain only finite values; handle NaNs first.")
    return array


def fourier_spectrum(
    image: ArrayLike, *, window: bool = False
) -> tuple[NDArray, NDArray, NDArray]:
    """Return a centered complex spectrum and (fy, fx) frequency axes.

    window=True subtracts the mean and applies a separable Hann window for
    peak inspection only. This reduces edge leakage but changes amplitudes.
    The filtering function never applies this inspection window to the data.
    Plot log1p(abs(spectrum)) to see weaker periodic peaks.
    """
    array = _image_array(image)
    if window:
        array = (array - array.mean()) * np.outer(
            np.hanning(array.shape[0]), np.hanning(array.shape[1])
        )
    spectrum = np.fft.fftshift(np.fft.fft2(array))
    fy = np.fft.fftshift(np.fft.fftfreq(array.shape[0]))
    fx = np.fft.fftshift(np.fft.fftfreq(array.shape[1]))
    return spectrum, fy, fx


def gaussian_notch_mask(
    shape: tuple[int, int],
    centers: ArrayLike,
    *,
    sigma: float = 0.01,
    strength: float = 0.9,
    protect_radius: float = 0.02,
) -> NDArray[np.float64]:
    """Build a centered mask for paired Gaussian notch rejection.

    Parameters
    ----------
    shape : (height, width)
        FFT array shape.
    centers : sequence of (fy, fx)
        Artifact frequencies in cycles/pixel, each in [-0.5, 0.5]. Supply only
        one member of each +/- pair. Empty centers return an identity mask.
        (0, 0.125) targets vertical stripes with an 8-pixel horizontal period;
        (0.125, 0) targets horizontal stripes. Add harmonics explicitly.
    sigma : float
        Gaussian standard deviation in cycles/pixel, strictly positive.
        FWHM is about 2.355*sigma. Larger values remove a broader band.
    strength : float
        Rejection depth from 0 (identity) to 1 (full rejection at the exact
        center). Overlapping notches use maximum rejection, not compounded
        rejection, so duplicate centers do not increase strength.
    protect_radius : float
        Frequencies at radial distance <= this value pass unchanged. DC is
        always protected. A center inside this disk is rejected as invalid.
        This disk has a hard boundary; keep notches well away from it.

    Notes
    -----
    Distances wrap at +/-0.5, preserving symmetry at Nyquist. Gaussian tails
    extend beyond the nominal width. The mask attenuates real sample content
    at the same frequencies as the artifact; it cannot distinguish the two.
    """
    if len(shape) != 2 or any(
        not isinstance(n, Integral) or isinstance(n, bool) or n < 2 for n in shape
    ):
        raise ValueError("shape must contain two integers >= 2.")
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("sigma must be finite and positive.")
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("strength must be between 0 and 1.")
    if not np.isfinite(protect_radius) or not 0 <= protect_radius < 0.5:
        raise ValueError("protect_radius must be in [0, 0.5).")
    points = np.asarray(centers, dtype=float)
    if points.shape == (0,):
        points = points.reshape(0, 2)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("centers must be a sequence of (fy, fx) pairs.")
    if not np.isfinite(points).all() or (np.abs(points) > 0.5).any():
        raise ValueError("center frequencies must be finite and within [-0.5, 0.5].")
    if np.any(np.linalg.norm(points, axis=1) <= protect_radius):
        raise ValueError("notch centers must lie outside the protected low-frequency disk.")

    fy = np.fft.fftshift(np.fft.fftfreq(shape[0]))[:, None]
    fx = np.fft.fftshift(np.fft.fftfreq(shape[1]))[None, :]
    rejection = np.zeros(shape, dtype=float)
    for cy, cx in points:
        for sign in (-1, 1):
            dy = (fy - sign * cy + 0.5) % 1.0 - 0.5
            dx = (fx - sign * cx + 0.5) % 1.0 - 0.5
            notch = np.exp(-0.5 * ((dy / sigma) ** 2 + (dx / sigma) ** 2))
            rejection = np.maximum(rejection, notch)
    mask = 1.0 - strength * rejection
    mask[np.hypot(fy, fx) <= protect_radius] = 1.0
    return mask


def apply_fourier_notch_filter(
    image: ArrayLike,
    centers: ArrayLike,
    *,
    sigma: float = 0.01,
    strength: float = 0.9,
    protect_radius: float = 0.02,
    pad_pixels: int = 0,
    preserve_mean: bool = True,
) -> FourierFilterResult:
    """Filter a reflectance image and return output plus Fourier diagnostics.

    centers, sigma, strength and protect_radius are described in
    gaussian_notch_mask. pad_pixels adds reflection padding on all sides to
    reduce periodic-boundary artifacts, then crops back to the original shape.
    Padding changes peak shapes: inspect the actual padded spectra as well.
    preserve_mean restores the original mean after cropping; this is useful
    with padding, but does not guarantee preservation of local ROI means.
    spectrum_after describes the padded masked transform before the optional
    final mean adjustment. Negative output values are retained, never clipped.
    """
    array = _image_array(image)
    if (
        not isinstance(pad_pixels, Integral)
        or isinstance(pad_pixels, bool)
        or pad_pixels < 0
    ):
        raise ValueError("pad_pixels must be a non-negative integer.")
    padded = np.pad(array, pad_pixels, mode="reflect") if pad_pixels else array
    spectrum, fy, fx = fourier_spectrum(padded)
    mask = gaussian_notch_mask(
        padded.shape, centers, sigma=sigma, strength=strength,
        protect_radius=protect_radius,
    )
    masked = spectrum * mask
    reconstructed = np.fft.ifft2(np.fft.ifftshift(masked)).real
    if pad_pixels:
        reconstructed = reconstructed[
            pad_pixels:-pad_pixels, pad_pixels:-pad_pixels
        ]
    filtered = reconstructed.copy()
    if preserve_mean:
        filtered += array.mean() - filtered.mean()
    return FourierFilterResult(
        filtered=filtered, removed=array - filtered, mask=mask,
        spectrum_before=spectrum, spectrum_after=masked, fy=fy, fx=fx,
    )


def gaussian_lowpass_mask(
    shape: tuple[int, int], *, cutoff: float = 0.1,
    cutoff_x: float | None = None, cutoff_y: float | None = None,
) -> NDArray[np.float64]:
    """Build an axis-aligned elliptical Gaussian low-pass in FFT order.

    cutoff_x and cutoff_y are independent HALF-AMPLITUDE frequency widths
    in cycles/pixel, each in (0, 0.5]. An omitted axis uses cutoff, preserving
    the original circular API. cutoff remains a valid positive fallback.
    H(fy, fx) = exp(-log(2) * ((fx/cutoff_x)**2 + (fy/cutoff_y)**2)).
    The H=0.5 contour is an ellipse with semi-axes cutoff_x and cutoff_y;
    full widths are twice these values. Equal axes recover a circular mask.
    A smaller x cutoff smooths variation along image columns more strongly
    (including vertical stripes); a smaller y cutoff smooths variation along
    rows more strongly (including horizontal stripes). H(0,0)=1.
    These are smooth half-amplitude widths, not hard cutoffs or -3 dB points.
    """
    if len(shape) != 2 or any(
        not isinstance(n, Integral) or isinstance(n, bool) or n < 2 for n in shape
    ):
        raise ValueError("shape must contain two integers >= 2.")
    if not np.isfinite(cutoff) or not 0 < cutoff <= 0.5:
        raise ValueError("cutoff must be finite and in (0, 0.5] cycles/pixel.")
    width_x = cutoff if cutoff_x is None else cutoff_x
    width_y = cutoff if cutoff_y is None else cutoff_y
    for name, width in (("cutoff_x", width_x), ("cutoff_y", width_y)):
        if not np.isfinite(width) or not 0 < width <= 0.5:
            raise ValueError(f"{name} must be finite and in (0, 0.5] cycles/pixel.")
    fy = np.fft.fftshift(np.fft.fftfreq(shape[0]))[:, None]
    fx = np.fft.fftshift(np.fft.fftfreq(shape[1]))[None, :]
    # Extremely small valid cutoffs underflow to a DC-only transmission mask.
    with np.errstate(over="ignore", under="ignore"):
        mask = np.exp(-np.log(2.0) * ((fx / width_x) ** 2 + (fy / width_y) ** 2))
    return mask


def apply_fourier_lowpass_filter(
    image: ArrayLike,
    *,
    cutoff: float = 0.1,
    cutoff_x: float | None = None,
    cutoff_y: float | None = None,
    pad_pixels: int = 0,
    preserve_mean: bool = True,
) -> FourierFilterResult:
    """Apply an elliptical 2D Gaussian low-pass to the supplied image.

    The unwindowed FFT is multiplied by gaussian_lowpass_mask and inverse
    transformed. Unlike a notch filter, this attenuates ALL directions of
    high-frequency content, including real cell edges and fine textures.
    cutoff_x and cutoff_y set the axis half-amplitude frequencies. Each
    defaults to cutoff when omitted; see gaussian_lowpass_mask.
    Reflection padding and mean restoration follow apply_fourier_notch_filter.
    The original array is unchanged; the result has the original shape and
    is not clipped. Diagnostics describe the padded transform before any
    final mean adjustment. No notch parameters are applied in this mode.
    """
    array = _image_array(image)
    if (
        not isinstance(pad_pixels, Integral)
        or isinstance(pad_pixels, bool)
        or pad_pixels < 0
    ):
        raise ValueError("pad_pixels must be a non-negative integer.")
    padded = np.pad(array, pad_pixels, mode="reflect") if pad_pixels else array
    spectrum, fy, fx = fourier_spectrum(padded)
    mask = gaussian_lowpass_mask(
        padded.shape, cutoff=cutoff, cutoff_x=cutoff_x, cutoff_y=cutoff_y,
    )
    masked = spectrum * mask
    reconstructed = np.fft.ifft2(np.fft.ifftshift(masked)).real
    if pad_pixels:
        reconstructed = reconstructed[
            pad_pixels:-pad_pixels, pad_pixels:-pad_pixels
        ]
    filtered = reconstructed.copy()
    if preserve_mean:
        filtered += array.mean() - filtered.mean()
    return FourierFilterResult(
        filtered=filtered, removed=array - filtered, mask=mask,
        spectrum_before=spectrum, spectrum_after=masked, fy=fy, fx=fx,
    )
