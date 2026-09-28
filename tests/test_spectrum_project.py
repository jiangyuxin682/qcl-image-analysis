"""Full-spectrum project inputs must extend beyond processing bands."""
import io
import json
import zipfile

import numpy as np
import pytest
from test_app_processing import acquisition as acquisition_fixture
from test_app_processing import complete

from ui.app_processing import ProcessingState
from ui.reproduction import reproduce


@pytest.fixture
def acquisition(tmp_path):
    return acquisition_fixture.__wrapped__(tmp_path)


def settings(pattern='pattern0', filtered=False):
    return {'selection': {'pattern': pattern, 'wavenumber': 1658,
                         'analyte_roi': {'x_min': 8, 'x_max': 12, 'y_min': 6, 'y_max': 10},
                         'background_roi': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3}},
            'filters': {'fourier_enabled': filtered, 'sg_enabled': filtered, 'fourier_mode': 'combined',
                        'cutoff': .2, 'notch_centers': [.3], 'notch_width': .05, 'window': 3, 'order': 1},
            'view': {'mapping': {'1658': [1601, 1702]}, 'marker_center': 'all', 'colorbar_zero': True}}


def test_full_spectrum_includes_unused_band_and_deduplicates(acquisition):
    state = complete(acquisition)
    state.save_spectrum(settings())
    package = state.export()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        recipe = json.loads(archive.read('recipe.json'))
        assert 'spectrum/[1]_full_spectrum.csv' in archive.namelist()
        spectrum = recipe['spectrum']
        assert [i['wavenumber'] for i in spectrum['inputs']] == [1080, 1601, 1658, 1702]
        assert len([n for n in archive.namelist() if n.endswith('.npy')]) == 7
    (acquisition / 'stacks').rename(acquisition / 'unavailable')
    restored, report = reproduce(package)
    assert report['summary']['mismatch'] == 0
    assert len(restored.spectrum_project['result']['points']) == 4
    assert 1080 in restored.restored_state()['discovery']['wavenumbers']
    assert restored.raw_roi_spectrum(settings()['selection']) == restored.spectrum_project['result']
    # Re-export preserves the spectrum and extra input.
    again, report = reproduce(restored.export())
    assert report['summary']['mismatch'] == 0
    again._reproduction_inputs.cleanup()
    restored._reproduction_inputs.cleanup()


def test_spectrum_parameters_require_all_matching_external_bands(acquisition):
    state = complete(acquisition)
    state.save_spectrum(settings())
    package = state.export({'raw_inputs': False, 'spectrum': 'parameters'})
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert not any(n.endswith('.npy') for n in archive.namelist())
    with pytest.raises(ValueError, match='original raw'):
        reproduce(package)
    external = ProcessingState()
    external.discover({'path': str(acquisition)})
    restored, report = reproduce(package, external=external)
    assert report['summary']['mismatch'] == 0
    restored._reproduction_inputs.cleanup()
    extra = acquisition / 'stacks/pattern0/lineScan_1080_0invcm.csv'
    np.savetxt(extra, np.ones((16, 20)), delimiter=',')
    with pytest.raises(ValueError, match='spectrum source data differs'):
        reproduce(package, external=external)
    extra.unlink()
    external.discover({'path': str(acquisition)})
    with pytest.raises(ValueError, match='all measured bands'):
        reproduce(package, external=external)


def test_spectrum_filter_roundtrip_for_unprocessed_pattern(acquisition):
    folder = acquisition / 'stacks/pattern2'
    folder.mkdir()
    for wn in range(1655, 1662):
        image = np.ones((16, 20)) * 100
        image[6:10, 8:12] *= 1 - .05 * np.exp(-((wn - 1658) / 2)**2)
        np.savetxt(folder / f'lineScan_{wn}_0invcm.csv', image, delimiter=',')
    state = complete(acquisition)
    state.save_spectrum(settings('pattern2', True))
    restored, report = reproduce(state.export())
    assert report['summary']['mismatch'] == 0
    for field in ('absorbance_fourier', 'absorbance_sg', 'absorbance_filtered'):
        np.testing.assert_allclose(restored.spectrum_project['filtered'][field], state.spectrum_project['filtered'][field])
    assert any(c['item'] == 'Full spectrum/absorbance_filtered' for c in report['checks'])
    restored._reproduction_inputs.cleanup()


def test_spectrum_exclusion_and_failed_save_preserve_previous(acquisition):
    state = complete(acquisition)
    state.save_spectrum(settings())
    previous = state.spectrum_project
    with pytest.raises(ValueError):
        state.save_spectrum(settings(filtered=True))  # Uneven bands cannot be filtered.
    assert state.spectrum_project is previous
    with zipfile.ZipFile(io.BytesIO(state.export({'spectrum': 'none'}))) as archive:
        assert json.loads(archive.read('recipe.json'))['spectrum'] is None


def test_spectrum_preserves_invalid_band_gaps(acquisition):
    path = acquisition / 'stacks/pattern0/lineScan_1080_0invcm.csv'
    array = np.loadtxt(path, delimiter=',')
    array[:3, :3] = 0  # A nonpositive ROI mean produces a spectral gap.
    np.savetxt(path, array, delimiter=',')
    state = complete(acquisition)
    state.save_spectrum(settings())
    restored, report = reproduce(state.export())
    assert report['summary']['mismatch'] == 0
    assert restored.spectrum_project['result']['points'][0]['absorbance'] is None
    restored._reproduction_inputs.cleanup()
