"""Numerical and export checks for the independent Fourier laboratory."""
import base64
import io
import json
import zipfile

import numpy as np
from PIL import Image
import pytest

from ui.app_fourier_lab import GLYPHS, analyze, calculate, export, make_image


def test_busy_port_falls_back_without_hiding_other_errors(monkeypatch):
    import errno
    from ui import app_fourier_lab as lab
    calls = []
    server = object()

    def bind(address, handler):
        calls.append(address)
        if address[1] == 8767:
            raise OSError(errno.EADDRINUSE, 'Address already in use')
        return server

    monkeypatch.setattr(lab, 'ThreadingHTTPServer', bind)
    assert lab.create_server(8767) is server
    assert calls == [('127.0.0.1', 8767), ('127.0.0.1', 0)]

    def forbidden(*args):
        raise PermissionError(errno.EACCES, 'Permission denied')

    monkeypatch.setattr(lab, 'ThreadingHTTPServer', forbidden)
    with pytest.raises(PermissionError):
        lab.create_server(8767)


@pytest.mark.parametrize("kind", ["letters", "rectangle", "disk", "bars", "checkerboard", "edge"])
def test_synthetic_sources(kind):
    image = make_image({"source": kind, "size": 128, "stroke": 5})
    assert image.shape == (128, 128)
    assert np.isfinite(image).all() and image.min() == 0 and image.max() == 1


def test_geometric_corners_and_uniform_stroke():
    square = make_image({"letters": "L", "size": 256, "stroke": 10, "corners": "square"})
    rounded = make_image({"letters": "L", "size": 256, "stroke": 10, "corners": "round", "corner_radius": 20})
    assert not np.array_equal(square, rounded)
    # Far from corners, changing corner style must not change the vertical stroke.
    np.testing.assert_array_equal(square[95:125, :80], rounded[95:125, :80])
    # Rasterization includes antialiased edge coverage (quarter-pixel sampling).
    assert square[100].sum() == pytest.approx(10, abs=.35)
    for letter in GLYPHS:
        for corners in ("square", "round"):
            assert make_image({"letters":letter,"corners":corners}).max() == 1


def test_letter_edge_smoothing_precedes_noise_and_retains_defaults():
    config = {'letters':'L','size':128,'stroke':6,'filter':'none'}
    sharp = make_image(config)
    np.testing.assert_array_equal(sharp, make_image({**config,'edge_smoothing':False,'edge_sigma':4}))
    np.testing.assert_array_equal(sharp, make_image({**config,'edge_smoothing':True,'edge_sigma':0}))
    smooth = make_image({**config,'edge_smoothing':True,'edge_sigma':2})
    assert smooth.min() >= 0 and smooth.max() <= 1
    assert smooth.sum() == pytest.approx(sharp.sum())
    assert np.max(np.abs(np.diff(smooth,axis=1))) < np.max(np.abs(np.diff(sharp,axis=1)))
    assert np.count_nonzero((smooth > .05) & (smooth < .95)) > np.count_nonzero((sharp > .05) & (sharp < .95))
    settings = {**config,'edge_smoothing':True,'edge_sigma':2,'gaussian':True,'noise_sigma':.08,'seed':4}
    arrays,_ = calculate(settings)
    np.testing.assert_array_equal(arrays['clean'],smooth)
    noise = np.random.default_rng(4).normal(0,.08*np.ptp(smooth),smooth.shape)
    np.testing.assert_allclose(arrays['input'],smooth+noise)
    with zipfile.ZipFile(io.BytesIO(export(settings))) as archive:
        metadata=json.loads(archive.read('settings.json'))
        assert metadata['edge_smoothing_effective']['enabled'] is True
        assert metadata['edge_smoothing_effective']['sigma_pixels'] == 2
    for sigma in (-1,21,float('nan')):
        with pytest.raises(ValueError,match='edge_sigma'):
            make_image({**config,'edge_smoothing':True,'edge_sigma':sigma})


def test_fixed_seed_and_filter_independence():
    config = {"source":"disk","size":128,"gaussian":True,"impulse":True,"stripes":True,"seed":17}
    a, _ = calculate({**config, "filter":"none"})
    b, _ = calculate({**config, "filter":"lowpass"})
    np.testing.assert_array_equal(a['input'], b['input'])
    np.testing.assert_allclose(a['input'], a['filtered'], atol=1e-14)
    np.testing.assert_array_equal(a['input'], calculate({**config,"filter":"none"})[0]['input'])
    assert not np.array_equal(a['input'], calculate({**config,"seed":18})[0]['input'])
    assert a['input'].min() < 0 and a['input'].max() > 1


@pytest.mark.parametrize("mode", ["none", "notch", "lowpass", "combined"])
def test_filter_arrays_and_axes(mode):
    arrays, out = calculate({"size":128,"stroke":5,"filter":mode,"notches":[[0,.125]],"padding":12,"gaussian":True})
    assert out.mask.shape == (152,152)
    assert len(out.fx) == len(out.fy) == 152
    np.testing.assert_allclose(out.spectrum_after, out.spectrum_before*out.mask)
    np.testing.assert_allclose(arrays['input'], arrays['filtered']+arrays['removed'])
    assert out.mask.min() >= 0 and out.mask.max() <= 1
    assert arrays['filtered'].mean() == pytest.approx(arrays['input'].mean())


def test_notch_rejects_added_stripes():
    arrays, _ = calculate({"source":"disk","size":128,"filter":"notch", "notches":[[0,.125]],
                          "sigma":.003,"stripes":True,"stripe_period":8,"stripe_amplitude":.4})
    assert np.mean((arrays['filtered']-arrays['clean'])**2) < np.mean((arrays['input']-arrays['clean'])**2)/10


def test_independent_zero_display_and_shared_scales():
    config={"size":128,"stroke":5,"gaussian":True}
    normal=analyze(config)
    zero=analyze({**config,"zero_images":["input"]})
    assert normal['metrics'] == zero['metrics']
    assert normal['profiles'] == zero['profiles']
    for before, after in zip(normal['cards'],zero['cards']):
        if before['key'] == 'input':
            assert after['vmin'] == 0 and after['png'] != before['png']
        else:
            assert after == before
    fft=[c for c in normal['cards'] if c['key'].startswith('fft_')]
    assert len({(c['vmin'],c['vmax']) for c in fft}) == 1
    assert len(normal['cards']) == 9


def test_import_preserves_csv_and_numeric_tiff():
    a = np.arange(128,dtype=float).reshape(8,16)-60
    csv=io.StringIO();np.savetxt(csv,a,delimiter=',')
    np.testing.assert_array_equal(make_image({'source':'upload','filename':'x.csv','file_data':base64.b64encode(csv.getvalue().encode()).decode()}),a)
    tiff=io.BytesIO();Image.fromarray(a.astype('float32')).save(tiff,format='TIFF')
    np.testing.assert_array_equal(make_image({'source':'upload','filename':'x.tif','file_data':base64.b64encode(tiff.getvalue()).decode()}),a)
    png=io.BytesIO();Image.new('RGB',(8,8),'white').save(png,format='PNG')
    np.testing.assert_array_equal(make_image({'source':'upload','filename':'x.png','file_data':base64.b64encode(png.getvalue()).decode()}),np.ones((8,8)))


def test_export_matches_calculated_arrays():
    config={'size':128,'stroke':5,'gaussian':True,'seed':99,'corners':'round','filter':'combined','notches':[[0,.125]]}
    arrays,out=calculate(config)
    with zipfile.ZipFile(io.BytesIO(export(config))) as archive:
        metadata=json.loads(archive.read('settings.json'))
        assert metadata['seed'] == 99
        assert 'file_data' not in metadata
        np.testing.assert_allclose(np.loadtxt(io.BytesIO(archive.read('filtered.csv')),delimiter=','),arrays['filtered'])
        with np.load(io.BytesIO(archive.read('arrays.npz'))) as data:
            np.testing.assert_array_equal(data['fft_after'],out.spectrum_after)
            np.testing.assert_array_equal(data['clean'],arrays['clean'])


@pytest.mark.parametrize('config', [{'source':'other'},{'size':20},{'stroke':0},{'letters':'hello!'},{'letters':'AAAAAA','stroke':30},
                                  {'filter':'oops'},{'cutoff_x':0},{'padding':100},{'seed':-1},{'notches':[[0,2]],'filter':'notch'}])
def test_invalid_inputs(config):
    with pytest.raises(ValueError):
        calculate(config)
