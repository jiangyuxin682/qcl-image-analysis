import numpy as np
import pandas as pd

from qcl_analysis.io import load_qcl_csv

REQUIRED_COLUMNS = {
    "frame",
    "wavenumber",
    "path",
}


class DatasetValidationError(ValueError):
    """Raised when a QCL dataset fails quality-control checks."""


def validate_dataset_index(
    dataset: pd.DataFrame,
    expected_wavenumbers: set[int] | None = None,
) -> None:
    """Validate the metadata index of a QCL dataset.

    Checks:
    1. Required columns exist.
    2. Dataset is not empty.
    3. No duplicate frame/wavenumber combinations exist.
    4. Every frame contains the same expected wavenumbers.
    """

    missing_columns = REQUIRED_COLUMNS - set(dataset.columns)

    if missing_columns:
        raise DatasetValidationError(
            f"Dataset is missing required columns: {sorted(missing_columns)}"
        )

    if dataset.empty:
        raise DatasetValidationError("Dataset is empty.")

    duplicate_mask = dataset.duplicated(
        subset=["frame", "wavenumber"],
        keep=False,
    )

    if duplicate_mask.any():
        duplicates = (
            dataset.loc[
                duplicate_mask,
                ["frame", "wavenumber"],
            ]
            .drop_duplicates()
            .sort_values(["frame", "wavenumber"])
        )

        duplicate_pairs = list(
            duplicates.itertuples(
                index=False,
                name=None,
            )
        )

        raise DatasetValidationError(
            f"Duplicate frame/wavenumber pairs found: {duplicate_pairs}"
        )

    if expected_wavenumbers is None:
        required_wavenumbers = set(dataset["wavenumber"].unique())
    else:
        required_wavenumbers = set(expected_wavenumbers)

    problems = []

    for frame, frame_data in dataset.groupby("frame", sort=True):
        frame_wavenumbers = set(frame_data["wavenumber"])

        missing = sorted(required_wavenumbers - frame_wavenumbers)
        unexpected = sorted(frame_wavenumbers - required_wavenumbers)

        if missing:
            problems.append(f"Frame {frame} missing wavenumbers: {missing}")

        if unexpected:
            problems.append(f"Frame {frame} has unexpected wavenumbers: {unexpected}")

    if problems:
        raise DatasetValidationError(
            "Dataset failed wavenumber consistency check:\n" + "\n".join(problems)
        )


def find_incomplete_frames(
    dataset: pd.DataFrame,
    expected_wavenumbers: set[int],
) -> dict[int, list[int]]:
    """Find frames that are missing expected wavenumbers."""

    incomplete_frames = {}

    for frame, frame_data in dataset.groupby("frame", sort=True):
        frame_wavenumbers = set(frame_data["wavenumber"])

        missing = sorted(int(wn) for wn in expected_wavenumbers - frame_wavenumbers)

        if missing:
            incomplete_frames[int(frame)] = missing

    return incomplete_frames


def validate_image_files(
    dataset: pd.DataFrame,
    expected_shape: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Validate that all QCL image files are readable and have consistent shapes."""

    reference_shape = expected_shape

    for row in dataset.itertuples(index=False):
        try:
            image = load_qcl_csv(row.path)
        except (FileNotFoundError, ValueError) as exc:
            raise DatasetValidationError(
                f"Failed to load frame {row.frame}, "
                f"wavenumber {row.wavenumber}: {row.path}"
            ) from exc

        if reference_shape is None:
            reference_shape = image.shape

        if image.shape != reference_shape:
            raise DatasetValidationError(
                f"Image shape mismatch at frame {row.frame}, "
                f"wavenumber {row.wavenumber}: "
                f"expected {reference_shape}, got {image.shape}"
            )

    if reference_shape is None:
        raise DatasetValidationError("Dataset contains no image files.")

    return reference_shape


def add_reference_quality_flags(
    dataset: pd.DataFrame,
    *,
    robust_z_threshold: float = 5.0,
    min_relative_deviation: float = 0.10,
) -> pd.DataFrame:
    """Add per-image quality flags based on I_goldref stability.

    Each wavenumber is evaluated independently using its median and
    median absolute deviation (MAD).

    An image is marked as a reference outlier only when:
    1. its robust z-score exceeds ``robust_z_threshold``, and
    2. its relative deviation from the median exceeds
       ``min_relative_deviation``.

    This reduces false positives when the reference signal is very stable.
    """

    required_columns = {
        "frame",
        "pattern",
        "wavenumber",
        "i_goldref",
    }

    missing_columns = required_columns - set(dataset.columns)

    if missing_columns:
        raise DatasetValidationError(
            f"Dataset is missing required columns: {sorted(missing_columns)}"
        )

    if dataset.empty:
        raise DatasetValidationError("Dataset is empty.")

    if robust_z_threshold <= 0:
        raise ValueError("robust_z_threshold must be positive.")

    if min_relative_deviation < 0:
        raise ValueError("min_relative_deviation cannot be negative.")

    result = dataset.copy()

    result["reference_median"] = np.nan
    result["reference_mad"] = np.nan
    result["reference_relative_deviation"] = np.nan
    result["reference_robust_z"] = np.nan
    result["reference_valid"] = True
    result["quality_reason"] = "good"

    for wavenumber, group in result.groupby(
        "wavenumber",
        sort=True,
    ):
        indices = group.index

        values = group["i_goldref"].astype(float)

        median = float(values.median())

        absolute_deviation = (values - median).abs()

        mad = float(absolute_deviation.median())

        if median <= 0 or not np.isfinite(median):
            raise DatasetValidationError(
                f"Invalid reference median for {wavenumber} cm^-1: {median}"
            )

        relative_deviation = absolute_deviation / abs(median)

        # Standard modified z-score based on MAD.
        if mad > 0:
            robust_z = 0.67448975 * (values - median) / mad

            outlier = (robust_z.abs() > robust_z_threshold) & (
                relative_deviation > min_relative_deviation
            )

        else:
            # If MAD is zero, most values are identical.
            # Fall back to relative deviation.
            robust_z = pd.Series(
                0.0,
                index=indices,
            )

            outlier = relative_deviation > min_relative_deviation

        result.loc[
            indices,
            "reference_median",
        ] = median

        result.loc[
            indices,
            "reference_mad",
        ] = mad

        result.loc[
            indices,
            "reference_relative_deviation",
        ] = relative_deviation

        result.loc[
            indices,
            "reference_robust_z",
        ] = robust_z

        result.loc[
            indices,
            "reference_valid",
        ] = ~outlier

        low_mask = outlier & (values < median)

        high_mask = outlier & (values > median)

        result.loc[
            indices[low_mask],
            "quality_reason",
        ] = "low_reference"

        result.loc[
            indices[high_mask],
            "quality_reason",
        ] = "high_reference"

    return result


def add_frame_quality_flags(
    dataset: pd.DataFrame,
    *,
    expected_wavenumbers: set[int] | None = None,
) -> pd.DataFrame:
    """Add frame-level quality flags without removing any data.

    A frame is considered bad when:
    - any image in the frame has ``reference_valid == False``; or
    - an expected wavenumber is missing.
    """

    required_columns = {
        "frame",
        "wavenumber",
        "reference_valid",
    }

    missing_columns = required_columns - set(dataset.columns)

    if missing_columns:
        raise DatasetValidationError(
            f"Dataset is missing required columns: {sorted(missing_columns)}"
        )

    result = dataset.copy()

    frame_valid_map = {}
    frame_reason_map = {}

    for frame, group in result.groupby(
        "frame",
        sort=True,
    ):
        reasons = []

        bad_reference = (~group["reference_valid"]).any()

        if bad_reference:
            reasons.append("reference_outlier")

        if expected_wavenumbers is not None:
            available_wavenumbers = {int(wn) for wn in group["wavenumber"]}

            missing = sorted(expected_wavenumbers - available_wavenumbers)

            if missing:
                missing_text = ",".join(str(wn) for wn in missing)

                reasons.append(f"missing_wavenumber:{missing_text}")

        frame_is_valid = len(reasons) == 0

        frame_valid_map[frame] = frame_is_valid

        if frame_is_valid:
            frame_reason_map[frame] = "good"

        else:
            frame_reason_map[frame] = ";".join(reasons)

    result["frame_valid"] = result["frame"].map(frame_valid_map)

    result["frame_quality_reason"] = result["frame"].map(frame_reason_map)

    return result
