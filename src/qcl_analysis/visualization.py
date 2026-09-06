"""Visualization utilities for QCL image analysis.

This module provides interactive tools for inspecting raw QCL images
and visualizing the brightest pixels used to calculate the per-image
gold-reference signal for reflectance calculation.
"""

import matplotlib.pyplot as plt
import pandas as pd

from qcl_analysis.io import load_qcl_csv
from qcl_analysis.reflectance import (
    calculate_gold_reference,
    get_brightest_pixel_indices,
)


class BrightestPixelsViewer:
    """Visualize brightest-pixel gold references across QCL images.

    Each selected pattern is displayed as one column.
    Each wavenumber is displayed as one row.

    For every image, the brightest ``n_pixels`` are selected independently
    and displayed as red crosses. Their mean raw signal is the I_goldref
    used for that specific pattern and wavenumber.
    """

    def __init__(
        self,
        dataset: pd.DataFrame,
        *,
        patterns: list[str],
        expected_wavenumbers: set[int] | None = None,
        n_pixels: int = 100,
        cmap: str = "viridis",
        marker_size: float = 22.0,
        show_colorbar: bool = True,
    ):
        """Initialize the brightest-pixel viewer."""

        if not patterns:
            raise ValueError("At least one pattern must be selected.")

        if len(patterns) != len(set(patterns)):
            raise ValueError("Selected patterns must be unique.")

        if n_pixels <= 0:
            raise ValueError("n_pixels must be greater than zero.")

        required_columns = {
            "pattern",
            "wavenumber",
            "path",
        }

        missing_columns = required_columns - set(dataset.columns)

        if missing_columns:
            raise ValueError(
                f"Dataset is missing required columns: {sorted(missing_columns)}"
            )

        available_patterns = set(dataset["pattern"])

        missing_patterns = [
            pattern for pattern in patterns if pattern not in available_patterns
        ]

        if missing_patterns:
            raise ValueError(f"Patterns not found in dataset: {missing_patterns}")

        self.dataset = dataset
        self.patterns = patterns
        self.n_pixels = n_pixels
        self.cmap = cmap
        self.marker_size = marker_size
        self.show_colorbar = show_colorbar

        if expected_wavenumbers is None:
            selected_data = dataset[dataset["pattern"].isin(patterns)]

            self.wavenumbers = sorted(
                int(wn) for wn in selected_data["wavenumber"].unique()
            )

        else:
            self.wavenumbers = sorted(int(wn) for wn in expected_wavenumbers)

        if not self.wavenumbers:
            raise ValueError("No wavenumbers available for display.")

        self.figure = None
        self.axes = None

        # Interaction mode:
        # "idle", "zoom_in", or "zoom_out"
        self._mode = "idle"

        self._full_xlim = None
        self._full_ylim = None

        self._controls = None
        self._status = None

        self._click_connection = None

        # Summary of I_goldref values for displayed images.
        self.reference_summary = None

    def _load_image(
        self,
        pattern: str,
        wavenumber: int,
    ):
        """Load one raw QCL image from the indexed dataset."""

        rows = self.dataset[
            (self.dataset["pattern"] == pattern)
            & (self.dataset["wavenumber"] == wavenumber)
        ]

        if rows.empty:
            return None

        return load_qcl_csv(rows.iloc[0]["path"])

    def _set_status(
        self,
        message: str,
    ):
        """Update the viewer status message."""

        if self._status is not None:
            self._status.value = message

    def _set_mode(
        self,
        mode: str,
    ):
        """Change the current interaction mode."""

        self._mode = mode

        if mode == "idle":
            self._set_status(
                f"Displaying the brightest {self.n_pixels} pixels "
                "in each image as red crosses."
            )

        elif mode == "zoom_in":
            self._set_status("Zoom In mode: click a point on any image.")

        elif mode == "zoom_out":
            self._set_status("Zoom Out mode: click a point on any image.")

    def _bounded_limits(
        self,
        *,
        center: float,
        current_limits: tuple[float, float],
        full_limits: tuple[float, float],
        factor: float,
    ) -> tuple[float, float]:
        """Calculate zoomed limits constrained to the image boundary."""

        current_start, current_end = current_limits
        full_start, full_end = full_limits

        reversed_axis = current_start > current_end

        current_low = min(
            current_start,
            current_end,
        )

        current_high = max(
            current_start,
            current_end,
        )

        full_low = min(
            full_start,
            full_end,
        )

        full_high = max(
            full_start,
            full_end,
        )

        full_span = full_high - full_low
        current_span = current_high - current_low

        new_span = min(
            current_span * factor,
            full_span,
        )

        center = min(
            max(center, full_low),
            full_high,
        )

        new_low = center - new_span / 2
        new_high = center + new_span / 2

        if new_low < full_low:
            shift = full_low - new_low
            new_low += shift
            new_high += shift

        if new_high > full_high:
            shift = new_high - full_high
            new_low -= shift
            new_high -= shift

        if reversed_axis:
            return (
                new_high,
                new_low,
            )

        return (
            new_low,
            new_high,
        )

    def _on_image_click(
        self,
        event,
    ):
        """Handle one-shot Zoom In or Zoom Out."""

        if (
            self._mode
            not in {
                "zoom_in",
                "zoom_out",
            }
            or event.inaxes is None
            or event.xdata is None
            or event.ydata is None
        ):
            return

        ax = event.inaxes

        if self._mode == "zoom_in":
            factor = 0.5
        else:
            factor = 2.0

        new_xlim = self._bounded_limits(
            center=event.xdata,
            current_limits=ax.get_xlim(),
            full_limits=self._full_xlim,
            factor=factor,
        )

        new_ylim = self._bounded_limits(
            center=event.ydata,
            current_limits=ax.get_ylim(),
            full_limits=self._full_ylim,
            factor=factor,
        )

        # All axes share x and y, so every image zooms together.
        ax.set_xlim(new_xlim)
        ax.set_ylim(new_ylim)

        self.figure.canvas.draw_idle()

        # Return to normal viewing after one zoom operation.
        self._set_mode("idle")

    def _zoom_in_clicked(
        self,
        _,
    ):
        """Activate one-shot Zoom In mode."""
        self._set_mode("zoom_in")

    def _zoom_out_clicked(
        self,
        _,
    ):
        """Activate one-shot Zoom Out mode."""
        self._set_mode("zoom_out")

    def _reset_view_clicked(
        self,
        _,
    ):
        """Restore the full-image view."""

        if self.axes is None or self._full_xlim is None or self._full_ylim is None:
            return

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        self.figure.canvas.draw_idle()

        self._set_mode("idle")
        self._set_status("View reset.")

    def _build_controls(self):
        """Create notebook control buttons."""

        try:
            import ipywidgets as widgets
        except ImportError as exc:
            raise ImportError(
                "ipywidgets is required for BrightestPixelsViewer controls."
            ) from exc

        zoom_in_button = widgets.Button(
            description="Zoom In",
            tooltip=("Click, then click an image to zoom in around that point."),
        )

        zoom_out_button = widgets.Button(
            description="Zoom Out",
            tooltip=("Click, then click an image to zoom out around that point."),
        )

        reset_button = widgets.Button(
            description="Reset View",
        )

        zoom_in_button.on_click(self._zoom_in_clicked)
        zoom_out_button.on_click(self._zoom_out_clicked)
        reset_button.on_click(self._reset_view_clicked)

        self._status = widgets.Label(
            value=(
                f"Displaying the brightest {self.n_pixels} pixels "
                "in each image as red crosses."
            )
        )

        button_row = widgets.HBox(
            [
                zoom_in_button,
                zoom_out_button,
                reset_button,
            ]
        )

        self._controls = widgets.VBox(
            [
                button_row,
                self._status,
            ]
        )

    def show(self):
        """Display raw images with brightest-pixel reference overlays."""

        try:
            from IPython.display import display
        except ImportError as exc:
            raise ImportError(
                "IPython is required to display the interactive viewer."
            ) from exc

        n_wavenumbers = len(self.wavenumbers)
        n_patterns = len(self.patterns)

        if self.figure is not None:
            plt.close(self.figure)

        figure_width = 6.6 * n_patterns if self.show_colorbar else 5.2 * n_patterns
        figure_height = 3.8 * n_wavenumbers

        # Prevent Jupyter from automatically displaying the figure twice.
        with plt.ioff():
            self.figure, self.axes = plt.subplots(
                n_wavenumbers,
                n_patterns,
                figsize=(
                    figure_width,
                    figure_height,
                ),
                squeeze=False,
                sharex=True,
                sharey=True,
            )

        reference_shape = None
        summary_records = []

        for row_index, wavenumber in enumerate(self.wavenumbers):
            for column_index, pattern in enumerate(self.patterns):
                ax = self.axes[
                    row_index,
                    column_index,
                ]

                image = self._load_image(
                    pattern,
                    wavenumber,
                )

                if row_index == 0:
                    ax.set_title(pattern)

                ax.set_xlabel("x (pixel)")

                if column_index == 0:
                    ax.set_ylabel(f"{wavenumber} cm$^{{-1}}$\ny (pixel)")
                else:
                    ax.set_ylabel("y (pixel)")

                if image is None:
                    ax.text(
                        0.5,
                        0.5,
                        "Missing image",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )
                    continue

                if reference_shape is None:
                    reference_shape = image.shape
                elif image.shape != reference_shape:
                    raise ValueError("Displayed images must have the same shape.")

                im = ax.imshow(
                    image,
                    cmap=self.cmap,
                    origin="upper",
                )

                if self.show_colorbar:
                    cbar = self.figure.colorbar(
                        im,
                        ax=ax,
                        fraction=0.046,
                        pad=0.04,
                    )
                    cbar.set_label("Raw MCT signal")

                y_indices, x_indices, _ = get_brightest_pixel_indices(
                    image,
                    n_pixels=self.n_pixels,
                )

                i_goldref = calculate_gold_reference(
                    image,
                    n_pixels=self.n_pixels,
                )

                ax.scatter(
                    x_indices,
                    y_indices,
                    marker="x",
                    c="red",
                    s=self.marker_size,
                    linewidths=1.2,
                    zorder=3,
                )

                ax.text(
                    0.02,
                    0.98,
                    (f"I_goldref = {i_goldref:.4f}\nbrightest {self.n_pixels} pixels"),
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=8,
                    color="white",
                    bbox={
                        "facecolor": "black",
                        "alpha": 0.55,
                        "edgecolor": "none",
                        "pad": 3,
                    },
                )

                summary_records.append(
                    {
                        "pattern": pattern,
                        "wavenumber": wavenumber,
                        "i_goldref": i_goldref,
                        "n_pixels": self.n_pixels,
                    }
                )

        if reference_shape is None:
            raise ValueError("No images available for display.")

        height, width = reference_shape

        self._full_xlim = (
            -0.5,
            width - 0.5,
        )

        self._full_ylim = (
            height - 0.5,
            -0.5,
        )

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        if self._click_connection is not None:
            self.figure.canvas.mpl_disconnect(self._click_connection)

        self._click_connection = self.figure.canvas.mpl_connect(
            "button_press_event",
            self._on_image_click,
        )

        self.reference_summary = pd.DataFrame(summary_records)

        self._build_controls()

        self.figure.tight_layout()

        display(self._controls)
        display(self.figure.canvas)

    def get_reference_summary(
        self,
    ) -> pd.DataFrame:
        """Return I_goldref values for the currently displayed images."""

        if self.reference_summary is None:
            raise RuntimeError("No images have been displayed yet. Call show() first.")

        return self.reference_summary.copy()


def plot_gold_reference_trend(
    dataset: pd.DataFrame,
) -> tuple[plt.Figure, plt.Axes]:
    """Plot I_goldref versus frame for each wavenumber.

    If the dataset contains a boolean column ``reference_valid``,
    points with ``reference_valid == False`` are highlighted
    with red circles.
    """

    required_columns = {
        "frame",
        "wavenumber",
        "i_goldref",
    }

    missing_columns = required_columns - set(dataset.columns)
    if missing_columns:
        raise ValueError(
            f"Dataset is missing required columns: {sorted(missing_columns)}"
        )

    has_reference_flag = "reference_valid" in dataset.columns

    fig, ax = plt.subplots(figsize=(10, 6))

    outlier_label_added = False

    for wavenumber in sorted(dataset["wavenumber"].unique()):
        group = dataset[dataset["wavenumber"] == wavenumber].sort_values("frame")

        ax.plot(
            group["frame"],
            group["i_goldref"],
            marker="o",
            markersize=3,
            linewidth=1.8,
            label=f"{wavenumber} cm$^{{-1}}$",
        )

        if has_reference_flag:
            bad_group = group[~group["reference_valid"]]

            if not bad_group.empty:
                ax.scatter(
                    bad_group["frame"],
                    bad_group["i_goldref"],
                    s=80,
                    facecolors="none",
                    edgecolors="red",
                    linewidths=2.0,
                    zorder=5,
                    label=("flagged outlier" if not outlier_label_added else None),
                )
                outlier_label_added = True

    ax.set_title("Gold-reference signal over time")
    ax.set_xlabel("Frame")
    ax.set_ylabel("I_goldref (raw MCT signal)")
    ax.grid(True, alpha=0.3)

    handles, labels = ax.get_legend_handles_labels()

    if "flagged outlier" in labels:
        outlier_index = labels.index("flagged outlier")

        ordered_handles = [handles[outlier_index]] + [
            h for i, h in enumerate(handles) if i != outlier_index
        ]
        ordered_labels = [labels[outlier_index]] + [
            l for i, l in enumerate(labels) if i != outlier_index
        ]
    else:
        ordered_handles = handles
        ordered_labels = labels

    ax.legend(
        ordered_handles,
        ordered_labels,
        title="Wavenumber",
    )

    fig.tight_layout()
    return fig, ax
