import numpy as np
import pandas as pd
import pytest

from qcl_analysis.qc import (
    DatasetValidationError,
    find_incomplete_frames,
    validate_dataset_index,
    validate_image_files,
)


def test_valid_dataset_passes():
    dataset = pd.DataFrame(
        {
            "frame": [0, 0, 1, 1],
            "wavenumber": [1600, 1655, 1600, 1655],
            "path": ["a.csv", "b.csv", "c.csv", "d.csv"],
        }
    )

    validate_dataset_index(dataset)


def test_missing_wavenumber_raises_error():
    dataset = pd.DataFrame(
        {
            "frame": [0, 0, 1],
            "wavenumber": [1600, 1655, 1600],
            "path": ["a.csv", "b.csv", "c.csv"],
        }
    )

    with pytest.raises(
        DatasetValidationError,
        match="missing wavenumbers",
    ):
        validate_dataset_index(dataset)


def test_duplicate_frame_wavenumber_raises_error():
    dataset = pd.DataFrame(
        {
            "frame": [0, 0],
            "wavenumber": [1655, 1655],
            "path": ["a.csv", "b.csv"],
        }
    )

    with pytest.raises(
        DatasetValidationError,
        match="Duplicate",
    ):
        validate_dataset_index(dataset)


def test_expected_wavenumbers_are_checked():
    dataset = pd.DataFrame(
        {
            "frame": [0, 0, 1, 1],
            "wavenumber": [1600, 1655, 1600, 1655],
            "path": ["a.csv", "b.csv", "c.csv", "d.csv"],
        }
    )

    with pytest.raises(
        DatasetValidationError,
        match="1750",
    ):
        validate_dataset_index(
            dataset,
            expected_wavenumbers={1600, 1655, 1750},
        )


def test_find_incomplete_frames():
    dataset = pd.DataFrame(
        {
            "frame": [0, 0, 1],
            "wavenumber": [1600, 1655, 1600],
            "path": ["a.csv", "b.csv", "c.csv"],
        }
    )

    result = find_incomplete_frames(
        dataset,
        expected_wavenumbers={1600, 1655},
    )

    assert result == {1: [1655]}


def test_find_incomplete_frames_returns_empty_dict_for_complete_dataset():
    dataset = pd.DataFrame(
        {
            "frame": [0, 0, 1, 1],
            "wavenumber": [1600, 1655, 1600, 1655],
            "path": ["a.csv", "b.csv", "c.csv", "d.csv"],
        }
    )

    result = find_incomplete_frames(
        dataset,
        expected_wavenumbers={1600, 1655},
    )

    assert result == {}


def test_validate_image_files_returns_shape(tmp_path):
    image1 = tmp_path / "image1.csv"
    image2 = tmp_path / "image2.csv"

    np.savetxt(image1, np.ones((2, 3)), delimiter=",")
    np.savetxt(image2, np.ones((2, 3)), delimiter=",")

    dataset = pd.DataFrame(
        {
            "frame": [0, 1],
            "wavenumber": [1655, 1655],
            "path": [image1, image2],
        }
    )

    shape = validate_image_files(dataset)

    assert shape == (2, 3)


def test_validate_image_files_detects_shape_mismatch(tmp_path):
    image1 = tmp_path / "image1.csv"
    image2 = tmp_path / "image2.csv"

    np.savetxt(image1, np.ones((2, 3)), delimiter=",")
    np.savetxt(image2, np.ones((3, 3)), delimiter=",")

    dataset = pd.DataFrame(
        {
            "frame": [0, 1],
            "wavenumber": [1655, 1655],
            "path": [image1, image2],
        }
    )

    with pytest.raises(
        DatasetValidationError,
        match="shape mismatch",
    ):
        validate_image_files(dataset)
