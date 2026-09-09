"""Validate Fourier rejection using known signals and numerical invariants.

Synthetic sinusoids provide exact target frequencies and known clean images.
The tests also check conjugate symmetry on odd/even FFT grids, mean handling,
input immutability, malformed parameters, and unchanged-data configurations.
"""

import numpy as np
import pytest

from qcl_analysis.fourier import (
    apply_fourier_notch_filter,
    fourier_spectrum,
    gaussian_notch_mask,
)


def test_known_grid_removed_while_other_frequency_is_preserved():
    y, x = np.mgrid[:96, :128]
    clean = 0.6 + 0.05 * np.cos(2 * np.pi * x / 64)
    grid = 0.04 * np.cos(2 * np.pi * x / 8) + 0.03 * np.cos(2 * np.pi * y / 12)
    image = clean + grid
    original = image.copy()
    result = apply_fourier_notch_filter(
        image, [(0, 1 / 8), (1 / 12, 0)], sigma=0.003, strength=1,
    )
    np.testing.assert_allclose(result.filtered, clean, atol=1e-12)
    np.testing.assert_allclose(result.removed, grid, atol=1e-12)
    np.testing.assert_array_equal(image, original)


@pytest.mark.parametrize('shape', [(63, 81), (64, 80), (63, 80)])
def test_mask_is_conjugate_symmetric_including_nyquist(shape):
    shifted = gaussian_notch_mask(shape, [(0.49, 0.48), (0.5, 0), (0.12, -0.21)])
    mask = np.fft.ifftshift(shifted)
    partner = mask[np.ix_((-np.arange(shape[0])) % shape[0],
                          (-np.arange(shape[1])) % shape[1])]
    np.testing.assert_allclose(mask, partner, atol=1e-14)
    assert mask[0, 0] == 1
    assert mask.min() >= 0 and mask.max() <= 1


@pytest.mark.parametrize('padding', [0, 12])
@pytest.mark.parametrize('centers,strength', [([], 1), ([(0.1, 0.2)], 0)])
def test_identity_and_original_shape(padding, centers, strength):
    image = np.random.default_rng(2).uniform(0.1, 1, (31, 44))
    result = apply_fourier_notch_filter(image, centers, strength=strength, pad_pixels=padding)
    np.testing.assert_allclose(result.filtered, image, atol=1e-14)
    assert result.mask.shape == (31 + 2 * padding, 44 + 2 * padding)


def test_padding_restores_global_mean_and_keeps_negative_values():
    image = np.random.default_rng(1).normal(0, 1, (33, 48))
    result = apply_fourier_notch_filter(image, [(0.1, 0.2)], pad_pixels=10)
    assert result.filtered.mean() == pytest.approx(image.mean(), abs=1e-14)
    assert (result.filtered < 0).any()
    np.testing.assert_allclose(result.filtered + result.removed, image, atol=1e-14)


def test_duplicate_and_partner_centers_do_not_compound_strength():
    a = gaussian_notch_mask((64, 80), [(0.125, 0.2)], strength=0.6)
    b = gaussian_notch_mask((64, 80), [(0.125, 0.2), (-0.125, -0.2), (0.125, 0.2)], strength=0.6)
    np.testing.assert_allclose(a, b)
    assert a.min() == pytest.approx(0.4)


def test_inspection_window_does_not_modify_input():
    image = np.ones((16, 24))
    spectrum, fy, fx = fourier_spectrum(image, window=True)
    np.testing.assert_allclose(spectrum, 0)
    np.testing.assert_array_equal(image, 1)
    assert len(fy) == 16 and len(fx) == 24


@pytest.mark.parametrize('kwargs', [
    {'sigma': 0}, {'sigma': np.nan}, {'strength': 1.1},
    {'protect_radius': -0.1}, {'pad_pixels': -1}, {'pad_pixels': 1.5},
])
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        apply_fourier_notch_filter(np.ones((8, 9)), [(0.2, 0.1)], **kwargs)


@pytest.mark.parametrize('centers', [[(0, 0)], [(0.01, 0)], [(0.6, 0)], [(np.nan, 0)], [0.1, 0.2]])
def test_invalid_centers(centers):
    with pytest.raises(ValueError):
        gaussian_notch_mask((8, 9), centers)


@pytest.mark.parametrize('image', [np.ones(8), np.ones((1, 8)), [[np.nan, 1], [1, 1]], np.ones((2, 2), complex)])
def test_invalid_images(image):
    with pytest.raises(ValueError):
        apply_fourier_notch_filter(image, [])


@pytest.mark.parametrize('shape', [(64, 80), (63, 81)])
def test_lowpass_symmetry_and_radial_falloff(shape):
    """Low-pass transmission must be symmetric, bounded and centered at DC."""
    from qcl_analysis.fourier import gaussian_lowpass_mask

    shifted = gaussian_lowpass_mask(shape, cutoff=0.1)
    mask = np.fft.ifftshift(shifted)
    partner = mask[np.ix_((-np.arange(shape[0])) % shape[0],
                          (-np.arange(shape[1])) % shape[1])]
    np.testing.assert_allclose(mask, partner, atol=1e-14)
    assert mask[0, 0] == 1
    assert 0 <= mask.min() <= mask.max() <= 1
    assert mask[0, 1] > mask[0, 2] > mask[0, 3]


def test_lowpass_analytical_amplitude_response_in_two_dimensions():
    """Known Fourier-bin sinusoids verify cutoff and diagonal attenuation."""
    from qcl_analysis.fourier import apply_fourier_lowpass_filter

    y, x = np.mgrid[:128, :128]
    cutoff = 0.125
    low = np.cos(2 * np.pi * x / 32)
    at_cutoff = np.cos(2 * np.pi * y / 8)
    diagonal = np.cos(2 * np.pi * (x + y) / 8)
    high = np.cos(2 * np.pi * x / 4)
    image = 0.6 + 0.02 * (low + at_cutoff + diagonal + high)
    before = image.copy()
    result = apply_fourier_lowpass_filter(image, cutoff=cutoff)
    expected = 0.6 + 0.02 * (
        2 ** (-0.25**2) * low + 0.5 * at_cutoff
        + 0.25 * diagonal + 0.0625 * high
    )
    np.testing.assert_allclose(result.filtered, expected, atol=1e-14)
    np.testing.assert_array_equal(image, before)
    np.testing.assert_allclose(result.filtered + result.removed, image)


@pytest.mark.parametrize('padding', [0, 12])
def test_lowpass_preserves_constant_and_shape(padding):
    """DC transmission must not change constant reflectance, even with padding."""
    from qcl_analysis.fourier import apply_fourier_lowpass_filter

    image = np.full((31, 44), 0.73)
    result = apply_fourier_lowpass_filter(image, pad_pixels=padding)
    np.testing.assert_allclose(result.filtered, image, atol=1e-14)
    assert result.filtered.shape == image.shape
    assert result.mask.shape == (31 + 2 * padding, 44 + 2 * padding)


def test_lowpass_mean_restoration_after_padding():
    """Cropping the inverse transform must still preserve the requested mean."""
    from qcl_analysis.fourier import apply_fourier_lowpass_filter

    image = np.random.default_rng(5).normal(size=(31, 44))
    result = apply_fourier_lowpass_filter(image, cutoff=0.04, pad_pixels=13)
    assert result.filtered.mean() == pytest.approx(image.mean(), abs=1e-14)
    assert np.isfinite(result.filtered).all()


@pytest.mark.parametrize('cutoff', [0, -0.1, 0.51, np.nan, np.inf])
def test_lowpass_invalid_cutoff(cutoff):
    """Invalid frequency parameters must fail before producing output."""
    from qcl_analysis.fourier import apply_fourier_lowpass_filter

    with pytest.raises(ValueError):
        apply_fourier_lowpass_filter(np.ones((8, 9)), cutoff=cutoff)



def test_elliptical_lowpass_directional_response():
    """Independent axis widths must produce the expected directional gains."""
    from qcl_analysis.fourier import apply_fourier_lowpass_filter

    y, x = np.mgrid[:128, :128]
    along_x = np.cos(2 * np.pi * x / 8)
    along_y = np.cos(2 * np.pi * y / 8)
    image = 0.6 + 0.03 * (along_x + along_y)
    result = apply_fourier_lowpass_filter(image, cutoff_x=0.0625, cutoff_y=0.125)
    expected = 0.6 + 0.03 * (0.0625 * along_x + 0.5 * along_y)
    np.testing.assert_allclose(result.filtered, expected, atol=1e-14)


@pytest.mark.parametrize("shape", [(64, 80), (63, 81)])
def test_elliptical_mask_symmetry_and_equal_axis_compatibility(shape):
    """Odd/even arrays preserve conjugate symmetry and circular compatibility."""
    from qcl_analysis.fourier import gaussian_lowpass_mask

    circle = gaussian_lowpass_mask(shape, cutoff=0.15)
    equal = gaussian_lowpass_mask(shape, cutoff_x=0.15, cutoff_y=0.15)
    np.testing.assert_allclose(circle, equal, atol=1e-14)
    mask = np.fft.ifftshift(gaussian_lowpass_mask(shape, cutoff_x=0.08, cutoff_y=0.2))
    partner = mask[np.ix_((-np.arange(shape[0])) % shape[0],
                          (-np.arange(shape[1])) % shape[1])]
    np.testing.assert_allclose(mask, partner, atol=1e-14)
    assert mask[0, 0] == 1


@pytest.mark.parametrize("axis", ["cutoff_x", "cutoff_y"])
@pytest.mark.parametrize("value", [0, -0.1, 0.51, np.nan, np.inf])
def test_invalid_elliptical_axis_width(axis, value):
    """Both independently supplied widths require valid frequencies."""
    from qcl_analysis.fourier import apply_fourier_lowpass_filter

    with pytest.raises(ValueError):
        apply_fourier_lowpass_filter(np.ones((8, 9)), **{axis: value})
