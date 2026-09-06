"""Visualization utilities for QCL image analysis.

This module provides interactive tools for:

- inspecting raw QCL images,
- visualizing brightest pixels used for gold-reference normalization,
- plotting gold-reference stability over time,
- selecting a shared cell-free metasurface ROI for R0 calculation,
- selecting shared on-MS and out-MS regions from reflectance images.
"""

import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.widgets import RectangleSelector

from qcl_analysis.absorbance import calculate_r0
from qcl_analysis.io import load_qcl_csv
from qcl_analysis.reflectance import (
    calculate_gold_reference,
    get_brightest_pixel_indices,
    load_reflectance_image,
)
from qcl_analysis.roi import ROI


class BrightestPixelsViewer:
    """Visualize brightest-pixel gold references across QCL images."""

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
        if not patterns:
            raise ValueError("At least one pattern must be selected.")

        if len(patterns) != len(set(patterns)):
            raise ValueError("Selected patterns must be unique.")

        if n_pixels <= 0:
            raise ValueError("n_pixels must be greater than zero.")

        required_columns = {"pattern", "wavenumber", "path"}
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
        self._mode = "idle"
        self._full_xlim = None
        self._full_ylim = None
        self._controls = None
        self._status = None
        self._click_connection = None
        self.reference_summary = None

    def _load_image(self, pattern: str, wavenumber: int):
        rows = self.dataset[
            (self.dataset["pattern"] == pattern)
            & (self.dataset["wavenumber"] == wavenumber)
        ]

        if rows.empty:
            return None

        return load_qcl_csv(rows.iloc[0]["path"])

    def _set_status(self, message: str):
        if self._status is not None:
            self._status.value = message

    def _set_mode(self, mode: str):
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

    @staticmethod
    def _bounded_limits(
        *,
        center: float,
        current_limits: tuple[float, float],
        full_limits: tuple[float, float],
        factor: float,
    ) -> tuple[float, float]:
        current_start, current_end = current_limits
        full_start, full_end = full_limits
        reversed_axis = current_start > current_end

        current_low = min(current_start, current_end)
        current_high = max(current_start, current_end)
        full_low = min(full_start, full_end)
        full_high = max(full_start, full_end)

        full_span = full_high - full_low
        current_span = current_high - current_low
        new_span = min(current_span * factor, full_span)

        center = min(max(center, full_low), full_high)
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
            return new_high, new_low

        return new_low, new_high

    def _on_image_click(self, event):
        if (
            self._mode not in {"zoom_in", "zoom_out"}
            or event.inaxes is None
            or event.xdata is None
            or event.ydata is None
        ):
            return

        factor = 0.5 if self._mode == "zoom_in" else 2.0

        new_xlim = self._bounded_limits(
            center=event.xdata,
            current_limits=event.inaxes.get_xlim(),
            full_limits=self._full_xlim,
            factor=factor,
        )
        new_ylim = self._bounded_limits(
            center=event.ydata,
            current_limits=event.inaxes.get_ylim(),
            full_limits=self._full_ylim,
            factor=factor,
        )

        event.inaxes.set_xlim(new_xlim)
        event.inaxes.set_ylim(new_ylim)
        self.figure.canvas.draw_idle()
        self._set_mode("idle")

    def _zoom_in_clicked(self, _):
        self._set_mode("zoom_in")

    def _zoom_out_clicked(self, _):
        self._set_mode("zoom_out")

    def _reset_view_clicked(self, _):
        if self.axes is None or self._full_xlim is None or self._full_ylim is None:
            return

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        self.figure.canvas.draw_idle()
        self._set_mode("idle")
        self._set_status("View reset.")

    def _build_controls(self):
        try:
            import ipywidgets as widgets
        except ImportError as exc:
            raise ImportError(
                "ipywidgets is required for BrightestPixelsViewer controls."
            ) from exc

        zoom_in_button = widgets.Button(description="Zoom In")
        zoom_out_button = widgets.Button(description="Zoom Out")
        reset_button = widgets.Button(description="Reset View")

        zoom_in_button.on_click(self._zoom_in_clicked)
        zoom_out_button.on_click(self._zoom_out_clicked)
        reset_button.on_click(self._reset_view_clicked)

        self._status = widgets.Label(
            value=(
                f"Displaying the brightest {self.n_pixels} pixels "
                "in each image as red crosses."
            )
        )

        self._controls = widgets.VBox(
            [
                widgets.HBox(
                    [
                        zoom_in_button,
                        zoom_out_button,
                        reset_button,
                    ]
                ),
                self._status,
            ]
        )

    def show(self):
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

        with plt.ioff():
            self.figure, self.axes = plt.subplots(
                n_wavenumbers,
                n_patterns,
                figsize=(figure_width, figure_height),
                squeeze=False,
                sharex=True,
                sharey=True,
            )

        reference_shape = None
        summary_records = []

        for row_index, wavenumber in enumerate(self.wavenumbers):
            for column_index, pattern in enumerate(self.patterns):
                ax = self.axes[row_index, column_index]
                image = self._load_image(pattern, wavenumber)

                if row_index == 0:
                    ax.set_title(pattern)

                ax.set_xlabel("x (pixel)")
                ax.set_ylabel(
                    f"{wavenumber} cm$^{{-1}}$\ny (pixel)"
                    if column_index == 0
                    else "y (pixel)"
                )

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

                im = ax.imshow(image, cmap=self.cmap, origin="upper")

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
                    f"I_goldref = {i_goldref:.4f}\nbrightest {self.n_pixels} pixels",
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
        self._full_xlim = (-0.5, width - 0.5)
        self._full_ylim = (height - 0.5, -0.5)

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

    def get_reference_summary(self) -> pd.DataFrame:
        if self.reference_summary is None:
            raise RuntimeError("No images have been displayed yet. Call show() first.")

        return self.reference_summary.copy()


class SharedMSReferenceSelector:
    """Select one shared cell-free metasurface ROI from reflectance images."""

    def __init__(
        self,
        dataset: pd.DataFrame,
        *,
        patterns: list[str],
        expected_wavenumbers: set[int] | None = None,
        cmap: str = "viridis",
        contrast_percentiles: tuple[float, float] = (1.0, 99.0),
        show_colorbar: bool = True,
    ):
        if not patterns:
            raise ValueError("At least one pattern must be selected.")

        if len(patterns) != len(set(patterns)):
            raise ValueError("Selected patterns must be unique.")

        required_columns = {"pattern", "wavenumber", "path", "i_goldref"}
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

        low, high = contrast_percentiles

        if not 0 <= low < high <= 100:
            raise ValueError(
                "contrast_percentiles must satisfy 0 <= low < high <= 100."
            )

        self.dataset = dataset
        self.patterns = patterns
        self.cmap = cmap
        self.show_colorbar = show_colorbar
        self.contrast_percentiles = (float(low), float(high))

        if expected_wavenumbers is None:
            selected_data = dataset[dataset["pattern"].isin(patterns)]
            self.wavenumbers = sorted(
                int(wn) for wn in selected_data["wavenumber"].unique()
            )
        else:
            self.wavenumbers = sorted(int(wn) for wn in expected_wavenumbers)

        if not self.wavenumbers:
            raise ValueError("No wavenumbers available for display.")

        self.roi: ROI | None = None
        self.confirmed_roi: ROI | None = None

        self.figure = None
        self.axes = None

        self._reflectance_images: dict[tuple[str, int], np.ndarray] = {}
        self._image_artists: dict[tuple[str, int], object] = {}
        self._patches = []
        self._selectors = []

        self._mode = "idle"
        self._full_xlim = None
        self._full_ylim = None
        self._image_shape = None

        self._controls = None
        self._status = None
        self._contrast_slider = None
        self._click_connection = None

        self._load_reflectance_images()

    def _get_row(self, pattern: str, wavenumber: int) -> pd.Series:
        wn_values = pd.to_numeric(
            self.dataset["wavenumber"],
            errors="coerce",
        )

        rows = self.dataset[
            (self.dataset["pattern"] == pattern) & (wn_values == int(wavenumber))
        ]

        if rows.empty:
            raise ValueError(f"No image found for {pattern}, {wavenumber} cm^-1.")

        if len(rows) > 1:
            raise ValueError(
                f"Multiple images found for {pattern}, {wavenumber} cm^-1."
            )

        return rows.iloc[0]

    def _load_reflectance_images(self):
        reference_shape = None

        for pattern in self.patterns:
            for wavenumber in self.wavenumbers:
                row = self._get_row(pattern, wavenumber)
                reflectance = load_reflectance_image(row)

                if reflectance.ndim != 2:
                    raise ValueError(
                        f"Expected a 2D reflectance image for "
                        f"{pattern}, {wavenumber} cm^-1, "
                        f"got shape {reflectance.shape}."
                    )

                if reference_shape is None:
                    reference_shape = reflectance.shape
                elif reflectance.shape != reference_shape:
                    raise ValueError(
                        "Displayed reflectance images must have the same shape."
                    )

                self._reflectance_images[(pattern, wavenumber)] = reflectance

        if reference_shape is None:
            raise ValueError("No reflectance images available for display.")

        self._image_shape = reference_shape

    def _set_status(self, message: str):
        if self._status is not None:
            self._status.value = message

    def _set_selectors_active(self, active: bool):
        for selector in self._selectors:
            selector.set_active(active)
            selector.set_visible(active)

    def _set_mode(self, mode: str):
        self._mode = mode

        if mode == "select":
            self._set_selectors_active(True)
            self._set_status("R0 ROI selection mode: drag on any reflectance image.")
        elif mode == "zoom_in":
            self._set_selectors_active(False)
            self._set_status("Zoom In mode: click a point on any image.")
        elif mode == "zoom_out":
            self._set_selectors_active(False)
            self._set_status("Zoom Out mode: click a point on any image.")
        else:
            self._set_selectors_active(False)
            self._update_status()

    @staticmethod
    def _get_contrast_limits(
        image: np.ndarray,
        low: float,
        high: float,
    ) -> tuple[float, float]:
        finite = image[np.isfinite(image)]

        if finite.size == 0:
            return 0.0, 1.0

        vmin, vmax = np.percentile(finite, [low, high])

        if vmin == vmax:
            vmax = vmin + np.finfo(float).eps

        return float(vmin), float(vmax)

    @staticmethod
    def _bounded_limits(
        *,
        center: float,
        current_limits: tuple[float, float],
        full_limits: tuple[float, float],
        factor: float,
    ) -> tuple[float, float]:
        current_start, current_end = current_limits
        full_start, full_end = full_limits
        reversed_axis = current_start > current_end

        current_low = min(current_start, current_end)
        current_high = max(current_start, current_end)
        full_low = min(full_start, full_end)
        full_high = max(full_start, full_end)

        full_span = full_high - full_low
        current_span = current_high - current_low
        new_span = min(current_span * factor, full_span)

        center = min(max(center, full_low), full_high)
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
            return new_high, new_low

        return new_low, new_high

    def _on_select(self, eclick, erelease):
        if self._mode != "select":
            return

        if (
            eclick.xdata is None
            or eclick.ydata is None
            or erelease.xdata is None
            or erelease.ydata is None
        ):
            return

        height, width = self._image_shape

        x_min = max(0, math.floor(min(eclick.xdata, erelease.xdata)))
        x_max = min(width, math.ceil(max(eclick.xdata, erelease.xdata)))
        y_min = max(0, math.floor(min(eclick.ydata, erelease.ydata)))
        y_max = min(height, math.ceil(max(eclick.ydata, erelease.ydata)))

        if x_min >= x_max or y_min >= y_max:
            self._set_status("Invalid ROI. Select a larger region.")
            return

        self.roi = ROI(
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        self.confirmed_roi = None

        self._update_roi_patches()
        self._set_mode("idle")

    def _update_roi_patches(self):
        if self.roi is None:
            for patch in self._patches:
                patch.set_visible(False)

            if self.figure is not None:
                self.figure.canvas.draw_idle()

            return

        width = self.roi.x_max - self.roi.x_min
        height = self.roi.y_max - self.roi.y_min

        for patch in self._patches:
            patch.set_xy(
                (
                    self.roi.x_min - 0.5,
                    self.roi.y_min - 0.5,
                )
            )
            patch.set_width(width)
            patch.set_height(height)
            patch.set_visible(True)

        if self.figure is not None:
            self.figure.canvas.draw_idle()

    def _update_status(self):
        if self.roi is None:
            self._set_status("No R0 ROI selected.")
            return

        prefix = (
            "R0 ROI confirmed" if self.confirmed_roi is not None else "R0 ROI selected"
        )

        self._set_status(
            f"{prefix}: "
            f"x=[{self.roi.x_min}, {self.roi.x_max}), "
            f"y=[{self.roi.y_min}, {self.roi.y_max})"
        )

    def _select_roi_clicked(self, _):
        self.confirmed_roi = None
        self._set_mode("select")

    def _clear_roi_clicked(self, _):
        self.roi = None
        self.confirmed_roi = None
        self._set_selectors_active(False)
        self._update_roi_patches()
        self._set_mode("idle")

    def _confirm_roi_clicked(self, _):
        if self.roi is None:
            self._set_status(
                "No R0 ROI selected. Select a cell-free metasurface region first."
            )
            return

        self.confirmed_roi = self.roi
        self._set_mode("idle")

    def _zoom_in_clicked(self, _):
        self._set_mode("zoom_in")

    def _zoom_out_clicked(self, _):
        self._set_mode("zoom_out")

    def _reset_view_clicked(self, _):
        if self.axes is None or self._full_xlim is None or self._full_ylim is None:
            return

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        self.figure.canvas.draw_idle()
        self._set_mode("idle")
        self._set_status("View reset.")

    def _on_image_click(self, event):
        if (
            self._mode not in {"zoom_in", "zoom_out"}
            or event.inaxes is None
            or event.xdata is None
            or event.ydata is None
        ):
            return

        if event.inaxes not in self.axes.flat:
            return

        factor = 0.5 if self._mode == "zoom_in" else 2.0

        new_xlim = self._bounded_limits(
            center=event.xdata,
            current_limits=event.inaxes.get_xlim(),
            full_limits=self._full_xlim,
            factor=factor,
        )
        new_ylim = self._bounded_limits(
            center=event.ydata,
            current_limits=event.inaxes.get_ylim(),
            full_limits=self._full_ylim,
            factor=factor,
        )

        event.inaxes.set_xlim(new_xlim)
        event.inaxes.set_ylim(new_ylim)

        self.figure.canvas.draw_idle()
        self._set_mode("idle")

    def _on_contrast_change(self, change):
        low, high = change["new"]

        if low >= high:
            return

        for key, image in self._reflectance_images.items():
            vmin, vmax = self._get_contrast_limits(image, low, high)
            self._image_artists[key].set_clim(vmin, vmax)

        if self.figure is not None:
            self.figure.canvas.draw_idle()

    def _build_controls(self):
        try:
            import ipywidgets as widgets
        except ImportError as exc:
            raise ImportError(
                "ipywidgets is required for SharedMSReferenceSelector controls."
            ) from exc

        zoom_in_button = widgets.Button(description="Zoom In")
        zoom_out_button = widgets.Button(description="Zoom Out")
        reset_button = widgets.Button(description="Reset View")

        select_button = widgets.Button(description="Select R0 ROI")
        clear_button = widgets.Button(description="Clear ROI")
        confirm_button = widgets.Button(
            description="Confirm R0 ROI",
            button_style="success",
        )

        zoom_in_button.on_click(self._zoom_in_clicked)
        zoom_out_button.on_click(self._zoom_out_clicked)
        reset_button.on_click(self._reset_view_clicked)

        select_button.on_click(self._select_roi_clicked)
        clear_button.on_click(self._clear_roi_clicked)
        confirm_button.on_click(self._confirm_roi_clicked)

        self._contrast_slider = widgets.FloatRangeSlider(
            value=self.contrast_percentiles,
            min=0.0,
            max=100.0,
            step=0.5,
            description="Contrast",
            continuous_update=True,
            readout_format=".1f",
            layout=widgets.Layout(width="520px"),
        )

        self._contrast_slider.observe(
            self._on_contrast_change,
            names="value",
        )

        self._status = widgets.Label(value="No R0 ROI selected.")

        self._controls = widgets.VBox(
            [
                widgets.HBox(
                    [
                        zoom_in_button,
                        zoom_out_button,
                        reset_button,
                    ]
                ),
                widgets.HBox(
                    [
                        select_button,
                        clear_button,
                        confirm_button,
                    ]
                ),
                self._contrast_slider,
                self._status,
            ]
        )

    def show(self):
        try:
            from IPython.display import display
        except ImportError as exc:
            raise ImportError(
                "IPython is required to display the interactive selector."
            ) from exc

        n_wavenumbers = len(self.wavenumbers)
        n_patterns = len(self.patterns)

        if self.figure is not None:
            plt.close(self.figure)

        figure_width = 6.2 * n_patterns if self.show_colorbar else 5.2 * n_patterns
        figure_height = 3.8 * n_wavenumbers

        with plt.ioff():
            self.figure, self.axes = plt.subplots(
                n_wavenumbers,
                n_patterns,
                figsize=(figure_width, figure_height),
                squeeze=False,
                sharex=True,
                sharey=True,
            )

        self._image_artists = {}
        self._patches = []
        self._selectors = []

        low, high = self.contrast_percentiles

        for row_index, wavenumber in enumerate(self.wavenumbers):
            for column_index, pattern in enumerate(self.patterns):
                ax = self.axes[row_index, column_index]
                key = (pattern, wavenumber)
                image = self._reflectance_images[key]

                vmin, vmax = self._get_contrast_limits(image, low, high)

                im = ax.imshow(
                    image,
                    cmap=self.cmap,
                    origin="upper",
                    vmin=vmin,
                    vmax=vmax,
                )

                self._image_artists[key] = im

                if row_index == 0:
                    ax.set_title(pattern)

                ax.set_xlabel("x (pixel)")
                ax.set_ylabel(
                    f"{wavenumber} cm$^{{-1}}$\ny (pixel)"
                    if column_index == 0
                    else "y (pixel)"
                )

                if self.show_colorbar:
                    cbar = self.figure.colorbar(
                        im,
                        ax=ax,
                        fraction=0.035,
                        pad=0.03,
                        shrink=0.8,
                    )
                    cbar.set_label("Reflectance R")

                patch = Rectangle(
                    (0, 0),
                    0,
                    0,
                    fill=False,
                    edgecolor="red",
                    linewidth=2.0,
                    linestyle="--",
                    visible=False,
                )

                ax.add_patch(patch)
                self._patches.append(patch)

                selector = RectangleSelector(
                    ax,
                    self._on_select,
                    useblit=True,
                    button=[1],
                    minspanx=1,
                    minspany=1,
                    spancoords="data",
                    interactive=False,
                )

                selector.set_active(False)
                selector.set_visible(False)
                self._selectors.append(selector)

        height, width = self._image_shape
        self._full_xlim = (-0.5, width - 0.5)
        self._full_ylim = (height - 0.5, -0.5)

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        if self._click_connection is not None:
            self.figure.canvas.mpl_disconnect(self._click_connection)

        self._click_connection = self.figure.canvas.mpl_connect(
            "button_press_event",
            self._on_image_click,
        )

        self._build_controls()
        self._update_roi_patches()

        self.figure.suptitle(
            "Select a shared cell-free metasurface ROI",
            fontsize=15,
        )
        self.figure.tight_layout()

        display(self._controls)
        display(self.figure.canvas)

    def get_roi(self) -> ROI:
        if self.confirmed_roi is not None:
            return self.confirmed_roi

        if self.roi is None:
            raise RuntimeError("No R0 ROI has been selected.")

        return self.roi

    def get_reflectance_image(
        self,
        pattern: str,
        wavenumber: int,
    ) -> np.ndarray:
        key = (pattern, int(wavenumber))

        if key not in self._reflectance_images:
            raise ValueError(
                f"No reflectance image found for {pattern}, {wavenumber} cm^-1."
            )

        return self._reflectance_images[key].copy()

    def get_r0_summary(self) -> pd.DataFrame:
        roi = self.get_roi()
        records = []

        for pattern in self.patterns:
            for wavenumber in self.wavenumbers:
                reflectance = self._reflectance_images[(pattern, wavenumber)]
                r0 = calculate_r0(reflectance, roi)
                row = self._get_row(pattern, wavenumber)

                record = {
                    "pattern": pattern,
                    "wavenumber": wavenumber,
                    "r0": r0,
                    "roi_x_min": roi.x_min,
                    "roi_x_max": roi.x_max,
                    "roi_y_min": roi.y_min,
                    "roi_y_max": roi.y_max,
                }

                if "frame" in row.index:
                    record["frame"] = int(row["frame"])

                records.append(record)

        summary = pd.DataFrame(records)

        preferred_columns = [
            "pattern",
            "frame",
            "wavenumber",
            "r0",
            "roi_x_min",
            "roi_x_max",
            "roi_y_min",
            "roi_y_max",
        ]

        existing_columns = [
            column for column in preferred_columns if column in summary.columns
        ]

        return summary[existing_columns]


class MSRegionSelector:
    """Select shared on-MS and out-MS regions from reflectance images."""

    def __init__(
        self,
        dataset: pd.DataFrame,
        *,
        patterns: list[str],
        expected_wavenumbers: set[int] | None = None,
        cmap: str = "viridis",
        contrast_percentiles: tuple[float, float] = (1.0, 99.0),
        show_colorbar: bool = True,
    ):
        if not patterns:
            raise ValueError("At least one pattern must be selected.")

        if len(patterns) != len(set(patterns)):
            raise ValueError("Selected patterns must be unique.")

        required_columns = {"pattern", "wavenumber", "path", "i_goldref"}
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

        low, high = contrast_percentiles

        if not 0 <= low < high <= 100:
            raise ValueError(
                "contrast_percentiles must satisfy 0 <= low < high <= 100."
            )

        self.dataset = dataset
        self.patterns = patterns
        self.cmap = cmap
        self.show_colorbar = show_colorbar
        self.contrast_percentiles = (float(low), float(high))

        if expected_wavenumbers is None:
            selected_data = dataset[dataset["pattern"].isin(patterns)]
            self.wavenumbers = sorted(
                int(wn) for wn in selected_data["wavenumber"].unique()
            )
        else:
            self.wavenumbers = sorted(int(wn) for wn in expected_wavenumbers)

        if not self.wavenumbers:
            raise ValueError("No wavenumbers available for display.")

        self.on_ms_roi: ROI | None = None
        self.out_ms_roi: ROI | None = None

        self.confirmed_on_ms_roi: ROI | None = None
        self.confirmed_out_ms_roi: ROI | None = None

        self.figure = None
        self.axes = None

        self._reflectance_images: dict[tuple[str, int], np.ndarray] = {}
        self._image_artists: dict[tuple[str, int], object] = {}

        self._on_ms_patches = []
        self._out_ms_patches = []
        self._selectors = []

        self._mode = "idle"
        self._full_xlim = None
        self._full_ylim = None
        self._image_shape = None

        self._controls = None
        self._status = None
        self._contrast_slider = None
        self._click_connection = None

        self._load_reflectance_images()

    def _get_row(self, pattern: str, wavenumber: int) -> pd.Series:
        wn_values = pd.to_numeric(
            self.dataset["wavenumber"],
            errors="coerce",
        )

        rows = self.dataset[
            (self.dataset["pattern"] == pattern) & (wn_values == int(wavenumber))
        ]

        if rows.empty:
            raise ValueError(f"No image found for {pattern}, {wavenumber} cm^-1.")

        if len(rows) > 1:
            raise ValueError(
                f"Multiple images found for {pattern}, {wavenumber} cm^-1."
            )

        return rows.iloc[0]

    def _load_reflectance_images(self):
        reference_shape = None

        for pattern in self.patterns:
            for wavenumber in self.wavenumbers:
                row = self._get_row(pattern, wavenumber)
                reflectance = load_reflectance_image(row)

                if reflectance.ndim != 2:
                    raise ValueError(
                        f"Expected a 2D reflectance image for "
                        f"{pattern}, {wavenumber} cm^-1, "
                        f"got shape {reflectance.shape}."
                    )

                if reference_shape is None:
                    reference_shape = reflectance.shape
                elif reflectance.shape != reference_shape:
                    raise ValueError(
                        "Displayed reflectance images must have the same shape."
                    )

                self._reflectance_images[(pattern, wavenumber)] = reflectance

        if reference_shape is None:
            raise ValueError("No reflectance images available for display.")

        self._image_shape = reference_shape

    def _set_status(self, message: str):
        if self._status is not None:
            self._status.value = message

    def _set_selectors_active(self, active: bool):
        for selector in self._selectors:
            selector.set_active(active)
            selector.set_visible(active)

    def _set_mode(self, mode: str):
        self._mode = mode

        if mode == "select_on_ms":
            self._set_selectors_active(True)
            self._set_status(
                "onMS selection mode: drag a rectangle around the metasurface region."
            )
        elif mode == "select_out_ms":
            self._set_selectors_active(True)
            self._set_status(
                "outMS selection mode: drag a rectangle outside the metasurface."
            )
        elif mode == "zoom_in":
            self._set_selectors_active(False)
            self._set_status("Zoom In mode: click a point on any image.")
        elif mode == "zoom_out":
            self._set_selectors_active(False)
            self._set_status("Zoom Out mode: click a point on any image.")
        else:
            self._set_selectors_active(False)
            self._update_status()

    @staticmethod
    def _get_contrast_limits(
        image: np.ndarray,
        low: float,
        high: float,
    ) -> tuple[float, float]:
        finite = image[np.isfinite(image)]

        if finite.size == 0:
            return 0.0, 1.0

        vmin, vmax = np.percentile(finite, [low, high])

        if vmin == vmax:
            vmax = vmin + np.finfo(float).eps

        return float(vmin), float(vmax)

    @staticmethod
    def _bounded_limits(
        *,
        center: float,
        current_limits: tuple[float, float],
        full_limits: tuple[float, float],
        factor: float,
    ) -> tuple[float, float]:
        current_start, current_end = current_limits
        full_start, full_end = full_limits
        reversed_axis = current_start > current_end

        current_low = min(current_start, current_end)
        current_high = max(current_start, current_end)
        full_low = min(full_start, full_end)
        full_high = max(full_start, full_end)

        full_span = full_high - full_low
        current_span = current_high - current_low
        new_span = min(current_span * factor, full_span)

        center = min(max(center, full_low), full_high)
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
            return new_high, new_low

        return new_low, new_high

    @staticmethod
    def _rois_overlap(first: ROI, second: ROI) -> bool:
        return not (
            first.x_max <= second.x_min
            or second.x_max <= first.x_min
            or first.y_max <= second.y_min
            or second.y_max <= first.y_min
        )

    def _on_select(self, eclick, erelease):
        if self._mode not in {"select_on_ms", "select_out_ms"}:
            return

        if (
            eclick.xdata is None
            or eclick.ydata is None
            or erelease.xdata is None
            or erelease.ydata is None
        ):
            return

        height, width = self._image_shape

        x_min = max(0, math.floor(min(eclick.xdata, erelease.xdata)))
        x_max = min(width, math.ceil(max(eclick.xdata, erelease.xdata)))
        y_min = max(0, math.floor(min(eclick.ydata, erelease.ydata)))
        y_max = min(height, math.ceil(max(eclick.ydata, erelease.ydata)))

        if x_min >= x_max or y_min >= y_max:
            self._set_status("Invalid ROI. Select a larger region.")
            return

        roi = ROI(
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )

        if self._mode == "select_on_ms":
            self.on_ms_roi = roi
        else:
            self.out_ms_roi = roi

        self.confirmed_on_ms_roi = None
        self.confirmed_out_ms_roi = None

        self._update_region_patches()
        self._set_mode("idle")

    def _update_region_patches(self):
        if self.on_ms_roi is None:
            for patch in self._on_ms_patches:
                patch.set_visible(False)
        else:
            width = self.on_ms_roi.x_max - self.on_ms_roi.x_min
            height = self.on_ms_roi.y_max - self.on_ms_roi.y_min

            for patch in self._on_ms_patches:
                patch.set_xy(
                    (
                        self.on_ms_roi.x_min - 0.5,
                        self.on_ms_roi.y_min - 0.5,
                    )
                )
                patch.set_width(width)
                patch.set_height(height)
                patch.set_visible(True)

        if self.out_ms_roi is None:
            for patch in self._out_ms_patches:
                patch.set_visible(False)
        else:
            width = self.out_ms_roi.x_max - self.out_ms_roi.x_min
            height = self.out_ms_roi.y_max - self.out_ms_roi.y_min

            for patch in self._out_ms_patches:
                patch.set_xy(
                    (
                        self.out_ms_roi.x_min - 0.5,
                        self.out_ms_roi.y_min - 0.5,
                    )
                )
                patch.set_width(width)
                patch.set_height(height)
                patch.set_visible(True)

        if self.figure is not None:
            self.figure.canvas.draw_idle()

    def _update_status(self):
        if self.on_ms_roi is None:
            on_ms_text = "onMS: not selected"
        else:
            on_ms_text = (
                "onMS: "
                f"x=[{self.on_ms_roi.x_min}, {self.on_ms_roi.x_max}), "
                f"y=[{self.on_ms_roi.y_min}, {self.on_ms_roi.y_max})"
            )

        if self.out_ms_roi is None:
            out_ms_text = "outMS: not selected"
        else:
            out_ms_text = (
                "outMS: "
                f"x=[{self.out_ms_roi.x_min}, {self.out_ms_roi.x_max}), "
                f"y=[{self.out_ms_roi.y_min}, {self.out_ms_roi.y_max})"
            )

        prefix = (
            "Regions confirmed. "
            if self.confirmed_on_ms_roi is not None
            and self.confirmed_out_ms_roi is not None
            else ""
        )

        self._set_status(prefix + on_ms_text + " | " + out_ms_text)

    def _select_on_ms_clicked(self, _):
        self.confirmed_on_ms_roi = None
        self.confirmed_out_ms_roi = None
        self._set_mode("select_on_ms")

    def _select_out_ms_clicked(self, _):
        self.confirmed_on_ms_roi = None
        self.confirmed_out_ms_roi = None
        self._set_mode("select_out_ms")

    def _clear_regions_clicked(self, _):
        self.on_ms_roi = None
        self.out_ms_roi = None
        self.confirmed_on_ms_roi = None
        self.confirmed_out_ms_roi = None

        self._set_selectors_active(False)
        self._update_region_patches()
        self._set_mode("idle")

    def _confirm_regions_clicked(self, _):
        if self.on_ms_roi is None or self.out_ms_roi is None:
            self._set_status("Select both onMS and outMS regions before confirming.")
            return

        if self._rois_overlap(self.on_ms_roi, self.out_ms_roi):
            self._set_status(
                "onMS and outMS regions overlap. Select non-overlapping regions."
            )
            return

        self.confirmed_on_ms_roi = self.on_ms_roi
        self.confirmed_out_ms_roi = self.out_ms_roi
        self._set_mode("idle")

    def _zoom_in_clicked(self, _):
        self._set_mode("zoom_in")

    def _zoom_out_clicked(self, _):
        self._set_mode("zoom_out")

    def _reset_view_clicked(self, _):
        if self.axes is None or self._full_xlim is None or self._full_ylim is None:
            return

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        self.figure.canvas.draw_idle()
        self._set_mode("idle")
        self._set_status("View reset.")

    def _on_image_click(self, event):
        if (
            self._mode not in {"zoom_in", "zoom_out"}
            or event.inaxes is None
            or event.xdata is None
            or event.ydata is None
        ):
            return

        if event.inaxes not in self.axes.flat:
            return

        factor = 0.5 if self._mode == "zoom_in" else 2.0

        new_xlim = self._bounded_limits(
            center=event.xdata,
            current_limits=event.inaxes.get_xlim(),
            full_limits=self._full_xlim,
            factor=factor,
        )
        new_ylim = self._bounded_limits(
            center=event.ydata,
            current_limits=event.inaxes.get_ylim(),
            full_limits=self._full_ylim,
            factor=factor,
        )

        event.inaxes.set_xlim(new_xlim)
        event.inaxes.set_ylim(new_ylim)

        self.figure.canvas.draw_idle()
        self._set_mode("idle")

    def _on_contrast_change(self, change):
        low, high = change["new"]

        if low >= high:
            return

        for key, image in self._reflectance_images.items():
            vmin, vmax = self._get_contrast_limits(image, low, high)
            self._image_artists[key].set_clim(vmin, vmax)

        if self.figure is not None:
            self.figure.canvas.draw_idle()

    def _build_controls(self):
        try:
            import ipywidgets as widgets
        except ImportError as exc:
            raise ImportError(
                "ipywidgets is required for MSRegionSelector controls."
            ) from exc

        zoom_in_button = widgets.Button(description="Zoom In")
        zoom_out_button = widgets.Button(description="Zoom Out")
        reset_button = widgets.Button(description="Reset View")

        select_on_ms_button = widgets.Button(description="Select onMS")
        select_out_ms_button = widgets.Button(description="Select outMS")
        clear_button = widgets.Button(description="Clear Regions")
        confirm_button = widgets.Button(
            description="Confirm Regions",
            button_style="success",
        )

        zoom_in_button.on_click(self._zoom_in_clicked)
        zoom_out_button.on_click(self._zoom_out_clicked)
        reset_button.on_click(self._reset_view_clicked)

        select_on_ms_button.on_click(self._select_on_ms_clicked)
        select_out_ms_button.on_click(self._select_out_ms_clicked)
        clear_button.on_click(self._clear_regions_clicked)
        confirm_button.on_click(self._confirm_regions_clicked)

        self._contrast_slider = widgets.FloatRangeSlider(
            value=self.contrast_percentiles,
            min=0.0,
            max=100.0,
            step=0.5,
            description="Contrast",
            continuous_update=True,
            readout_format=".1f",
            layout=widgets.Layout(width="520px"),
        )

        self._contrast_slider.observe(
            self._on_contrast_change,
            names="value",
        )

        self._status = widgets.Label(value="Select the onMS and outMS regions.")

        self._controls = widgets.VBox(
            [
                widgets.HBox(
                    [
                        zoom_in_button,
                        zoom_out_button,
                        reset_button,
                    ]
                ),
                widgets.HBox(
                    [
                        select_on_ms_button,
                        select_out_ms_button,
                        clear_button,
                        confirm_button,
                    ]
                ),
                self._contrast_slider,
                self._status,
            ]
        )

    def show(self):
        try:
            from IPython.display import display
        except ImportError as exc:
            raise ImportError(
                "IPython is required to display the interactive selector."
            ) from exc

        n_wavenumbers = len(self.wavenumbers)
        n_patterns = len(self.patterns)

        if self.figure is not None:
            plt.close(self.figure)

        figure_width = 6.2 * n_patterns if self.show_colorbar else 5.2 * n_patterns
        figure_height = 3.8 * n_wavenumbers

        with plt.ioff():
            self.figure, self.axes = plt.subplots(
                n_wavenumbers,
                n_patterns,
                figsize=(figure_width, figure_height),
                squeeze=False,
                sharex=True,
                sharey=True,
            )

        self._image_artists = {}
        self._on_ms_patches = []
        self._out_ms_patches = []
        self._selectors = []

        low, high = self.contrast_percentiles

        for row_index, wavenumber in enumerate(self.wavenumbers):
            for column_index, pattern in enumerate(self.patterns):
                ax = self.axes[row_index, column_index]
                key = (pattern, wavenumber)
                image = self._reflectance_images[key]

                vmin, vmax = self._get_contrast_limits(image, low, high)

                im = ax.imshow(
                    image,
                    cmap=self.cmap,
                    origin="upper",
                    vmin=vmin,
                    vmax=vmax,
                )

                self._image_artists[key] = im

                if row_index == 0:
                    ax.set_title(pattern)

                ax.set_xlabel("x (pixel)")
                ax.set_ylabel(
                    f"{wavenumber} cm$^{{-1}}$\ny (pixel)"
                    if column_index == 0
                    else "y (pixel)"
                )

                if self.show_colorbar:
                    cbar = self.figure.colorbar(
                        im,
                        ax=ax,
                        fraction=0.035,
                        pad=0.03,
                        shrink=0.8,
                    )
                    cbar.set_label("Reflectance R")

                on_ms_patch = Rectangle(
                    (0, 0),
                    0,
                    0,
                    fill=False,
                    edgecolor="cyan",
                    linewidth=2.0,
                    linestyle="-",
                    visible=False,
                )

                out_ms_patch = Rectangle(
                    (0, 0),
                    0,
                    0,
                    fill=False,
                    edgecolor="orange",
                    linewidth=2.0,
                    linestyle="--",
                    visible=False,
                )

                ax.add_patch(on_ms_patch)
                ax.add_patch(out_ms_patch)

                self._on_ms_patches.append(on_ms_patch)
                self._out_ms_patches.append(out_ms_patch)

                selector = RectangleSelector(
                    ax,
                    self._on_select,
                    useblit=True,
                    button=[1],
                    minspanx=1,
                    minspany=1,
                    spancoords="data",
                    interactive=False,
                )

                selector.set_active(False)
                selector.set_visible(False)
                self._selectors.append(selector)

        height, width = self._image_shape
        self._full_xlim = (-0.5, width - 0.5)
        self._full_ylim = (height - 0.5, -0.5)

        first_ax = self.axes.flat[0]
        first_ax.set_xlim(self._full_xlim)
        first_ax.set_ylim(self._full_ylim)

        if self._click_connection is not None:
            self.figure.canvas.mpl_disconnect(self._click_connection)

        self._click_connection = self.figure.canvas.mpl_connect(
            "button_press_event",
            self._on_image_click,
        )

        self._build_controls()
        self._update_region_patches()

        self.figure.suptitle(
            "Select shared on-MS and out-MS regions",
            fontsize=15,
        )
        self.figure.tight_layout()

        display(self._controls)
        display(self.figure.canvas)

    def get_regions(self) -> dict[str, ROI]:
        if self.confirmed_on_ms_roi is None or self.confirmed_out_ms_roi is None:
            raise RuntimeError("Both onMS and outMS regions must be confirmed first.")

        return {
            "onMS": self.confirmed_on_ms_roi,
            "outMS": self.confirmed_out_ms_roi,
        }

    def get_reflectance_image(
        self,
        pattern: str,
        wavenumber: int,
    ) -> np.ndarray:
        key = (pattern, int(wavenumber))

        if key not in self._reflectance_images:
            raise ValueError(
                f"No reflectance image found for {pattern}, {wavenumber} cm^-1."
            )

        return self._reflectance_images[key].copy()


def plot_gold_reference_trend(
    dataset: pd.DataFrame,
) -> tuple[plt.Figure, plt.Axes]:
    """Plot I_goldref versus frame for each wavenumber."""

    required_columns = {"frame", "wavenumber", "i_goldref"}
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
            handle for index, handle in enumerate(handles) if index != outlier_index
        ]
        ordered_labels = [labels[outlier_index]] + [
            label for index, label in enumerate(labels) if index != outlier_index
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
