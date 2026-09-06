"""Reflectance calculation utilities for QCL image analysis.

This module identifies the brightest pixels in each raw QCL image,
calculates a per-image gold-reference signal, and converts raw MCT
detector signals into relative reflectance.
"""

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from qcl_analysis.io import load_qcl_csv


def get_brightest_pixel_indices(
    image: NDArray[np.float64],
    n_pixels: int = 100,
) -> tuple[
    NDArray[np.int64],
    NDArray[np.int64],
    NDArray[np.float64],
]:
    """Return coordinates and values of the brightest pixels in an image.

    Parameters
    ----------
    image
        Two-dimensional raw QCL image.

    n_pixels
        Number of brightest pixels to select.

    Returns
    -------
    y_indices
        Row coordinates of the selected pixels.

    x_indices
        Column coordinates of the selected pixels.

    values
        Raw signal values of the selected pixels, sorted from
        brightest to dimmest.
    """

    if image.ndim != 2:
        raise ValueError(f"Expected a 2D image, got shape {image.shape}.")

    if image.size == 0:
        raise ValueError("Image is empty.")

    if not np.isfinite(image).all():
        raise ValueError("Image contains NaN or infinite values.")

    if n_pixels <= 0:
        raise ValueError("n_pixels must be greater than zero.")

    if n_pixels > image.size:
        raise ValueError(
            f"n_pixels ({n_pixels}) exceeds the total number "
            f"of image pixels ({image.size})."
        )

    flat_image = image.ravel()

    # Find the brightest n_pixels without sorting the entire image.
    start_index = flat_image.size - n_pixels

    brightest_flat_indices = np.argpartition(
        flat_image,
        start_index,
    )[start_index:]

    # Sort only the selected pixels from brightest to dimmest.
    selected_values = flat_image[brightest_flat_indices]

    order = np.argsort(selected_values)[::-1]

    brightest_flat_indices = brightest_flat_indices[order]

    brightest_values = flat_image[brightest_flat_indices]

    y_indices, x_indices = np.unravel_index(
        brightest_flat_indices,
        image.shape,
    )

    return (
        y_indices.astype(np.int64),
        x_indices.astype(np.int64),
        brightest_values.astype(np.float64),
    )


def calculate_gold_reference(
    image: NDArray[np.float64],
    n_pixels: int = 100,
) -> float:
    """Calculate I_goldref from the brightest pixels of one raw image.

    I_goldref is defined as the mean raw MCT signal of the
    brightest n_pixels pixels in that image.
    """

    _, _, values = get_brightest_pixel_indices(
        image,
        n_pixels=n_pixels,
    )

    i_goldref = float(np.mean(values))

    if not np.isfinite(i_goldref):
        raise ValueError("Gold-reference signal is not finite.")

    if i_goldref <= 0:
        raise ValueError("Gold-reference signal must be positive.")

    return i_goldref


def calculate_reflectance(
    image: NDArray[np.float64],
    i_goldref: float,
) -> NDArray[np.float64]:
    """Calculate relative reflectance from one raw QCL image.

    The relative reflectance is calculated as:

        R = I_raw / I_goldref

    where I_goldref is independently calculated for each
    pattern and wavenumber.
    """

    if not np.isfinite(i_goldref):
        raise ValueError("Gold-reference signal is not finite.")

    if i_goldref <= 0:
        raise ValueError("Gold-reference signal must be positive.")

    reflectance = image / i_goldref

    return reflectance


def add_gold_reference_signals(
    dataset: pd.DataFrame,
    n_pixels: int = 100,
) -> pd.DataFrame:
    """Calculate I_goldref independently for every image in a dataset.

    A copy of the dataset is returned with two additional columns:

    - ``i_goldref``
    - ``gold_reference_n_pixels``

    Each pattern/wavenumber image receives its own I_goldref.
    """

    required_columns = {
        "frame",
        "pattern",
        "wavenumber",
        "path",
    }

    missing_columns = required_columns - set(dataset.columns)

    if missing_columns:
        raise ValueError(
            f"Dataset is missing required columns: {sorted(missing_columns)}"
        )

    if dataset.empty:
        raise ValueError("Dataset is empty.")

    result = dataset.copy()

    gold_signals = []

    for row in result.itertuples(index=False):
        image = load_qcl_csv(row.path)

        i_goldref = calculate_gold_reference(
            image,
            n_pixels=n_pixels,
        )

        gold_signals.append(i_goldref)

    result["i_goldref"] = gold_signals

    result["gold_reference_n_pixels"] = n_pixels

    return result


def load_reflectance_image(
    row: pd.Series,
) -> NDArray[np.float64]:
    """Load one raw QCL image and calculate its relative reflectance.

    The supplied dataset row must already contain ``path`` and
    ``i_goldref``.
    """

    required_fields = {
        "path",
        "i_goldref",
    }

    missing_fields = required_fields - set(row.index)

    if missing_fields:
        raise ValueError(
            f"Dataset row is missing required fields: {sorted(missing_fields)}"
        )

    image = load_qcl_csv(row["path"])

    return calculate_reflectance(
        image,
        float(row["i_goldref"]),
    )
