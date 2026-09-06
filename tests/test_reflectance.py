import numpy as np
import pandas as pd
import pytest

from qcl_analysis.reflectance import (
    add_gold_reference_signals,
    calculate_gold_reference,
    calculate_reflectance,
    get_brightest_pixel_indices,
    load_reflectance_image,
)


def test_get_brightest_pixel_indices():
    image = np.array(
        [
            [1.0, 2.0],
            [3.0, 4.0],
        ]
    )

    y, x, values = get_brightest_pixel_indices(
        image,
        n_pixels=2,
    )

    assert values.tolist() == [4.0, 3.0]

    coordinates = set(
        zip(
            y.tolist(),
            x.tolist(),
            strict=True,
        )
    )

    assert coordinates == {
        (1, 1),
        (1, 0),
    }


def test_calculate_gold_reference():
    image = np.array(
        [
            [1.0, 2.0],
            [3.0, 5.0],
        ]
    )

    i_goldref = calculate_gold_reference(
        image,
        n_pixels=2,
    )

    assert i_goldref == pytest.approx(4.0)


def test_calculate_reflectance():
    image = np.array(
        [
            [2.0, 4.0],
            [6.0, 8.0],
        ]
    )

    reflectance = calculate_reflectance(
        image,
        i_goldref=4.0,
    )

    expected = np.array(
        [
            [0.5, 1.0],
            [1.5, 2.0],
        ]
    )

    np.testing.assert_allclose(
        reflectance,
        expected,
    )


def test_reference_pixels_have_mean_reflectance_one():
    image = np.array(
        [
            [1.0, 2.0],
            [3.0, 5.0],
        ]
    )

    y, x, _ = get_brightest_pixel_indices(
        image,
        n_pixels=2,
    )

    i_goldref = calculate_gold_reference(
        image,
        n_pixels=2,
    )

    reflectance = calculate_reflectance(
        image,
        i_goldref,
    )

    assert reflectance[
        y,
        x,
    ].mean() == pytest.approx(1.0)


def test_add_gold_reference_signals(tmp_path):
    image1 = np.array(
        [
            [1.0, 2.0],
            [3.0, 5.0],
        ]
    )

    image2 = np.array(
        [
            [2.0, 4.0],
            [6.0, 10.0],
        ]
    )

    path1 = tmp_path / "image1.csv"
    path2 = tmp_path / "image2.csv"

    np.savetxt(
        path1,
        image1,
        delimiter=",",
    )

    np.savetxt(
        path2,
        image2,
        delimiter=",",
    )

    dataset = pd.DataFrame(
        {
            "frame": [0, 1],
            "pattern": [
                "pattern0",
                "pattern1",
            ],
            "wavenumber": [
                1655,
                1655,
            ],
            "path": [
                path1,
                path2,
            ],
        }
    )

    result = add_gold_reference_signals(
        dataset,
        n_pixels=2,
    )

    assert result.loc[
        0,
        "i_goldref",
    ] == pytest.approx(4.0)

    assert result.loc[
        1,
        "i_goldref",
    ] == pytest.approx(8.0)


def test_load_reflectance_image(tmp_path):
    image = np.array(
        [
            [2.0, 4.0],
            [6.0, 8.0],
        ]
    )

    path = tmp_path / "image.csv"

    np.savetxt(
        path,
        image,
        delimiter=",",
    )

    row = pd.Series(
        {
            "path": path,
            "i_goldref": 4.0,
        }
    )

    reflectance = load_reflectance_image(row)

    expected = np.array(
        [
            [0.5, 1.0],
            [1.5, 2.0],
        ]
    )

    np.testing.assert_allclose(
        reflectance,
        expected,
    )
