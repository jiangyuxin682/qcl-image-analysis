from os import PathLike
from pathlib import Path

import numpy as np
from numpy.typing import NDArray


def load_qcl_csv(
    path: str | PathLike[str],
    *,
    delimiter: str = ",",
    skiprows: int = 0,
) -> NDArray[np.float64]:
    """Load a QCL CSV/text image as a 2D NumPy array.

    Parameters
    ----------
    path
        Path to the image file.
    delimiter
        Column delimiter used in the file.
    skiprows
        Number of rows to skip at the beginning of the file.

    Returns
    -------
    NDArray[np.float64]
        Two-dimensional image data.

    Raises
    ------
    FileNotFoundError
        If the input file does not exist.
    ValueError
        If the file cannot be parsed as a 2D numeric image.
    """
    file_path = Path(path).expanduser()

    if not file_path.is_file():
        raise FileNotFoundError(f"QCL image file not found: {file_path}")

    try:
        image = np.loadtxt(
            file_path,
            delimiter=delimiter,
            skiprows=skiprows,
            dtype=np.float64,
        )
    except ValueError as exc:
        raise ValueError(
            f"Could not parse QCL image as numeric data: {file_path}"
        ) from exc

    if image.ndim != 2 or image.size == 0:
        raise ValueError(
            f"QCL image must be a non-empty 2D array; got shape {image.shape}."
        )

    if not np.isfinite(image).all():
        raise ValueError(f"QCL image contains NaN or infinite values: {file_path}")

    return image
