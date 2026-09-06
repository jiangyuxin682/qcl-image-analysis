import io
import json
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from PIL import Image

from qcl_analysis.roi import ROI
from ui.app import AnalysisState, _overlap, render_data_png, render_png, render_svg


def test_ui_overlap_uses_half_open_roi_coordinates():
    left = ROI(0, 10, 0, 10)
    touching = ROI(10, 20, 0, 10)
    overlapping = ROI(9, 20, 0, 10)

    assert not _overlap(left, touching)
    assert _overlap(left, overlapping)


def test_ui_render_png_creates_png_data():
    image = np.arange(24, dtype=float).reshape(4, 6)
    data = render_png(image)

    assert data.startswith(b"\x89PNG")
    rendered = Image.open(io.BytesIO(data))
    assert rendered.size == (258, 12)


def test_ui_render_png_labels_colorbar_for_short_crop():
    image = np.arange(240, dtype=float).reshape(40, 6)
    rendered = np.asarray(Image.open(io.BytesIO(render_png(image))))
    background = np.array([13, 23, 21])

    assert np.any(rendered[:18, 42:] != background)


def test_ui_svg_colorbar_is_vector_and_has_fixed_aspect_ratio():
    ratios = []
    for shape in ((40, 6), (160, 120)):
        image = np.arange(np.prod(shape), dtype=float).reshape(shape)
        root = ET.fromstring(render_svg(image, colorbar_label="Absorbance"))
        strip = root.find(".//*[@id='colorbar-strip']")

        assert strip is not None
        assert "Absorbance" in "".join(root.itertext())
        ratios.append(float(strip.attrib["height"]) / float(strip.attrib["width"]))

    assert all(abs(ratio - 18.0) < 0.01 for ratio in ratios)


def test_timelapse_respects_pattern_range(tmp_path):
    stacks = tmp_path / "stacks"
    for frame in range(3):
        pattern_dir = stacks / f"pattern{frame}"
        pattern_dir.mkdir(parents=True)
        image = np.arange(1, 101, dtype=float).reshape(10, 10) + frame
        np.savetxt(pattern_dir / "lineScan_1600_0invcm.csv", image, delimiter=",")

    state = AnalysisState()
    state.index(
        {
            "stacks_dir": str(stacks),
            "expected_wavenumbers": [1600],
            "n_reference_pixels": 5,
        }
    )
    state.dataset["created_timestamp"] = state.dataset["frame"].map(
        {0: 1_700_000_000.0, 1: 1_700_000_300.0, 2: 1_700_000_900.0}
    )
    state.dataset["timestamp_source"] = "test_creation_time"
    state.set_regions(
        {
            "on_x_min": 0,
            "on_x_max": 5,
            "on_y_min": 0,
            "on_y_max": 10,
            "out_x_min": 5,
            "out_x_max": 10,
            "out_y_min": 0,
            "out_y_max": 10,
            "patterns": ["pattern0"],
            "wavenumbers": [1600],
        }
    )
    state.calculate(
        {
            "on_x_min": 0,
            "on_x_max": 2,
            "on_y_min": 0,
            "on_y_max": 2,
            "out_x_min": 0,
            "out_x_max": 2,
            "out_y_min": 0,
            "out_y_max": 2,
        }
    )

    manifest = state.timelapse_manifest(
        "on",
        1600,
        start_frame=1,
        end_frame=2,
    )

    assert [frame["pattern"] for frame in manifest["frames"]] == [
        "pattern1",
        "pattern2",
    ]
    assert manifest["frame_count"] == 2
    assert manifest["dt_seconds"] == 600.0
    assert manifest["timestamp_source"] == "test_creation_time"
    assert [frame["elapsed_seconds"] for frame in manifest["frames"]] == [
        0.0,
        600.0,
    ]
    assert manifest["t0"] == manifest["frames"][0]["created_at"]
    assert manifest["tend"] == manifest["frames"][-1]["created_at"]

    original = state.on_absorbance[("pattern0", 1600)].copy()
    render_data_png(original, low=10, high=90)
    archive_bytes, _ = state.export_zip()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        saved = np.loadtxt(
            io.StringIO(
                archive.read("absorbance/on_ms/pattern0_1600.csv").decode()
            ),
            delimiter=",",
        )

    metadata_text = json.dumps(metadata).lower()
    assert "contrast" not in metadata_text
    assert "percentile" not in metadata_text
    assert np.allclose(saved, original, equal_nan=True)
