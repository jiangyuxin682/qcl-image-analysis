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
    assert len(diagnostics) == 6
    assert diagnostics[0]["vmax"] == diagnostics[2]["vmax"]
    assert (diagnostics[1]["vmin"], diagnostics[1]["vmax"]) == (0.0, 1.0)
    output, flat = state.process_image(state.crops[("pattern0", 1658)], payload)
    arrays = [
        np.log1p(abs(output.spectrum_before)),
        output.mask,
        np.log1p(abs(output.spectrum_after)),
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
    assert changed[3]["png"] != updated[3]["png"]
    payload["rolling"]["enabled"] = False
    payload["fourier"]["enabled"] = False
    bypass = state.preview(payload)["diagnostics"]
    assert bypass[0]["png"] == bypass[2]["png"]
    assert not bypass[3]["available"] and not bypass[4]["available"]
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
    return state


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
