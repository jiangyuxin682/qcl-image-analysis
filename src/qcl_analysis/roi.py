"""Region-of-interest utilities for QCL image analysis.

This module defines a reusable rectangular ROI object for selecting and
representing spatial regions in QCL images, such as the gold-reference area.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ROI:
    """Rectangular region of interest in image pixel coordinates."""

    x_min: int
    x_max: int
    y_min: int
    y_max: int

    def __post_init__(self):
        if self.x_min < 0 or self.y_min < 0:
            raise ValueError("ROI coordinates must be non-negative.")

        if self.x_min >= self.x_max:
            raise ValueError("x_min must be smaller than x_max.")

        if self.y_min >= self.y_max:
            raise ValueError("y_min must be smaller than y_max.")

    def as_slices(self) -> tuple[slice, slice]:
        """Return NumPy-compatible y/x slices."""

        return (
            slice(self.y_min, self.y_max),
            slice(self.x_min, self.x_max),
        )
