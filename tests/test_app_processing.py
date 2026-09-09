"""Exercise filename discovery and the complete shared-band processing workflow.

Small synthetic spectral stacks verify mapping validation, numerical baseline
weights, synchronized CNR, export fidelity and downstream invalidation.
"""

import io
import json
import zipfile

import numpy as np
import pytest

from ui.app_processing import ProcessingState, clean_json, discover_files


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
    state.crop({"roi": {"x_min": 1, "x_max": 10, "y_min": 1, "y_max": 10}})
    assert state.stage == "cropped"
    assert not state.flat and not state.baselines and not state.cnr_records
    with pytest.raises(ValueError, match="complete"):
        state.export()
