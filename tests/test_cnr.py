"""Validate CNR definition, scale invariance and matched pixels across stages."""

import numpy as np
import pytest

from qcl_analysis.cnr import calculate_roi_cnr, compare_stage_cnr
from qcl_analysis.roi import ROI

BG = ROI(0, 2, 0, 2)
TARGET = ROI(2, 4, 0, 2)


def test_known_cnr_and_negative_contrast():
    image = np.array([[1, 2, 0, 0], [3, 4, 0, 0]], dtype=float)
    result = calculate_roi_cnr(image, BG, TARGET)
    assert result.background_mean == 2.5
    assert result.background_std == pytest.approx(np.sqrt(5 / 3))
    assert result.signed_contrast == -2.5
    assert result.cnr == pytest.approx(2.5 / np.sqrt(5 / 3))
    assert result.background_pixels == result.target_pixels == 4
    assert result.status == 'valid'


def test_cnr_is_invariant_to_scalar_normalization_and_offset():
    image = np.array([[1, 2, 6, 7], [3, 4, 8, 9]], dtype=float)
    a = calculate_roi_cnr(image, BG, TARGET)
    b = calculate_roi_cnr(image / 10, BG, TARGET)
    c = calculate_roi_cnr(image + 20, BG, TARGET)
    assert a.cnr == pytest.approx(b.cnr)
    assert a.cnr == pytest.approx(c.cnr)


def test_common_mask_prevents_stage_dependent_pixel_counts():
    a = np.array([[1, 2, 6, 7], [3, 4, 8, 9]], dtype=float)
    b = a.copy()
    b[0, 0] = np.nan
    b[0, 2] = np.inf
    original = a.copy()
    rows = compare_stage_cnr({'raw': a, 'processed': b, 'missing': None}, BG, TARGET)
    for row in rows[:2]:
        assert row['background_pixels'] == row['target_pixels'] == 3
        assert row['excluded_background_pixels'] == row['excluded_target_pixels'] == 1
    assert rows[0]['cnr'] == pytest.approx(rows[1]['cnr'])
    assert rows[2]['status'] == 'unavailable'
    assert np.isnan(rows[2]['cnr'])
    np.testing.assert_array_equal(a, original)


def test_constant_background_has_undefined_cnr():
    image = np.array([[1, 1, 4, 4], [1, 1, 4, 4]], dtype=float)
    result = calculate_roi_cnr(image, BG, TARGET)
    assert result.status == 'zero_background_noise'
    assert np.isnan(result.cnr)


def test_insufficient_common_pixels():
    image = np.ones((2, 4))
    image[0, :2] = np.nan
    image[1, 0] = np.nan
    result = calculate_roi_cnr(image, BG, TARGET)
    assert result.status == 'insufficient_background_pixels'
    assert np.isnan(result.cnr)


def test_empty_target_is_reported():
    image = np.array([[1, 2, np.nan, np.nan], [3, 4, np.nan, np.nan]])
    assert calculate_roi_cnr(image, BG, TARGET).status == 'insufficient_target_pixels'


def test_overlap_is_rejected():
    with pytest.raises(ValueError, match='overlap'):
        calculate_roi_cnr(np.ones((4, 4)), BG, ROI(1, 3, 1, 3))


def test_roi_outside_image_is_rejected():
    with pytest.raises(ValueError):
        calculate_roi_cnr(np.ones((2, 4)), BG, ROI(3, 6, 0, 2))


def test_stage_shape_mismatch_is_rejected():
    with pytest.raises(ValueError, match='shape'):
        compare_stage_cnr({'a': np.ones((2, 4)), 'b': np.ones((4, 4))}, BG, TARGET)


@pytest.mark.parametrize('mask', [np.ones((2, 4)), np.ones((3, 4), dtype=bool)])
def test_mask_must_be_boolean_with_matching_shape(mask):
    with pytest.raises(ValueError):
        calculate_roi_cnr(np.ones((2, 4)), BG, TARGET, valid_mask=mask)


def test_no_available_stages_is_rejected():
    with pytest.raises(ValueError):
        compare_stage_cnr({'missing': None}, BG, TARGET)
