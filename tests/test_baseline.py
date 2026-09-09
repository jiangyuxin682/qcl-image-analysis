"""Verify pixelwise interpolation, multi-reference regression and data validity.

Tests use analytic spectra with known peaks and slopes; they also exercise
independent center configurations, invalid pixels and input immutability.
"""

import numpy as np
import pytest

from qcl_analysis.baseline import (
    correct_absorbance_baselines,
    linear_baseline_correction,
)


def test_unequally_spaced_two_reference_interpolation():
    low = np.array([[0.1, 0.2], [0.3, 0.4]])
    high = np.array([[0.3, 0.1], [0.5, 0.2]])
    baseline = low * (44 / 101) + high * (57 / 101)
    peak = np.array([[0.02, -0.01], [0.08, 0]])
    images = {1601: low, 1658: baseline + peak, 1702: high}
    before = {wn: a.copy() for wn, a in images.items()}
    result = linear_baseline_correction(images, 1658, [1702, 1601])
    np.testing.assert_allclose(result.baseline, baseline, atol=1e-14)
    np.testing.assert_allclose(result.corrected, peak, atol=1e-14)
    assert result.reference_wavenumbers == (1601, 1702)
    for wn, array in images.items():
        np.testing.assert_array_equal(array, before[wn])


def test_multiple_references_use_all_points_not_only_endpoints():
    refs = [1500, 1590, 1700, 1760]
    values = np.array([0.1, 0.21, 0.19, 0.35])
    expected_coeff = np.polyfit(refs, values, 1)
    images = {wn: np.full((2, 3), a) for wn, a in zip(refs, values)}
    images[1658] = np.full((2, 3), 0.4)
    result = linear_baseline_correction(images, 1658, refs)
    np.testing.assert_allclose(result.baseline, np.polyval(expected_coeff, 1658))
    np.testing.assert_allclose(result.slope, expected_coeff[0])


def test_independent_baselines_for_multiple_centers():
    images = {wn: np.full((3, 4), wn * 0.0001) for wn in [1500, 1550, 1600, 1658, 1702, 1750]}
    images[1600] += 0.04
    images[1658] += 0.08
    result = correct_absorbance_baselines(images, {1600: [1500, 1702], 1658: [1550, 1702, 1750]})
    np.testing.assert_allclose(result[1600].corrected, 0.04)
    np.testing.assert_allclose(result[1658].corrected, 0.08)


def test_invalid_pixels_do_not_silently_use_fewer_references():
    images = {wn: np.full((2, 3), 0.2) for wn in [1500, 1601, 1658, 1702]}
    images[1601][0, 0] = np.nan
    images[1702][0, 1] = np.inf
    images[1658][1, 0] = np.nan
    result = linear_baseline_correction(images, 1658, [1500, 1601, 1702])
    assert np.isnan(result.baseline[0, :2]).all()
    assert np.isnan(result.corrected[1, 0])
    assert np.isfinite(result.baseline[1, 0])
    assert result.valid_mask.sum() == 3


def test_all_invalid_references_produce_invalid_result():
    result = linear_baseline_correction({1601: [[np.nan]], 1658: [[0.2]], 1702: [[0.3]]}, 1658, [1601, 1702])
    assert np.isnan(result.corrected).all()
    assert not result.valid_mask.any()


def test_explicit_extrapolation():
    images = {1500: np.ones((2, 2)), 1600: np.full((2, 2), 2), 1700: np.full((2, 2), 3.5)}
    with pytest.raises(ValueError, match='bracket'):
        linear_baseline_correction(images, 1700, [1500, 1600])
    result = linear_baseline_correction(images, 1700, [1500, 1600], allow_extrapolation=True)
    np.testing.assert_allclose(result.corrected, 0.5)


@pytest.mark.parametrize('refs', [[1601], [1601, 1601], [1601, 1658], [1601, 1800], [np.nan, 1702]])
def test_invalid_references(refs):
    images = {wn: np.ones((2, 3)) for wn in [1601, 1658, 1702]}
    with pytest.raises(ValueError):
        linear_baseline_correction(images, 1658, refs)


@pytest.mark.parametrize('bad', [np.ones((4, 3)), np.ones(3), np.ones((2, 3), complex)])
def test_image_shapes_and_types(bad):
    with pytest.raises(ValueError):
        linear_baseline_correction({1601: bad, 1658: np.ones((2, 3)), 1702: np.ones((2, 3))}, 1658, [1601, 1702])


def test_empty_center_configuration_rejected():
    with pytest.raises(ValueError):
        correct_absorbance_baselines({}, {})
