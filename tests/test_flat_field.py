"""Check rolling-ball estimates, multiplicative correction and failure cases.

Known fields provide an exact division target. Synthetic dark/bright features
check polarity and feature preservation independently of experimental images.
"""

import numpy as np
import pytest

from qcl_analysis.flat_field import (
    correct_flat_field,
    estimate_rolling_ball_background,
    rolling_ball_flat_field,
)


@pytest.mark.parametrize('polarity', ['dark', 'bright'])
@pytest.mark.parametrize('padding', [0, 5])
def test_constant_image_is_unchanged(polarity, padding):
    image = np.full((31, 37), 0.65)
    before = image.copy()
    result = rolling_ball_flat_field(image, radius=8, feature_polarity=polarity, pad_pixels=padding)
    np.testing.assert_allclose(result.corrected, image, atol=1e-14)
    np.testing.assert_allclose(result.background, image, atol=1e-14)
    np.testing.assert_array_equal(image, before)
    assert result.corrected.shape == image.shape


def test_known_multiplicative_field_is_removed():
    y, x = np.mgrid[:40, :50]
    background = 0.4 + 0.3 * x / 49
    specimen = 1 - 0.15 * np.exp(-((x - 25)**2 + (y - 20)**2) / 20)
    observed = background * specimen
    result = correct_flat_field(observed, background, reference_level=0.6)
    np.testing.assert_allclose(result.corrected, 0.6 * specimen)
    np.testing.assert_allclose(result.change, result.corrected - observed)


@pytest.mark.parametrize('polarity,sign', [('dark', -1), ('bright', 1)])
def test_rolling_ball_preserves_small_feature_and_flattens_gradient(polarity, sign):
    y, x = np.mgrid[:65, :65]
    background = 0.6 + 0.08 * x / 64
    feature = np.exp(-((x - 32)**2 + (y - 32)**2) / 4)
    observed = background + sign * 0.08 * feature
    result = rolling_ball_flat_field(
        observed, radius=14, kernel_height=0.02,
        feature_polarity=polarity, smooth_sigma=0,
    )
    blank = (x > 15) & (x < 50) & (y < 15)
    assert result.corrected[blank].std() < observed[blank].std() * 0.2
    contrast = result.corrected[32, 32] - np.median(result.corrected[blank])
    assert sign * contrast > 0.06
    assert np.mean(np.abs(result.background[blank] - background[blank])) < 0.01


def test_polarity_inversion_symmetry():
    image = np.random.default_rng(1).uniform(0.4, 0.7, (20, 25))
    lower = estimate_rolling_ball_background(image, radius=5, feature_polarity='bright', smooth_sigma=0)
    upper_inverted = estimate_rolling_ball_background(1-image, radius=5, feature_polarity='dark', smooth_sigma=0)
    np.testing.assert_allclose(lower, 1-upper_inverted, atol=1e-14)


def test_invalid_background_is_masked_not_floored():
    field = np.array([[0.5, 0], [np.nan, -0.1]])
    result = correct_flat_field(np.ones((2, 2)), field)
    np.testing.assert_array_equal(result.valid_mask, [[True, False], [False, False]])
    assert np.isnan(result.corrected[~result.valid_mask]).all()
    assert result.reference_level == 0.5


def test_smoothing_is_not_applied_to_correction_numerator():
    image = np.random.default_rng(2).uniform(0.5, 0.7, (20, 25))
    result = rolling_ball_flat_field(image, radius=5, smooth_sigma=2)
    np.testing.assert_allclose(result.corrected, image * result.gain)


@pytest.mark.parametrize('kwargs', [
    {'radius': 0}, {'radius': 1.5}, {'kernel_height': 0},
    {'kernel_height': np.nan}, {'smooth_sigma': -1},
    {'feature_polarity': 'mixed'}, {'pad_pixels': -1},
])
def test_invalid_estimation_parameters(kwargs):
    with pytest.raises(ValueError):
        estimate_rolling_ball_background(np.ones((5, 6)), **kwargs)


@pytest.mark.parametrize('kwargs', [{'min_background': 0}, {'reference_level': -1}])
def test_invalid_correction_parameters(kwargs):
    with pytest.raises(ValueError):
        correct_flat_field(np.ones((5, 6)), np.ones((5, 6)), **kwargs)


def test_no_valid_background_fails():
    with pytest.raises(ValueError):
        correct_flat_field(np.ones((5, 6)), np.zeros((5, 6)))


@pytest.mark.parametrize('image', [np.ones(8), [[np.nan, 1], [1, 1]], np.ones((2, 2), complex)])
def test_invalid_input_image(image):
    with pytest.raises(ValueError):
        rolling_ball_flat_field(image)
