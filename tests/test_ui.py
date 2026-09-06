import numpy as np

from qcl_analysis.roi import ROI
from ui.app import AnalysisState, _overlap, render_png


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
