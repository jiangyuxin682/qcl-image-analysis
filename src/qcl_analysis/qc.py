import pandas as pd

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
