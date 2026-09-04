import re
from pathlib import Path

import pandas as pd

_PATTERN_REGEX = re.compile(r"^pattern(\d+)$")
_WAVENUMBER_REGEX = re.compile(r"^lineScan_(\d+)_0invcm\.csv$")


def index_qcl_dataset(stacks_path: str | Path) -> pd.DataFrame:
    """Create an index of QCL images in a stacks directory."""

    stacks_path = Path(stacks_path).expanduser()

    if not stacks_path.is_dir():
        raise NotADirectoryError(f"QCL stacks directory not found: {stacks_path}")

    records = []

    for pattern_dir in stacks_path.iterdir():
        if not pattern_dir.is_dir():
            continue

        pattern_match = _PATTERN_REGEX.match(pattern_dir.name)

        if pattern_match is None:
            continue

        frame = int(pattern_match.group(1))

        for file_path in pattern_dir.iterdir():
            if not file_path.is_file():
                continue

            wn_match = _WAVENUMBER_REGEX.match(file_path.name)

            if wn_match is None:
                continue

            wavenumber = int(wn_match.group(1))

            records.append(
                {
                    "frame": frame,
                    "pattern": pattern_dir.name,
                    "wavenumber": wavenumber,
                    "path": file_path,
                }
            )

    dataset = pd.DataFrame(records)

    if dataset.empty:
        raise ValueError(f"No valid QCL CSV images found in: {stacks_path}")

    dataset = dataset.sort_values(["frame", "wavenumber"]).reset_index(drop=True)

    return dataset
