"""Verify known gold translations, shared spectral crops and failure handling."""
import numpy as np
import pytest
from qcl_analysis.drift import gold_drift_rois
from qcl_analysis.roi import ROI


def frame(dx=0):
    image = np.full((30, 100), 0.5)
    image[:, 10+dx:15+dx] = 1
    image[:, 80+dx:85+dx] = 1
    return image


@pytest.mark.parametrize('side', ['left', 'right', 'both'])
def test_horizontal_gold_tracking(side):
    images = {'reference': frame(), 'next': frame(5), 'previous': frame(-4)}
    roi = ROI(25, 65, 5, 25)
    rois, records = gold_drift_rois(images, 'reference', roi, side, 10)
    assert rois['next'] == ROI(30, 70, 5, 25)
    assert rois['previous'] == ROI(21, 61, 5, 25)
    assert [r['dx'] for r in records] == [0, 5, -4]


def test_ambiguous_gold_rejected():
    with pytest.raises(ValueError, match='distinguished'):
        gold_drift_rois({'ref': np.ones((30, 100))}, 'ref', ROI(25, 65, 5, 25))
    inconsistent = frame(5)
    inconsistent[:, 85:90] = .5
    inconsistent[:, 75:80] = 1
    with pytest.raises(ValueError, match='disagree'):
        gold_drift_rois({'ref': frame(), 'bad': inconsistent}, 'ref', ROI(25, 65, 5, 25))


def test_crop_pipeline_uses_pattern_rois():
    from ui.app_processing import ProcessingState
    state = ProcessingState()
    state.stage = 'configured'
    state.patterns = ['p0', 'p1']
    state.bands = [1601, 1658]
    state.ref = {(p, w): frame(dx) for p, dx in [('p0', 0), ('p1', 5)] for w in state.bands}
    state.raw = {k: v * 100 for k, v in state.ref.items()}
    payload = {'roi': {'x_min': 25, 'x_max': 65, 'y_min': 5, 'y_max': 25},
               'drift': {'enabled': True, 'reference_pattern': 'p0', 'wavenumber': 1658, 'side': 'both', 'max_shift': 10}}
    state.crop_plan(payload)
    assert state.stage == 'configured' and not state.crops
    state.crop(payload)
    for wn in state.bands:
        np.testing.assert_array_equal(state.crops[('p1', wn)], state.ref[('p1', wn)][5:25,30:70])
        np.testing.assert_array_equal(state.stage_arrays(('p1', wn))['raw'], state.raw[('p1', wn)][5:25,30:70])
    payload['drift']['enabled'] = False
    state.crop(payload)
    assert state.on_rois['p0'] == state.on_rois['p1']
