"""Exercise filename discovery and the complete shared-band processing workflow.

Small synthetic spectral stacks verify mapping validation, numerical baseline
weights, synchronized CNR, export fidelity and downstream invalidation.
"""

import base64
import io
import itertools
import json
import zipfile

import numpy as np
import pytest

from ui.app import render_data_png
from ui.app_processing import (
    ProcessingState,
    clean_json,
    discover_files,
    select_cell_free_pixels,
)


def test_extreme_pixel_selection_is_stable_and_validated():
    image = np.array([[4.0, 1.0, np.nan], [4.0, 2.0, -1.0]])
    np.testing.assert_array_equal(
        select_cell_free_pixels(image, "brightest", 2), [[0, 0], [1, 0]]
    )
    np.testing.assert_array_equal(
        select_cell_free_pixels(image, "darkest", 2), [[0, 1], [1, 1]]
    )
    with pytest.raises(ValueError, match="exceeds"):
        select_cell_free_pixels(image, "brightest", 5)
    with pytest.raises(ValueError, match="at least 1"):
        select_cell_free_pixels(image, "darkest", 0)


def test_live_diagnostics_follow_actual_filter_and_background(acquisition):
    state = configured(acquisition)
    state.crop({"roi": {"x_min": 0, "x_max": 20, "y_min": 0, "y_max": 16}})
    payload = {
        "pattern": "pattern0",
        "wavenumber": 1658,
        "fourier": {
            "mode": "lowpass",
            "cutoff_x": 0.1,
            "cutoff_y": 0.2,
            "pad_pixels": 4,
        },
        "rolling": {"radius": 3},
    }
    preview = state.preview(payload)
    diagnostics = preview["diagnostics"]
    assert len(diagnostics) == 7
    assert diagnostics[0]["vmax"] == diagnostics[2]["vmax"]
    assert (diagnostics[1]["vmin"], diagnostics[1]["vmax"]) == (0.0, 1.0)
    output, flat = state.process_image(state.crops[("pattern0", 1658)], payload)
    arrays = [
        np.log1p(abs(output.spectrum_before)),
        output.mask,
        np.log1p(abs(output.spectrum_after)),
        output.removed,
        flat.background,
        flat.gain,
        output.filtered - flat.corrected,
    ]
    for card, array in zip(diagnostics, arrays):
        png, _, _ = render_data_png(array, limits=(card["vmin"], card["vmax"]))
        assert base64.b64decode(card["png"]) == png
    payload["fourier"]["cutoff_x"] = 0.05
    updated = state.preview(payload)["diagnostics"]
    assert updated[1]["png"] != diagnostics[1]["png"]
    assert updated[2]["png"] != diagnostics[2]["png"]
    payload["rolling"]["radius"] = 7
    changed = state.preview(payload)["diagnostics"]
    assert changed[4]["png"] != updated[4]["png"]
    payload["rolling"]["enabled"] = False
    payload["fourier"]["enabled"] = False
    bypass = state.preview(payload)["diagnostics"]
    assert bypass[0]["png"] == bypass[2]["png"]
    assert not bypass[4]["available"] and not bypass[5]["available"]
    assert state.stage == "cropped" and not state.ff


@pytest.mark.parametrize(
    "fourier_enabled,rolling_enabled",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_preview_matches_batch_and_does_not_mutate(
    acquisition, fourier_enabled, rolling_enabled
):
    state = configured(acquisition)
    state.crop({"roi": {"x_min": 0, "x_max": 20, "y_min": 0, "y_max": 16}})
    settings = {
        "fourier": {
            "enabled": fourier_enabled,
            "mode": "lowpass",
            "cutoff_x": 0.1,
            "cutoff_y": 0.2,
        },
        "rolling": {"enabled": rolling_enabled, "radius": 3},
    }
    version = state.version
    result = state.preview({"pattern": "pattern0", "wavenumber": 1658, **settings})
    assert state.version == version and state.stage == "cropped"
    assert not state.ff and not state.flat and not state.parameters
    state.process(settings)
    for stage, card in zip(("reflectance", "fourier", "rolling"), result["images"]):
        committed = state.image(
            {"pattern": "pattern0", "wavenumber": 1658, "kind": stage}
        )
        assert card["png"] == committed["png"]
        assert base64.b64decode(card["png"]).startswith(b"\x89PNG")
    if not fourier_enabled:
        np.testing.assert_array_equal(
            state.ff[("pattern0", 1658)].filtered, state.crops[("pattern0", 1658)]
        )
    if not rolling_enabled:
        for key in state.flat:
            np.testing.assert_array_equal(
                state.flat[key].corrected, state.ff[key].filtered
            )
            assert np.all(state.flat[key].gain == 1)
    state.calculate({"roi": {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3}})
    state.correct_baseline({})
    assert state.stage == "complete"


def test_top_ten_candidates_ranked_and_exclude_dc(acquisition):
    state = configured(acquisition)
    state.crop({"roi": {"x_min": 0, "x_max": 20, "y_min": 0, "y_max": 16}})
    y, x = np.mgrid[:128, :128]
    image = 100 + sum(
        (12 - i) * np.cos(2 * np.pi * (i * 5 * x + i * 2 * y) / 128) for i in range(1, 12)
    )
    state.crops[("pattern0", 1658)] = image
    result = state.image(
        {
            "pattern": "pattern0",
            "wavenumber": 1658,
            "kind": "spectrum",
            "window": "false",
        }
    )
    peaks = result["peaks"]
    assert len(peaks) == 10
    assert [p["rank"] for p in peaks] == list(range(1, 11))
    assert all(p["fy"] > 0 or (p["fy"] == 0 and p["fx"] > 0) for p in peaks)
    assert all(np.hypot(p["fy"], p["fx"]) > 0.025 for p in peaks)
    assert peaks[0]["fx"] == pytest.approx(5 / 128)
    assert peaks[0]["fy"] == pytest.approx(2 / 128)
    assert all(a["amplitude"] >= b["amplitude"] for a, b in itertools.pairwise(peaks))


def test_explicit_conjugate_pairs_do_not_double_filter():
    image = np.random.default_rng(2).normal(size=(32, 40))
    payload = {
        "fourier": {"mode": "notch", "centers": [[0.125, 0.2]]},
        "rolling": {"enabled": False},
    }
    one, _ = ProcessingState.process_image(image, payload)
    payload["fourier"]["centers"].append([-0.125, -0.2])
    pair, _ = ProcessingState.process_image(image, payload)
    np.testing.assert_allclose(one.filtered, pair.filtered)


@pytest.fixture
def acquisition(tmp_path):
    y, x = np.mgrid[:16, :20]
    for frame in range(2):
        folder = tmp_path / "stacks" / f"pattern{frame}"
        folder.mkdir(parents=True)
        for wn in (1080, 1601, 1658, 1702):
            a = 100 + 0.1 * x + 0.2 * y + np.sin(x * 2) + frame
            a = a * (1 + (wn - 1601) / 2000) - (wn == 1658) * 2 * np.exp(
                -((x - 10) ** 2 + (y - 8) ** 2) / 10
            )
            np.savetxt(folder / f"lineScan_{wn}_0invcm.csv", a, delimiter=",")
    return tmp_path


def configured(path):
    state = ProcessingState()
    state.discover({"path": str(path)})
    state.configure(
        {
            "mapping": {"1658": [1601, 1702]},
            "patterns": ["pattern0", "pattern1"],
            "n_pixels": 5,
        }
    )
    state.normalize({"has_gold": True, "n_pixels": 5})
    return state


def complete(path):
    state = configured(path)
    state.crop({"roi": {"x_min": 2, "x_max": 18, "y_min": 1, "y_max": 15}})
    state.process(
        {
            "fourier": {"mode": "lowpass", "cutoff_x": 0.2, "cutoff_y": 0.1},
            "rolling": {"radius": 3, "kernel_height": 0.05},
        }
    )
    state.calculate({"roi": {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3}})
    state.correct_baseline({})
    return state


def test_configuration_requires_explicit_normalization_choice(acquisition):
    state = ProcessingState()
    state.discover({"path": str(acquisition)})
    state.configure({"mapping": {"1658": [1601, 1702]}, "patterns": ["pattern0"]})
    assert state.stage == "configured" and state.has_gold is None and not state.ref
    with pytest.raises(ValueError):
        state.crop({"roi": {"x_min": 0, "x_max": 5, "y_min": 0, "y_max": 5}})
    with pytest.raises(ValueError, match="gold patch"):
        state.normalize({})


@pytest.mark.parametrize("enabled", [False, True])
def test_no_gold_processes_raw_and_exports_no_reflectance(acquisition, enabled):
    state = configured(acquisition)
    state.normalize({"has_gold": False, "n_pixels": -100})
    assert not state.ref and not state.gold_pixels
    assert state.status()["processing_basis"] == "raw_intensity"
    roi = {"x_min": 2, "x_max": 18, "y_min": 1, "y_max": 15}
    with pytest.raises(ValueError, match="requires a gold"):
        state.crop({"roi": roi, "drift": {"enabled": True}})
    state.crop({"roi": roi})
    parameters = {"fourier": {"enabled": enabled, "mode": "lowpass", "cutoff_x": .2, "cutoff_y": .1},
                  "rolling": {"enabled": enabled, "radius": 3, "kernel_height": .05}}
    state.process(parameters)
    state.calculate({"roi": {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3}})
    for key, raw in state.raw.items():
        cropped = raw[1:15, 2:18]
        np.testing.assert_array_equal(state.crops[key], cropped)
        _, expected = state.process_image(cropped, parameters)
        np.testing.assert_allclose(state.flat[key].corrected, expected.corrected)
        np.testing.assert_allclose(state.absorbance[key], -np.log10(expected.corrected / expected.corrected[:3, :3].mean()))
        assert state.stage_arrays(key)["reflectance"] is None
    state.correct_baseline({})
    with zipfile.ZipFile(io.BytesIO(state.export())) as archive:
        assert not any(name.endswith('/reflectance.csv') or name.endswith('/gold_reference_pixels.csv') for name in archive.namelist())
        metadata = json.loads(archive.read('metadata.json'))
        assert metadata['has_gold_patch_reference'] is False
        assert metadata['normalization_formula'] is None
    state.normalize({"has_gold": True, "n_pixels": 5})
    assert state.stage == "referenced" and not state.crops and not state.absorbance


def test_gold_preview_marks_exact_normalization_pixels(acquisition):
    state = configured(acquisition)
    for key, raw in state.raw.items():
        pixels = state.gold_pixels[key]
        assert pixels.shape == (5, 2)
        mean = raw[pixels[:, 0], pixels[:, 1]].mean()
        np.testing.assert_allclose(mean, np.sort(raw.ravel())[-5:].mean())
        np.testing.assert_allclose(state.ref[key], raw / mean)
        preview = state.image({"pattern": key[0], "wavenumber": key[1], "kind": "full_raw"})
        assert preview['gold_pixels'] == pixels.tolist()
        assert preview['i_goldref'] == mean
    state.normalize({"has_gold": False})
    assert not state.image({"pattern": key[0], "wavenumber": key[1], "kind": "full_reflectance"})['available']
    assert 'gold_pixels' not in state.image({"pattern": key[0], "wavenumber": key[1], "kind": "full_raw"})


def test_cnr_display_clipping_and_export_provenance(acquisition):
    state = complete(acquisition)
    rois = {"background": {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3},
            "target": {"x_min": 5, "x_max": 8, "y_min": 5, "y_max": 8}}
    key = ('pattern0', 1658)
    state.raw[key][1:4, 2:5] = [100, 104, 1000]
    originals = {k: a.copy() for k, a in state.raw.items()}
    default = state.cnr(rois)['records']
    for row in default:
        if np.isfinite(row['cnr']):
            assert row['cnr'] == row['cnr_unadjusted']
        assert not row['contrast_adjusted']
    rows = state.cnr({**rois, 'low': 10, 'high': 80})['records']
    raw = next(r for r in rows if (r['pattern'], r['wavenumber'], r['stage']) == (*key, 'raw'))
    assert raw['cnr'] != pytest.approx(raw['cnr_unadjusted'])
    for row in rows:
        if row['status'] == 'unavailable':
            continue
        image = state.image({'pattern': row['pattern'], 'wavenumber': row['wavenumber'],
                             'kind': row['stage'], 'low': 10, 'high': 80})
        assert row['contrast_vmin'] == image['vmin']
        assert row['contrast_vmax'] == image['vmax']
    clipped = np.clip(state.stage_arrays(key)['raw'], raw['contrast_vmin'], raw['contrast_vmax'])
    expected = abs(clipped[5:8, 5:8].mean() - clipped[:3, :3].mean()) / clipped[:3, :3].std(ddof=1)
    assert raw['cnr'] == pytest.approx(expected)
    for k, a in originals.items():
        np.testing.assert_array_equal(state.raw[k], a)
    with zipfile.ZipFile(io.BytesIO(state.export())) as archive:
        metadata = json.loads(archive.read('metadata.json'))
        assert all(r['contrast_low_percentile'] == 10 for r in metadata['cnr_contrast']['records'])
        header = archive.read('cnr_summary.csv').decode().splitlines()[0]
        for column in ['contrast_vmin', 'contrast_vmax', 'contrast_low_percentile', 'contrast_high_percentile', 'cnr_unadjusted']:
            assert column in header
    previous = state.cnr_records
    for low, high in [(-1, 100), (80, 20), (0, 101), (float('nan'), 100)]:
        with pytest.raises(ValueError, match='percentiles'):
            state.cnr({**rois, 'low': low, 'high': high})
        assert state.cnr_records is previous


def test_zero_colorbar_is_display_only_across_renderers(acquisition):
    state = complete(acquisition)
    key = ('pattern0', 1658)
    params = {'pattern': key[0], 'wavenumber': key[1], 'low': 10, 'high': 90}
    rois = {'background': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3},
            'target': {'x_min': 5, 'x_max': 8, 'y_min': 5, 'y_max': 8}, 'low': 10, 'high': 90}
    original_cnr = clean_json(state.cnr(rois))
    arrays = {k: a.copy() for k, a in state.stage_arrays(key).items() if a is not None}
    before = state.image({**params, 'kind': 'raw'})
    after = state.image({**params, 'kind': 'raw', 'colorbar_zero': 'true'})
    assert after['vmin'] == 0 and after['vmax'] == before['vmax']
    assert after['png'] != before['png']
    for kind in ['full_raw', 'full_reflectance', 'raw', 'reflectance', 'fourier', 'rolling', 'absorbance', 'baseline', 'spectrum', 'mask', 'background', 'gain', 'linear_baseline']:
        assert state.image({**params, 'kind': kind, 'colorbar_zero': True})['vmin'] == 0
    assert state.raw_inspection({**params, 'mode': 'image', 'colorbar_zero': True})['vmin'] == 0
    preview = state.preview({**params, **state.parameters, 'colorbar_zero': True})
    for card in preview['images'] + preview['diagnostics']:
        if 'vmin' in card:
            assert card['vmin'] == 0
    normal = state.preview({**params, **state.parameters})
    selected_title = 'After Fourier'
    independent = state.preview({**params, **state.parameters, 'colorbar_zero_titles': [selected_title]})
    for before_card, after_card in zip(normal['images'] + normal['diagnostics'], independent['images'] + independent['diagnostics']):
        if before_card['title'] == selected_title:
            assert after_card['vmin'] == 0
            assert after_card['png'] != before_card['png']
        else:
            assert after_card == before_card
    video = state.timelapse({'wavenumber': 1658, 'colorbar_zero': True})
    assert video['vmin'] == 0 and video['colorbar_zero'] is True
    assert clean_json(state.cnr({**rois, 'colorbar_zero': True})) == original_cnr
    for kind, array in arrays.items():
        np.testing.assert_array_equal(state.stage_arrays(key)[kind], array)
    restored = state.image({**params, 'kind': 'raw', 'colorbar_zero': 'false'})
    assert restored['png'] == before['png']


def test_discovery_paths(acquisition):
    for path, count in [
        (acquisition, 8),
        (acquisition / "stacks", 8),
        (acquisition / "stacks/pattern0", 4),
        (acquisition / "stacks/pattern0/lineScan_1658_0invcm.csv", 4),
    ]:
        _, data = discover_files(path)
        assert len(data) == count
        assert set(data.wavenumber) == {1080, 1601, 1658, 1702}


@pytest.mark.parametrize(
    "mapping",
    [
        {"1658": [1601]},
        {"1658": [1601, 1658]},
        {"1658": [1080, 1601]},
        {"1658": [1601, 1800]},
        {"1658": [1601, 1601, 1702]},
    ],
)
def test_invalid_mapping(acquisition, mapping):
    state = ProcessingState()
    state.discover({"path": str(acquisition)})
    with pytest.raises(ValueError):
        state.configure({"mapping": mapping, "patterns": ["pattern0"]})
    assert state.stage == "discovered"


def test_missing_required_band(acquisition):
    (acquisition / "stacks/pattern1/lineScan_1702_0invcm.csv").unlink()
    with pytest.raises(ValueError, match="missing required"):
        configured(acquisition)


def test_complete_pipeline_and_export(acquisition):
    state = complete(acquisition)
    assert state.bands == [1601, 1658, 1702]
    assert len(state.ff) == len(state.flat) == len(state.absorbance) == 6
    key = ("pattern0", 1658)
    a = state.absorbance
    expected = a[key] - (44 * a[("pattern0", 1601)] + 57 * a[("pattern0", 1702)]) / 101
    np.testing.assert_allclose(state.baselines[key].corrected, expected, atol=1e-14)
    cnr = state.cnr(
        {
            "background": {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3},
            "target": {"x_min": 6, "x_max": 10, "y_min": 6, "y_max": 10},
        }
    )
    rows = [r for r in cnr["records"] if (r["pattern"], r["wavenumber"]) == key]
    assert len(cnr["records"]) == 36
    assert rows[0]["cnr"] == pytest.approx(rows[1]["cnr"])
    json.dumps(clean_json(cnr), allow_nan=False)
    for kind in (
        "raw",
        "reflectance",
        "fourier",
        "rolling",
        "absorbance",
        "baseline",
        "linear_baseline",
        "mask",
        "spectrum",
    ):
        image = state.image({"pattern": key[0], "wavenumber": key[1], "kind": kind})
        assert image["available"] and image["width"] == 16
    assert not state.image({"pattern": key[0], "wavenumber": 1601, "kind": "baseline"})[
        "available"
    ]
    time = state.timelapse({"wavenumber": 1658, "start": 1, "end": 1})
    assert [f["pattern"] for f in time["frames"]] == ["pattern1"]
    with zipfile.ZipFile(io.BytesIO(state.export())) as z:
        metadata = json.loads(z.read("metadata.json"))
        assert metadata["processed_wavenumbers"] == [1601, 1658, 1702]
        assert "cnr_summary.csv" in z.namelist()
        saved = np.loadtxt(
            io.StringIO(z.read("pattern0/1658cm-1/baseline.csv").decode()),
            delimiter=",",
        )
        np.testing.assert_allclose(saved, expected, atol=1e-14)
        mask = np.loadtxt(
            io.StringIO(
                z.read("pattern0/1658cm-1/cell_free_pixel_mask.csv").decode()
            ),
            delimiter=",",
        )
        assert mask.sum() == 9
        coordinates = z.read("pattern0/1658cm-1/cell_free_pixels.csv").decode()
        assert coordinates.startswith("y,x\n")
    state.crop({"roi": {"x_min": 1, "x_max": 10, "y_min": 1, "y_max": 10}})
    assert state.stage == "cropped"
    assert not state.flat and not state.baselines and not state.cnr_records
    with pytest.raises(ValueError, match="complete"):
        state.export()


@pytest.mark.parametrize("method", ["brightest", "darkest"])
def test_per_image_extreme_pixels_drive_r0_preview_and_export(acquisition, method):
    state = configured(acquisition)
    state.crop({"roi": {"x_min": 2, "x_max": 18, "y_min": 1, "y_max": 15}})
    state.process(
        {
            "fourier": {"enabled": False, "mode": "none"},
            "rolling": {"enabled": False},
        }
    )
    count = 7
    reference_bands = {"pattern0": 1601, "pattern1": 1702}
    for i, flat in enumerate(state.flat.values()):
        flat.corrected[:] = np.roll(np.arange(flat.corrected.size).reshape(flat.corrected.shape) + 1.0, i * 13)
    result = state.calculate({"method": method, "count": count, "reference_bands": reference_bands})
    state.correct_baseline({})
    assert result["r0_selection"] == {"method": method, "count": count, "reference_bands": reference_bands}
    assert state.r0_roi is None
    assert len(state.r0_pixels) == 6
    for key, pixels in state.r0_pixels.items():
        expected = select_cell_free_pixels(state.flat[(key[0], reference_bands[key[0]])].corrected, method, count)
        np.testing.assert_array_equal(pixels, expected)
        row = next(
            r
            for r in state.r0_records
            if (r["pattern"], r["wavenumber"]) == key
        )
        assert row["method"] == method and row["pixel_count"] == count
        assert row["r0"] == pytest.approx(
            np.mean(state.flat[key].corrected[pixels[:, 0], pixels[:, 1]])
        )
    preview = state.image(
        {
            "pattern": "pattern0",
            "wavenumber": 1658,
            "kind": "rolling",
            "r0_method": method,
            "r0_count": count,
            "r0_reference_band": 1601,
        }
    )
    assert len(preview["cell_free_pixels"]) == count
    np.testing.assert_array_equal(
        preview["cell_free_pixels"], state.r0_pixels[("pattern0", 1658)]
    )
    with zipfile.ZipFile(io.BytesIO(state.export())) as z:
        metadata = json.loads(z.read("metadata.json"))
        assert metadata["cell_free_roi_local"] is None
        assert metadata["cell_free_selection"] == {
            "method": method,
            "count": count,
            "reference_bands": reference_bands,
        }
        mask = np.loadtxt(
            io.StringIO(
                z.read("pattern1/1702cm-1/cell_free_pixel_mask.csv").decode()
            ),
            delimiter=",",
        )
        assert mask.sum() == count


def test_unknown_reference_band_rejected(acquisition):
    state = complete(acquisition)
    with pytest.raises(ValueError, match="reference wavenumber"):
        state.calculate({"method": "brightest", "count": 3,
                         "reference_bands": {"pattern0": 9999}})


def test_timelapse_contrast_and_identity(acquisition):
    state = complete(acquisition)
    default = state.timelapse({"wavenumber": 1658})
    assert (default["low"], default["high"], default["wavenumber"]) == (0, 100, 1658)
    arrays = [state.baselines[(pattern, 1658)].corrected for pattern in state.patterns]
    assert (default["vmin"], default["vmax"]) == state.limits(arrays, 0, 100)
    adjusted = state.timelapse({"wavenumber": 1658, "low": 10, "high": 90})
    assert (adjusted["vmin"], adjusted["vmax"]) == state.limits(arrays, 10, 90)
    assert adjusted["frames"][0]["png"] != default["frames"][0]["png"]
    with pytest.raises(ValueError, match="Contrast"):
        state.timelapse({"wavenumber": 1658, "low": 90, "high": 10})


@pytest.mark.parametrize("quote", ['"', "'"])
def test_discovery_accepts_quoted_paths(acquisition, quote):
    source, data = discover_files(f"  {quote}{acquisition}{quote}  ")
    assert source == acquisition / "stacks"
    assert len(data) == 8


@pytest.mark.parametrize("path", ["", "  ", '\"\"', "''"])
def test_discovery_rejects_empty_paths(path):
    with pytest.raises(ValueError, match="data path"):
        discover_files(path)


@pytest.mark.parametrize("kind", ["raw", "reflectance", "fourier", "rolling", "absorbance", "baseline"])
def test_timelapse_uses_selected_stage(acquisition, kind):
    state = complete(acquisition)
    # Non-baseline stages must also support reference bands.
    wn = 1658 if kind == "baseline" else 1601
    result = state.timelapse({"wavenumber": wn, "kind": kind, "low": 10, "high": 90})
    arrays = [state.stage_arrays((p, wn))[kind] for p in state.patterns]
    limits = state.limits(arrays, 10, 90)
    assert (result["vmin"], result["vmax"]) == limits
    assert result["kind"] == kind
    assert len(result["frames"]) == len(arrays)
    from ui.app import render_data_png
    import base64
    for frame, array in zip(result["frames"], arrays):
        expected, _, _ = render_data_png(array, limits=limits)
        assert base64.b64decode(frame["png"]) == expected
    assert "absorbance" not in result["extrema_label"]


@pytest.mark.parametrize("references", [[1601, 1702], [1080, 1601, 1702]])
def test_baseline_pixel_reports_committed_fit(acquisition, references):
    from qcl_analysis.baseline import correct_absorbance_baselines
    state = complete(acquisition)
    # An unequal-spaced fit with a known slope and a center-only peak.
    state.mapping = {1658: references}
    for wn in [1658, *references]:
        state.absorbance[('pattern0', wn)] = np.full((14, 16), .2 + .001 * (wn - 1658) + (.07 if wn == 1658 else 0))
    results = correct_absorbance_baselines(
        {wn: state.absorbance[('pattern0', wn)] for wn in [1658, *references]}, state.mapping
    )
    state.baselines[('pattern0', 1658)] = results[1658]
    d = state.baseline_pixel({'pattern': 'pattern0', 'wavenumber': 1658, 'x': 4, 'y': 3})
    assert d['valid']
    assert d['before'] == pytest.approx(.27)
    assert d['baseline'] == pytest.approx(.2)
    assert d['after'] == pytest.approx(.07)
    assert d['slope'] == pytest.approx(.001)
    assert [r['wavenumber'] for r in d['references']] == references
    for r in d['references']:
        assert r['fitted'] == pytest.approx(r['absorbance'])


@pytest.mark.parametrize('changes', [{'x': -1}, {'x': 16}, {'y': 14}, {'y': .5}, {'wavenumber': 1601}, {'pattern': 'missing'}])
def test_baseline_pixel_validates_selection(acquisition, changes):
    state = complete(acquisition)
    with pytest.raises(ValueError):
        state.baseline_pixel({'pattern': 'pattern0', 'wavenumber': 1658, 'x': 0, 'y': 0, **changes})


def test_baseline_pixel_invalid_values_are_json_null(acquisition):
    from qcl_analysis.baseline import correct_absorbance_baselines
    state = complete(acquisition)
    state.absorbance[('pattern0', 1601)][2, 3] = np.nan
    state.baselines[('pattern0', 1658)] = correct_absorbance_baselines(
        {wn: state.absorbance[('pattern0', wn)] for wn in state.bands}, state.mapping
    )[1658]
    d = clean_json(state.baseline_pixel({'pattern': 'pattern0', 'wavenumber': 1658, 'x': 3, 'y': 2}))
    assert not d['valid']
    assert d['baseline'] is None and d['after'] is None
    assert d['references'][0]['absorbance'] is None


def test_absorbance_and_baseline_are_separate_stages(acquisition):
    state = complete(acquisition)
    state.calculate({'roi': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3}})
    assert state.stage == 'absorbed'
    assert state.absorbance and not state.baselines
    assert state.image({'pattern': 'pattern0', 'wavenumber': 1658, 'kind': 'absorbance'})['available']
    assert not state.image({'pattern': 'pattern0', 'wavenumber': 1658, 'kind': 'baseline'})['available']
    with pytest.raises(ValueError, match='complete'):
        state.baseline_pixel({'pattern': 'pattern0', 'wavenumber': 1658, 'x': 0, 'y': 0})
    original = state.absorbance[('pattern0', 1658)].copy()
    state.correct_baseline({})
    assert state.stage == 'complete' and state.baselines
    np.testing.assert_array_equal(state.absorbance[('pattern0', 1658)], original)
    result = state.cnr({'background': {'x_min': 0, 'x_max': 3, 'y_min': 0, 'y_max': 3},
                        'target': {'x_min': 6, 'x_max': 10, 'y_min': 6, 'y_max': 10}})
    row = result['records'][0]
    assert row['cnr'] == pytest.approx(abs(row['target_mean'] - row['background_mean']) / row['background_std'])
    assert 'snr' not in row
    with zipfile.ZipFile(io.BytesIO(state.export())) as archive:
        assert 'snr' not in archive.read('cnr_summary.csv').decode().splitlines()[0]
        assert 'snr_formula' not in json.loads(archive.read('metadata.json'))
    state.calculate({'roi': {'x_min': 0, 'x_max': 2, 'y_min': 0, 'y_max': 2}})
    assert not state.baselines and not state.cnr_records


def test_anisotropic_notch_preview_removed_signal_matches_batch(acquisition):
    state = configured(acquisition)
    state.crop({"roi": {"x_min": 0, "x_max": 20, "y_min": 0, "y_max": 16}})
    payload = {"pattern": "pattern0", "wavenumber": 1658,
               "fourier": {"mode": "notch", "centers": [[0, .3]], "sigma_x": .04, "sigma_y": .015},
               "rolling": {"enabled": False}}
    preview = state.preview(payload)
    output, _ = state.process_image(state.crops[("pattern0", 1658)], payload)
    card = preview["diagnostics"][3]
    expected, _, _ = render_data_png(output.removed, limits=(card["vmin"], card["vmax"]))
    assert base64.b64decode(card["png"]) == expected
    assert card["vmin"] == -card["vmax"]
    assert state.stage == "cropped" and not state.ff
    state.process(payload)
    np.testing.assert_allclose(state.ff[("pattern0", 1658)].removed, output.removed)
    assert state.parameters['fourier']['sigma_x'] == .04
    payload['fourier']['centers'] = []
    cleared = state.preview(payload)['diagnostics'][3]
    assert cleared['png'] != card['png']


def test_import_raw_spectrum_uses_all_discovered_bands(acquisition):
    state = ProcessingState()
    state.discover({'path': str(acquisition)})
    version = state.version
    payload = {'pattern': 'pattern1', 'wavenumber': 1658, 'x': 7, 'y': 4}
    result = state.raw_inspection(payload)
    assert [p['wavenumber'] for p in result['points']] == [1080, 1601, 1658, 1702]
    for point in result['points']:
        array = np.loadtxt(acquisition / 'stacks' / 'pattern1' / f"lineScan_{point['wavenumber']}_0invcm.csv", delimiter=',')
        assert point['raw_signal'] == array[4, 7]
    preview = state.raw_inspection({**payload, 'mode': 'image'})
    assert (preview['width'], preview['height']) == (20, 16)
    assert base64.b64decode(preview['png']).startswith(b'\x89PNG')
    assert state.version == version and state.stage == 'discovered'
    assert not state.raw and not state.mapping


def test_raw_spectrum_reports_missing_bands(acquisition):
    (acquisition / 'stacks/pattern1/lineScan_1080_0invcm.csv').unlink()
    state = ProcessingState()
    state.discover({'path': str(acquisition)})
    result = state.raw_inspection({'pattern': 'pattern1', 'wavenumber': 1658, 'x': 0, 'y': 0})
    assert result['missing_wavenumbers'] == [1080]
    assert len(result['points']) == 3


@pytest.mark.parametrize('override', [{'x': -1}, {'y': 16}, {'x': .5}, {'pattern': 'missing'}, {'wavenumber': 1234}])
def test_raw_inspection_rejects_invalid_selection(acquisition, override):
    state = ProcessingState()
    state.discover({'path': str(acquisition)})
    with pytest.raises(ValueError):
        state.raw_inspection({'pattern': 'pattern0', 'wavenumber': 1658, 'x': 0, 'y': 0, **override})


def test_raw_inspection_rejects_misaligned_shapes(acquisition):
    np.savetxt(acquisition / 'stacks/pattern0/lineScan_1080_0invcm.csv', np.ones((8, 10)), delimiter=',')
    state = ProcessingState()
    state.discover({'path': str(acquisition)})
    with pytest.raises(ValueError, match='shape'):
        state.raw_inspection({'pattern': 'pattern0', 'wavenumber': 1658, 'x': 0, 'y': 0})


def test_multiple_folder_sessions_are_isolated(acquisition):
    from ui.app_processing import ComparisonSession
    session = ComparisonSession()
    first = session.add({'path': str(acquisition), 'name': 'A'})
    second = session.add({'path': str(acquisition), 'name': 'B'})
    a, b = session.get(first['id']), session.get(second['id'])
    assert a is not b
    a.configure({'mapping': {'1658': [1601, 1702]}, 'patterns': ['pattern0'], 'n_pixels': 5})
    assert b.stage == 'discovered' and not b.raw
    with pytest.raises(ValueError, match='Unknown dataset'):
        session.get('not-a-dataset')
    session.datasets[first['id']] = complete(acquisition)
    session.datasets[second['id']] = complete(acquisition)
    ids = [first['id'], second['id']]
    summary = session.info(ids)
    assert [d['name'] for d in summary] == ['A', 'B']
    assert all(d['stage'] == 'complete' for d in summary)
    with zipfile.ZipFile(io.BytesIO(session.export(ids))) as archive:
        assert set(archive.namelist()) == {'dataset_1/results.zip', 'dataset_2/results.zip', 'datasets.json'}
        assert json.loads(archive.read('datasets.json'))[1]['name'] == 'B'


def test_raw_roi_spectrum_means_and_invalid_bands(tmp_path):
    folder = tmp_path / 'pattern0'
    folder.mkdir()
    for wn, signal in [(1700, [2., 6.]), (1600, [1., 3.]), (1800, [0., 0.])]:
        np.savetxt(folder / f'lineScan_{wn}_0invcm.csv', [signal, [8., 8.]], delimiter=',')
    state = ProcessingState()
    state.discover({'path': str(folder)})
    payload = {'pattern': 'pattern0', 'wavenumber': 1700,
               'analyte_roi': {'x_min': 0, 'x_max': 2, 'y_min': 0, 'y_max': 1},
               'background_roi': {'x_min': 0, 'x_max': 2, 'y_min': 1, 'y_max': 2}}
    version = state.version
    result = state.raw_roi_spectrum(payload)
    assert result['analyte_pixels'] == result['background_pixels'] == 2
    assert [p['wavenumber'] for p in result['points']] == [1600, 1700, 1800]
    assert [p['I'] for p in result['points']] == [2., 4., 0.]
    assert result['points'][0]['ratio'] == .25
    assert result['points'][1]['absorbance'] == pytest.approx(-np.log10(.5))
    assert result['points'][2]['absorbance'] is None
    assert result['points'][2]['status'] != 'valid'
    assert state.version == version and state.stage == 'discovered'
    assert state.r0_roi is None and not state.raw
    json.dumps(clean_json(result), allow_nan=False)
    with pytest.raises(ValueError, match='exceeds'):
        state.raw_roi_spectrum({**payload, 'analyte_roi': {**payload['analyte_roi'], 'x_max': 3}})
    np.savetxt(folder / 'lineScan_1800_0invcm.csv', np.ones((3, 3)), delimiter=',')
    with pytest.raises(ValueError, match='shape'):
        state.raw_roi_spectrum(payload)


def test_raw_roi_spectrum_all_bands_and_missing(acquisition):
    (acquisition / 'stacks/pattern1/lineScan_1080_0invcm.csv').unlink()
    state = ProcessingState()
    state.discover({'path': str(acquisition)})
    result = state.raw_roi_spectrum({'pattern': 'pattern1', 'wavenumber': 1658,
        'analyte_roi': {'x_min': 1, 'x_max': 4, 'y_min': 2, 'y_max': 5},
        'background_roi': {'x_min': 5, 'x_max': 9, 'y_min': 1, 'y_max': 3}})
    assert result['missing_wavenumbers'] == [1080]
    for p in result['points']:
        raw = np.loadtxt(acquisition / 'stacks/pattern1' / f"lineScan_{p['wavenumber']}_0invcm.csv", delimiter=',')
        assert p['I'] == pytest.approx(raw[2:5, 1:4].mean())
        assert p['I_bg'] == pytest.approx(raw[1:3, 5:9].mean())


def test_roi_sg_preserves_polynomial_and_reduces_noise():
    state = ProcessingState()
    x = np.arange(1600., 1641.)
    baseline = .1 + .002 * (x - 1620) + .0001 * (x - 1620) ** 2
    payload = {'wavenumbers': x.tolist(), 'absorbance': baseline.tolist(), 'window': 11, 'order': 2}
    result = state.smooth_roi_spectrum(payload)
    np.testing.assert_allclose(result['absorbance_sg'], baseline, atol=1e-12)
    noisy = baseline + .01 * (-1.) ** np.arange(x.size)
    result = state.smooth_roi_spectrum({**payload, 'absorbance': noisy.tolist()})
    assert np.std(np.array(result['absorbance_sg']) - baseline) < np.std(noisy - baseline)
    assert payload['absorbance'] == baseline.tolist()


@pytest.mark.parametrize('override', [
    {'window': 4}, {'window': 9}, {'window': 3.5}, {'order': 5}, {'order': -1},
    {'absorbance': [1, 2, None, 4, 5]}, {'wavenumbers': [1, 2, 4, 5, 6]},
    {'wavenumbers': [1, 2, 2, 3, 4]}, {'absorbance': [1, 2]},
])
def test_roi_sg_rejects_invalid_parameters_or_sampling(override):
    payload = {'wavenumbers': [1, 2, 3, 4, 5], 'absorbance': [1, 2, 3, 4, 5], 'window': 5, 'order': 2}
    with pytest.raises(ValueError):
        ProcessingState().smooth_roi_spectrum({**payload, **override})


@pytest.mark.parametrize('fourier,sg', [(False, False), (True, False), (False, True), (True, True)])
def test_roi_spectral_filters_combine_independently(fourier, sg):
    state = ProcessingState()
    x = np.arange(129.)
    clean = .2 + .1 * np.cos(2 * np.pi * x / 128)
    signal = clean + .02 * np.cos(2 * np.pi * 40 * x / 128)
    payload = {'wavenumbers': (x + 1600).tolist(), 'absorbance': signal.tolist(),
               'fourier_enabled': fourier, 'sg_enabled': sg, 'cutoff': .1,
               'window': 11, 'order': 2}
    result = state.filter_roi_spectrum(payload)
    output = np.array(result['absorbance_filtered'])
    if not fourier and not sg:
        np.testing.assert_array_equal(output, signal)
    else:
        assert np.std(output-clean) < np.std(signal-clean)
    if fourier:
        np.testing.assert_allclose(np.array(result['absorbance_fourier']) + result['fourier_removed'], signal)
        frequency = np.array(result['frequency'])
        assert np.all(np.array(result['fft_after'])[frequency > .1] == 0)
        np.testing.assert_allclose(np.array(result['fft_after']) + result['fft_removed'], result['fft_before'])
    if sg:
        expected = state.smooth_roi_spectrum({**payload, 'absorbance': result.get('absorbance_fourier', signal.tolist())})
        np.testing.assert_allclose(output, expected['absorbance_sg'])
    assert payload['absorbance'] == signal.tolist()


def test_roi_fourier_nyquist_preserves_signal():
    signal = np.random.default_rng(0).normal(size=31)
    result = ProcessingState().filter_roi_spectrum({'wavenumbers': list(range(31)),
        'absorbance': signal.tolist(), 'fourier_enabled': True, 'cutoff': .5})
    np.testing.assert_allclose(result['absorbance_filtered'], signal, atol=1e-14)


@pytest.mark.parametrize('override', [{'cutoff': 0}, {'cutoff': .6}, {'cutoff': float('nan')},
    {'absorbance': [1, None, 3]}, {'wavenumbers': [1, 2, 4]}])
def test_roi_fourier_rejects_invalid_input(override):
    with pytest.raises(ValueError):
        ProcessingState().filter_roi_spectrum({'wavenumbers': [1, 2, 3], 'absorbance': [1, 2, 3],
            'fourier_enabled': True, 'cutoff': .1, **override})


@pytest.mark.parametrize('mode', ['notch', 'combined'])
def test_roi_notch_removes_only_selected_frequency_ranges(mode):
    x = np.arange(129.)
    signal = .2 + .1*np.cos(2*np.pi*x/128) + .02*np.cos(2*np.pi*32*x/128)
    result = ProcessingState().filter_roi_spectrum({'wavenumbers': x.tolist(),
        'absorbance': signal.tolist(), 'fourier_enabled': True, 'fourier_mode': mode,
        'cutoff': .4, 'notch_centers': [.25, .35], 'notch_width': .04,
        'sg_enabled': True, 'window': 11, 'order': 2})
    frequency = np.array(result['frequency'])
    rejected = (np.abs(frequency-.25) <= .02) | (np.abs(frequency-.35) <= .02)
    if mode == 'combined':
        rejected |= frequency > .4
    np.testing.assert_array_equal(result['mask'], (~rejected).astype(int))
    assert result['fft_after'][0] == result['fft_before'][0]
    assert np.all(np.array(result['fft_after'])[rejected] == 0)
    np.testing.assert_allclose(np.array(result['absorbance_fourier'])+result['fourier_removed'], signal)
    assert np.std(np.array(result['absorbance_fourier'])-(.2+.1*np.cos(2*np.pi*x/128))) < .01
    assert result['sg_enabled']


@pytest.mark.parametrize('override', [{'notch_centers': []}, {'notch_centers': [0]},
    {'notch_centers': [.6]}, {'notch_centers': [float('nan')]}, {'notch_width': 0},
    {'notch_width': -1}, {'fourier_mode': 'unknown'}])
def test_roi_notch_rejects_invalid_settings(override):
    with pytest.raises(ValueError):
        ProcessingState().filter_roi_spectrum({'wavenumbers': list(range(9)),
            'absorbance': [1]*9, 'fourier_enabled': True, 'fourier_mode': 'notch',
            'notch_centers': [.25], 'notch_width': .02, **override})


@pytest.mark.parametrize('method', ['roi', 'brightest', 'darkest'])
def test_cnr_reuses_committed_analyte_free_selection(acquisition, method):
    state = complete(acquisition)
    roi = {'x_min': 0, 'x_max': 4, 'y_min': 0, 'y_max': 4}
    selection = {'method': method, 'roi': roi, 'search_roi': roi, 'count': 5,
                 'reference_bands': {'pattern0': 1601, 'pattern1': 1702}}
    state.calculate(selection)
    saved = {key: pixels.copy() for key, pixels in state.r0_pixels.items()}
    state.correct_baseline({})
    target = {'x_min': 8, 'x_max': 11, 'y_min': 8, 'y_max': 11}
    result = state.cnr({'background_source': 'analyte_free', 'target': target})
    for row in result['records']:
        key = (row['pattern'], row['wavenumber'])
        pixels = saved[key]
        array = state.stage_arrays(key)[row['stage']]
        if array is None:
            continue
        bg = array[pixels[:, 0], pixels[:, 1]]
        assert row['background_mean'] == pytest.approx(bg.mean())
        assert row['background_std'] == pytest.approx(bg.std(ddof=1))
        assert row['background_pixels'] == len(pixels)
        assert row['background_source'] == 'analyte_free'
    for key, pixels in saved.items():
        image = state.image({'pattern': key[0], 'wavenumber': key[1],
                             'kind': 'raw', 'cnr_background_source': 'analyte_free'})
        if method == 'roi':
            assert image['analyte_free_roi'] == roi
        else:
            assert image['cell_free_pixels'] == pixels.tolist()
    # Percentile recalculation (also used by multi-folder comparison) retains source.
    assert state.cnr({**result['rois'], 'low': 5, 'high': 95})['rois'] == result['rois']
    with zipfile.ZipFile(io.BytesIO(state.export())) as archive:
        metadata = json.loads(archive.read('metadata.json'))
        assert metadata['cnr_rois']['background_source'] == 'analyte_free'
    y, x = saved[('pattern0', 1658)][0]
    with pytest.raises(ValueError, match='overlap'):
        state.cnr({'background_source': 'analyte_free', 'target': {
            'x_min': int(x), 'x_max': int(x + 1), 'y_min': int(y), 'y_max': int(y + 1)}})
    manual = {'x_min': 4, 'x_max': 7, 'y_min': 4, 'y_max': 7}
    assert state.cnr({'background': manual, 'target': target})['rois']['background_source'] == 'manual'
    state.clear_absorbance()
    assert not state.r0_pixels


def test_line_profile_uses_stage_values_and_shared_positions(acquisition):
    state = complete(acquisition)
    key = ('pattern0', 1658)
    payload = {'pattern': key[0], 'wavenumber': key[1],
               'start': {'x': 1, 'y': 2}, 'end': {'x': 8, 'y': 2}}
    result = state.line_profile(payload)
    np.testing.assert_allclose(result['distance'], np.arange(8))
    for stage, array in state.stage_arrays(key).items():
        np.testing.assert_allclose(result['profiles'][stage], array[2, 1:9])
    assert result == state.line_profile({**payload, 'low': 30, 'high': 50, 'colorbar_zero': True})
    assert state.stage == 'complete' and not state.cnr_records
    reverse = state.line_profile({**payload, 'start': payload['end'], 'end': payload['start']})
    for stage in result['profiles']:
        np.testing.assert_allclose(reverse['profiles'][stage], result['profiles'][stage][::-1])
    reference = state.line_profile({**payload, 'wavenumber': 1601})
    assert reference['profiles']['baseline'] is None


def test_line_profile_diagonal_interpolation_and_invalid_samples(acquisition, monkeypatch):
    state = complete(acquisition)
    yy, xx = np.indices((14, 16))
    plane = 2.0 * xx + 3.0 * yy
    monkeypatch.setattr(state, 'stage_arrays', lambda key: {'raw': plane, 'reflectance': None})
    payload = {'pattern': 'pattern0', 'wavenumber': 1658,
               'start': {'x': 0, 'y': 0}, 'end': {'x': 15, 'y': 13}}
    result = state.line_profile(payload)
    np.testing.assert_allclose(result['profiles']['raw'], 2*np.array(result['x'])+3*np.array(result['y']))
    assert result['distance'][-1] == pytest.approx(np.hypot(15, 13))
    assert result['profiles']['reflectance'] is None
    plane[0, 1] = np.nan
    row = state.line_profile({**payload, 'end': {'x': 3, 'y': 0}})
    assert row['profiles']['raw'][0] == 0  # Zero-weight invalid neighbors do not contaminate pixels.
    assert clean_json(row)['profiles']['raw'][1] is None
    assert row['profiles']['raw'][2] == 4
    json.dumps(clean_json(row), allow_nan=False)


@pytest.mark.parametrize('end', [{'x': 16, 'y': 0}, {'x': -1, 'y': 0},
                                {'x': 0, 'y': 14}, {'x': float('nan'), 'y': 0},
                                {'x': 0, 'y': 0}])
def test_line_profile_rejects_invalid_endpoints(acquisition, end):
    state = complete(acquisition)
    with pytest.raises(ValueError, match='endpoints'):
        state.line_profile({'pattern': 'pattern0', 'wavenumber': 1658,
                            'start': {'x': 0, 'y': 0}, 'end': end})
