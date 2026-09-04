import numpy as np
import pytest

from qcl_analysis.io import load_qcl_csv


def test_load_qcl_csv(tmp_path):
    expected = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ]
    )

    file_path = tmp_path / "image.csv"
    np.savetxt(file_path, expected, delimiter=",")

    image = load_qcl_csv(file_path)

    np.testing.assert_allclose(image, expected)


def test_missing_file_raises_error(tmp_path):
    file_path = tmp_path / "missing.csv"

    with pytest.raises(FileNotFoundError):
        load_qcl_csv(file_path)


def test_one_dimensional_data_raises_error(tmp_path):
    file_path = tmp_path / "invalid.csv"
    np.savetxt(file_path, np.array([1.0, 2.0, 3.0]), delimiter=",")

    with pytest.raises(ValueError):
        load_qcl_csv(file_path)
