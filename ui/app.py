from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import os
import threading
import webbrowser
import zipfile
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from qcl_analysis.absorbance import calculate_absorbance, calculate_r0
from qcl_analysis.cropping import crop_image, crop_ms_regions
from qcl_analysis.io import load_qcl_csv
from qcl_analysis.metadata import index_qcl_dataset
from qcl_analysis.qc import add_frame_quality_flags, add_reference_quality_flags
from qcl_analysis.reflectance import (
    add_gold_reference_signals,
    get_brightest_pixel_indices,
    load_reflectance_image,
)
from qcl_analysis.roi import ROI

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_STACKS = os.environ.get("QCL_STACKS_DIR", "")
COLORBAR_PANEL_WIDTH = 80
IMAGE_RENDER_SCALE = 3


def _json_ready(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _roi(payload: dict, prefix: str = "") -> ROI:
    return ROI(
        x_min=int(payload[f"{prefix}x_min"]),
        x_max=int(payload[f"{prefix}x_max"]),
        y_min=int(payload[f"{prefix}y_min"]),
        y_max=int(payload[f"{prefix}y_max"]),
    )


def _overlap(a: ROI, b: ROI) -> bool:
    return not (
        a.x_max <= b.x_min
        or b.x_max <= a.x_min
        or a.y_max <= b.y_min
        or b.y_max <= a.y_min
    )


class AnalysisState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        self.stacks_dir: Path | None = None
        self.dataset: pd.DataFrame | None = None
        self.patterns: list[str] = []
        self.wavenumbers: list[int] = []
        self.expected_wavenumbers: list[int] = []
        self.n_reference_pixels = 100
        self.raw_cache: dict[tuple[str, int], np.ndarray] = {}
        self.reflectance_cache: dict[tuple[str, int], np.ndarray] = {}
        self.on_roi: ROI | None = None
        self.out_roi: ROI | None = None
        self.on_r0_roi: ROI | None = None
        self.out_r0_roi: ROI | None = None
        self.on_reflectance: dict[tuple[str, int], np.ndarray] = {}
        self.out_reflectance: dict[tuple[str, int], np.ndarray] = {}
        self.on_absorbance: dict[tuple[str, int], np.ndarray] = {}
        self.out_absorbance: dict[tuple[str, int], np.ndarray] = {}
        self.timelapse_cache: dict[tuple[str, str, int], np.ndarray] = {}
        self.r0_summary = pd.DataFrame()
        self.check_summary = pd.DataFrame()

    def require_dataset(self) -> pd.DataFrame:
        if self.dataset is None:
            raise RuntimeError("Load a dataset first.")
        return self.dataset

    def index(self, payload: dict) -> dict:
        stacks_dir = Path(payload["stacks_dir"]).expanduser().resolve()
        expected = sorted({int(x) for x in payload.get("expected_wavenumbers", [])})
        n_pixels = int(payload.get("n_reference_pixels", 100))
        z_threshold = float(payload.get("robust_z_threshold", 5.0))
        relative_threshold = float(payload.get("min_relative_deviation", 0.10))

        indexed = index_qcl_dataset(stacks_dir)
        with_references = add_gold_reference_signals(indexed, n_pixels=n_pixels)
        qc = add_reference_quality_flags(
            with_references,
            robust_z_threshold=z_threshold,
            min_relative_deviation=relative_threshold,
        )
        qc = add_frame_quality_flags(
            qc,
            expected_wavenumbers=set(expected) if expected else None,
        )

        available_wavenumbers = sorted(int(x) for x in qc["wavenumber"].unique())
        if expected:
            missing = sorted(set(expected) - set(available_wavenumbers))
            if missing:
                raise ValueError(f"Wavenumbers not found in dataset: {missing}")
        else:
            expected = available_wavenumbers

        with self.lock:
            self.reset()
            self.stacks_dir = stacks_dir
            self.dataset = qc
            self.patterns = sorted(
                qc["pattern"].unique().tolist(),
                key=lambda x: int(x.removeprefix("pattern")),
            )
            self.wavenumbers = available_wavenumbers
            self.expected_wavenumbers = expected
            self.n_reference_pixels = n_pixels

        image = self.raw(self.patterns[0], expected[0])
        available_by_pattern = {
            pattern: {int(value) for value in group["wavenumber"]}
            for pattern, group in qc.groupby("pattern")
        }
        complete_patterns = [
            pattern
            for pattern in self.patterns
            if set(expected).issubset(available_by_pattern[pattern])
        ]
        incomplete_patterns = [
            {
                "pattern": pattern,
                "missing_wavenumbers": sorted(
                    set(expected) - available_by_pattern[pattern]
                ),
            }
            for pattern in self.patterns
            if not set(expected).issubset(available_by_pattern[pattern])
        ]
        invalid_images = int((~qc["reference_valid"]).sum())
        invalid_frames = int((~qc.drop_duplicates("frame")["frame_valid"]).sum())
        return {
            "stacks_dir": str(stacks_dir),
            "images": len(qc),
            "frames": int(qc["frame"].nunique()),
            "patterns": complete_patterns,
            "all_patterns": self.patterns,
            "incomplete_patterns": incomplete_patterns,
            "wavenumbers": available_wavenumbers,
            "selected_wavenumbers": expected,
            "image_shape": list(image.shape),
            "invalid_images": invalid_images,
            "invalid_frames": invalid_frames,
        }

    def row(self, pattern: str, wavenumber: int) -> pd.Series:
        dataset = self.require_dataset()
        rows = dataset[
            (dataset["pattern"] == pattern) & (dataset["wavenumber"] == int(wavenumber))
        ]
        if rows.empty:
            raise KeyError(f"No image found for {pattern}, {wavenumber} cm^-1.")
        return rows.iloc[0]

    def raw(self, pattern: str, wavenumber: int) -> np.ndarray:
        key = (pattern, int(wavenumber))
        if key not in self.raw_cache:
            self.raw_cache[key] = load_qcl_csv(self.row(*key)["path"])
        return self.raw_cache[key]

    def reflectance(self, pattern: str, wavenumber: int) -> np.ndarray:
        key = (pattern, int(wavenumber))
        if key not in self.reflectance_cache:
            self.reflectance_cache[key] = load_reflectance_image(self.row(*key))
        return self.reflectance_cache[key]

    def set_regions(self, payload: dict) -> dict:
        on_roi = _roi(payload, "on_")
        out_roi = _roi(payload, "out_")
        sample = self.raw(self.patterns[0], self.expected_wavenumbers[0])
        height, width = sample.shape
        for name, roi in (("on-MS", on_roi), ("out-MS", out_roi)):
            if roi.x_max > width or roi.y_max > height:
                raise ValueError(f"{name} ROI exceeds image bounds {width} × {height}.")
        if _overlap(on_roi, out_roi):
            raise ValueError("on-MS and out-MS regions must not overlap.")

        patterns = payload.get("patterns") or self.patterns[:2]
        wavenumbers = [
            int(x) for x in payload.get("wavenumbers", self.expected_wavenumbers)
        ]
        on_images, out_images = {}, {}
        for pattern in patterns:
            for wavenumber in wavenumbers:
                key = (pattern, wavenumber)
                on_images[key], out_images[key] = crop_ms_regions(
                    self.reflectance(*key), on_roi, out_roi
                )

        with self.lock:
            self.on_roi, self.out_roi = on_roi, out_roi
            self.on_reflectance, self.out_reflectance = on_images, out_images
            self.on_r0_roi = self.out_r0_roi = None
            self.on_absorbance, self.out_absorbance = {}, {}
            self.timelapse_cache = {}
            self.r0_summary, self.check_summary = pd.DataFrame(), pd.DataFrame()
        return {
            "on_roi": asdict(on_roi),
            "out_roi": asdict(out_roi),
            "on_shape": list(next(iter(on_images.values())).shape),
            "out_shape": list(next(iter(out_images.values())).shape),
            "patterns": patterns,
            "wavenumbers": wavenumbers,
        }

    def _cropped(self, region: str, key: tuple[str, int]) -> np.ndarray:
        images = self.on_reflectance if region == "on" else self.out_reflectance
        if not images:
            raise RuntimeError("Confirm on-MS and out-MS regions first.")
        if key not in images:
            raise KeyError(f"Image {key} is not in the selected analysis set.")
        return images[key]

    def calculate(self, payload: dict) -> dict:
        on_r0_roi = _roi(payload, "on_")
        out_r0_roi = _roi(payload, "out_")
        records, check_records = [], []
        on_absorbance, out_absorbance = {}, {}

        for region, images, roi in (
            ("on-MS", self.on_reflectance, on_r0_roi),
            ("out-MS", self.out_reflectance, out_r0_roi),
        ):
            if not images:
                raise RuntimeError("Confirm on-MS and out-MS regions first.")
            for (pattern, wavenumber), reflectance in images.items():
                r0 = calculate_r0(reflectance, roi)
                absorbance = calculate_absorbance(reflectance, r0)
                target = on_absorbance if region == "on-MS" else out_absorbance
                target[(pattern, wavenumber)] = absorbance
                mean_absorbance = float(np.nanmean(absorbance[roi.as_slices()]))
                records.append(
                    {
                        "region": region,
                        "pattern": pattern,
                        "wavenumber": wavenumber,
                        "r0": r0,
                    }
                )
                check_records.append(
                    {
                        "region": region,
                        "pattern": pattern,
                        "wavenumber": wavenumber,
                        "mean_absorbance_in_r0_roi": mean_absorbance,
                    }
                )

        with self.lock:
            self.on_r0_roi, self.out_r0_roi = on_r0_roi, out_r0_roi
            self.on_absorbance, self.out_absorbance = on_absorbance, out_absorbance
            self.timelapse_cache = {}
            self.r0_summary = pd.DataFrame(records)
            self.check_summary = pd.DataFrame(check_records)
        return {
            "r0_summary": records,
            "checks": check_records,
            "processed_images": len(on_absorbance) + len(out_absorbance),
        }

    def timelapse_absorbance(
        self,
        region: str,
        pattern: str,
        wavenumber: int,
    ) -> np.ndarray:
        if region not in {"on", "out"}:
            raise ValueError("Timelapse region must be 'on' or 'out'.")

        cache_key = (region, pattern, int(wavenumber))
        if cache_key in self.timelapse_cache:
            return self.timelapse_cache[cache_key]

        spatial_roi = self.on_roi if region == "on" else self.out_roi
        reference_roi = self.on_r0_roi if region == "on" else self.out_r0_roi
        if spatial_roi is None or reference_roi is None:
            raise RuntimeError("Calculate absorbance before building a timelapse.")

        reflectance = self.reflectance(pattern, int(wavenumber))
        cropped = crop_image(reflectance, spatial_roi)
        r0 = calculate_r0(cropped, reference_roi)
        absorbance = calculate_absorbance(cropped, r0)
        self.timelapse_cache[cache_key] = absorbance
        return absorbance

    def timelapse_manifest(
        self,
        region: str,
        wavenumber: int,
        *,
        start_frame: int | None = None,
        end_frame: int | None = None,
        low: float = 0.0,
        high: float = 100.0,
        exclude_invalid: bool = False,
    ) -> dict:
        if not 0 <= low < high <= 100:
            raise ValueError("Display percentiles must satisfy 0 <= low < high <= 100.")

        dataset = self.require_dataset()
        selected = dataset[dataset["wavenumber"] == int(wavenumber)].sort_values(
            "frame"
        )
        if start_frame is not None:
            selected = selected[selected["frame"] >= int(start_frame)]
        if end_frame is not None:
            selected = selected[selected["frame"] <= int(end_frame)]
        if (
            start_frame is not None
            and end_frame is not None
            and int(start_frame) > int(end_frame)
        ):
            raise ValueError("Start pattern must not come after end pattern.")
        if exclude_invalid:
            selected = selected[selected["frame_valid"]]
        if selected.empty:
            raise ValueError(f"No frames are available for {wavenumber} cm^-1.")

        created_timestamps = selected["created_timestamp"].astype(float).to_numpy()
        t0_timestamp = float(created_timestamps[0])
        intervals = np.diff(created_timestamps)
        dt_seconds = float(np.median(intervals)) if intervals.size else 0.0
        timestamp_sources = selected["timestamp_source"].astype(str).unique().tolist()
        timestamp_source = (
            timestamp_sources[0] if len(timestamp_sources) == 1 else "mixed"
        )

        frames = []
        finite_parts = []
        shape = None
        for row in selected.itertuples(index=False):
            image = self.timelapse_absorbance(
                region,
                str(row.pattern),
                int(row.wavenumber),
            )
            shape = image.shape
            finite = image[np.isfinite(image)]
            if finite.size:
                finite_parts.append(finite)
            frames.append(
                {
                    "pattern": str(row.pattern),
                    "frame": int(row.frame),
                    "valid": bool(row.frame_valid),
                    "created_at": datetime.fromtimestamp(
                        float(row.created_timestamp)
                    )
                    .astimezone()
                    .isoformat(timespec="seconds"),
                    "elapsed_seconds": float(row.created_timestamp)
                    - t0_timestamp,
                }
            )

        if not finite_parts or shape is None:
            raise ValueError("Timelapse contains no finite absorbance values.")
        vmin, vmax = np.percentile(np.concatenate(finite_parts), [low, high])
        if vmax <= vmin:
            vmax = vmin + np.finfo(float).eps

        return {
            "region": region,
            "wavenumber": int(wavenumber),
            "frames": frames,
            "frame_count": len(frames),
            "start_frame": int(frames[0]["frame"]),
            "end_frame": int(frames[-1]["frame"]),
            "t0": frames[0]["created_at"],
            "tend": frames[-1]["created_at"],
            "dt_seconds": dt_seconds,
            "timestamp_source": timestamp_source,
            "image_shape": list(shape),
            "vmin": float(vmin),
            "vmax": float(vmax),
        }

    def image(self, kind: str, pattern: str, wavenumber: int) -> np.ndarray:
        key = (pattern, int(wavenumber))
        if kind == "raw":
            return self.raw(*key)
        if kind == "reflectance":
            return self.reflectance(*key)
        mappings = {
            "on_reflectance": self.on_reflectance,
            "out_reflectance": self.out_reflectance,
            "on_absorbance": self.on_absorbance,
            "out_absorbance": self.out_absorbance,
        }
        if kind not in mappings:
            raise ValueError(f"Unknown image type: {kind}")
        if key not in mappings[kind]:
            raise RuntimeError(f"{kind.replace('_', ' ')} is not available yet.")
        return mappings[kind][key]

    def trend(self) -> list[dict]:
        dataset = self.require_dataset()
        columns = [
            "frame",
            "pattern",
            "wavenumber",
            "i_goldref",
            "reference_valid",
            "frame_valid",
        ]
        return dataset[columns].to_dict(orient="records")

    def export_zip(self) -> tuple[bytes, str]:
        if not self.on_absorbance:
            raise RuntimeError("Calculate absorbance before exporting.")
        buffer = io.BytesIO()
        metadata = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_stacks": str(self.stacks_dir),
            "wavenumbers": self.expected_wavenumbers,
            "n_reference_pixels": self.n_reference_pixels,
            "on_ms_roi": asdict(self.on_roi),
            "out_ms_roi": asdict(self.out_roi),
            "on_ms_r0_roi": asdict(self.on_r0_roi),
            "out_ms_r0_roi": asdict(self.out_r0_roi),
            "formula": "A = -log10(R / R0)",
        }
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata.json", json.dumps(metadata, indent=2))
            archive.writestr(
                "quality_control.csv", self.require_dataset().to_csv(index=False)
            )
            archive.writestr("r0_summary.csv", self.r0_summary.to_csv(index=False))
            archive.writestr(
                "reference_checks.csv", self.check_summary.to_csv(index=False)
            )
            for region, reflectance_images, absorbance_images in (
                ("on_ms", self.on_reflectance, self.on_absorbance),
                ("out_ms", self.out_reflectance, self.out_absorbance),
            ):
                for (pattern, wavenumber), image in reflectance_images.items():
                    text = io.StringIO()
                    np.savetxt(text, image, delimiter=",")
                    archive.writestr(
                        f"reflectance/{region}/{pattern}_{wavenumber}.csv",
                        text.getvalue(),
                    )
                for (pattern, wavenumber), image in absorbance_images.items():
                    text = io.StringIO()
                    np.savetxt(text, image, delimiter=",")
                    archive.writestr(
                        f"absorbance/{region}/{pattern}_{wavenumber}.csv",
                        text.getvalue(),
                    )
        timestamp = datetime.now().astimezone()
        return buffer.getvalue(), f"qcl-analysis-{timestamp:%Y%m%d-%H%M%S}.zip"


STATE = AnalysisState()


def render_png(
    image: np.ndarray,
    *,
    low: float = 0,
    high: float = 100,
    cmap: str = "inferno",
    brightest: int = 0,
    limits: tuple[float, float] | None = None,
    colorbar_label: str = "Value",
) -> bytes:
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        vmin, vmax = 0.0, 1.0
        normalized = np.zeros_like(image, dtype=float)
    else:
        vmin, vmax = limits or np.percentile(finite, [low, high])
        if vmax <= vmin:
            vmax = vmin + np.finfo(float).eps
        normalized = np.clip((image - vmin) / (vmax - vmin), 0, 1)
        normalized[~np.isfinite(normalized)] = 0
    rgba = plt.get_cmap(cmap)(normalized, bytes=True)
    rgb = rgba[:, :, :3].copy()
    if brightest:
        ys, xs, _ = get_brightest_pixel_indices(image, n_pixels=brightest)
        for y, x in zip(ys, xs):
            rgb[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (0, 255, 136)

    height, width = image.shape
    scale = IMAGE_RENDER_SCALE
    data_image = Image.fromarray(rgb).resize(
        (width * scale, height * scale), Image.Resampling.NEAREST
    )
    rendered = Image.new(
        "RGB",
        ((width + COLORBAR_PANEL_WIDTH) * scale, height * scale),
        (13, 23, 21),
    )
    rendered.paste(data_image, (0, 0))

    # Keep data at x:[0, width * scale) so ROI coordinates remain reversible.
    draw = ImageDraw.Draw(rendered)
    render_height = height * scale
    strip_x0 = (width + 8) * scale
    strip_x1 = strip_x0 + 12 * scale
    has_labels = render_height >= 60
    if has_labels:
        label_size = max(8, min(30, round(render_height * 0.065)))
        tick_size = max(7, min(27, round(render_height * 0.055)))
        top = label_size + tick_size // 2 + 8
        bottom = render_height - tick_size // 2 - 4
    else:
        top = 2 * scale
        bottom = max(top + scale, render_height - 2 * scale)
    gradient = np.linspace(1.0, 0.0, bottom - top + 1)[:, None]
    gradient_rgb = plt.get_cmap(cmap)(gradient, bytes=True)[:, :, :3]
    gradient_rgb = np.repeat(gradient_rgb, strip_x1 - strip_x0, axis=1)
    rendered.paste(Image.fromarray(gradient_rgb), (strip_x0, top))
    draw.rectangle(
        (strip_x0, top, strip_x1 - 1, bottom),
        outline=(224, 235, 232),
        width=scale,
    )

    if has_labels:
        try:
            label_font = ImageFont.truetype("DejaVuSans.ttf", label_size)
            tick_font = ImageFont.truetype("DejaVuSans.ttf", tick_size)
        except OSError:
            label_font = ImageFont.load_default(size=label_size)
            tick_font = ImageFont.load_default(size=tick_size)
        text_x = strip_x1 + 5 * scale
        text_color = (224, 235, 232)
        draw.text(
            (strip_x0, 3),
            colorbar_label,
            fill=text_color,
            font=label_font,
        )
        ticks = (
            (top, vmax),
            ((top + bottom) // 2, (vmin + vmax) / 2),
            (bottom, vmin),
        )
        for tick_y, value in ticks:
            draw.line(
                (strip_x1, tick_y, strip_x1 + 3 * scale, tick_y),
                fill=text_color,
                width=scale,
            )
            draw.text(
                (text_x, tick_y),
                f"{value:.3g}",
                fill=text_color,
                font=tick_font,
                anchor="lm",
            )
    output = io.BytesIO()
    rendered.save(output, format="PNG")
    return output.getvalue()


def render_svg(
    image: np.ndarray,
    *,
    low: float = 0,
    high: float = 100,
    cmap: str = "inferno",
    brightest: int = 0,
    limits: tuple[float, float] | None = None,
    colorbar_label: str = "Value",
) -> bytes:
    """Render a heatmap with a vector colorbar and resolution-independent text."""
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        vmin, vmax = 0.0, 1.0
        normalized = np.zeros_like(image, dtype=float)
    else:
        vmin, vmax = limits or np.percentile(finite, [low, high])
        if vmax <= vmin:
            vmax = vmin + np.finfo(float).eps
        normalized = np.clip((image - vmin) / (vmax - vmin), 0, 1)
        normalized[~np.isfinite(normalized)] = 0

    colormap = plt.get_cmap(cmap)
    rgb = colormap(normalized, bytes=True)[:, :, :3].copy()
    if brightest:
        ys, xs, _ = get_brightest_pixel_indices(image, n_pixels=brightest)
        for y, x in zip(ys, xs):
            rgb[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (0, 255, 136)

    raster = io.BytesIO()
    Image.fromarray(rgb).save(raster, format="PNG")
    encoded = base64.b64encode(raster.getvalue()).decode("ascii")

    height, width = image.shape
    bar_aspect = 18.0
    margin = max(1.2, min(3.0, height * 0.018))
    label_size = max(2.2, min(7.0, height * 0.055))
    tick_size = max(2.0, min(6.0, height * 0.05))
    bar_top = max(margin + label_size * 1.35, height * 0.09)
    bar_bottom = height - max(margin, tick_size * 0.62)
    bar_height = max(1.0, bar_bottom - bar_top)
    bar_width = bar_height / bar_aspect
    tick_length = max(0.8, bar_width * 0.42)
    gap = max(1.0, height * 0.012)
    values = (f"{vmax:.3g}", f"{(vmin + vmax) / 2:.3g}", f"{vmin:.3g}")
    label_width = len(colorbar_label) * label_size * 0.61
    value_width = max(len(value) for value in values) * tick_size * 0.61
    panel_width = max(
        label_width + 2 * margin,
        margin + bar_width + tick_length + gap + value_width + margin,
    )
    total_width = width + panel_width
    bar_x = width + margin
    text_x = bar_x + bar_width + tick_length + gap
    stroke_width = max(0.25, height * 0.0035)

    stops = []
    for offset in np.linspace(0, 1, 13):
        red, green, blue, _ = colormap(float(offset))
        color = f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"
        stops.append(
            f'<stop offset="{offset:.4f}" stop-color="{color}"/>'
        )
    tick_positions = (bar_top, (bar_top + bar_bottom) / 2, bar_bottom)
    tick_markup = "".join(
        f'<line x1="{bar_x + bar_width:.4f}" y1="{position:.4f}" '
        f'x2="{bar_x + bar_width + tick_length:.4f}" y2="{position:.4f}"/>'
        f'<text x="{text_x:.4f}" y="{position:.4f}" '
        f'font-size="{tick_size:.4f}" dominant-baseline="middle">'
        f'{html.escape(value)}</text>'
        for position, value in zip(tick_positions, values)
    )
    output_width = math.ceil(total_width * IMAGE_RENDER_SCALE)
    output_height = height * IMAGE_RENDER_SCALE
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg"
      width="{output_width}" height="{output_height}"
      viewBox="0 0 {total_width:.4f} {height}"
      preserveAspectRatio="xMinYMid meet">
      <defs>
        <linearGradient id="colorbar-gradient" x1="0" y1="1" x2="0" y2="0">
          {''.join(stops)}
        </linearGradient>
      </defs>
      <rect width="100%" height="100%" fill="#0d1715"/>
      <image href="data:image/png;base64,{encoded}" x="0" y="0"
        width="{width}" height="{height}" preserveAspectRatio="none"
        style="image-rendering:pixelated"/>
      <g fill="#e0ebe8" stroke="#e0ebe8"
        font-family="Inter,Segoe UI,DejaVu Sans,Arial,sans-serif">
        <text x="{bar_x:.4f}" y="{margin + label_size:.4f}"
          font-size="{label_size:.4f}" stroke="none">{html.escape(colorbar_label)}</text>
        <rect id="colorbar-strip" x="{bar_x:.4f}" y="{bar_top:.4f}"
          width="{bar_width:.4f}" height="{bar_height:.4f}"
          fill="url(#colorbar-gradient)" stroke-width="{stroke_width:.4f}"
          data-colorbar-aspect="{bar_aspect:.1f}"/>
        <g fill="#e0ebe8" stroke="#e0ebe8" stroke-width="{stroke_width:.4f}">
          {tick_markup}
        </g>
      </g>
    </svg>'''
    return svg.encode("utf-8")


def render_data_png(
    image: np.ndarray,
    *,
    low: float = 0,
    high: float = 100,
    cmap: str = "inferno",
    brightest: int = 0,
    limits: tuple[float, float] | None = None,
) -> tuple[bytes, float, float]:
    """Render only image data; the browser draws the vector-like HTML colorbar."""
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        vmin, vmax = 0.0, 1.0
        normalized = np.zeros_like(image, dtype=float)
    else:
        vmin, vmax = limits or np.percentile(finite, [low, high])
        if vmax <= vmin:
            vmax = vmin + np.finfo(float).eps
        normalized = np.clip((image - vmin) / (vmax - vmin), 0, 1)
        normalized[~np.isfinite(normalized)] = 0

    rgb = plt.get_cmap(cmap)(normalized, bytes=True)[:, :, :3].copy()
    if brightest:
        ys, xs, _ = get_brightest_pixel_indices(image, n_pixels=brightest)
        for y, x in zip(ys, xs):
            rgb[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (0, 255, 136)

    height, width = image.shape
    rendered = Image.fromarray(rgb).resize(
        (width * IMAGE_RENDER_SCALE, height * IMAGE_RENDER_SCALE),
        Image.Resampling.NEAREST,
    )
    output = io.BytesIO()
    rendered.save(output, format="PNG")
    return output.getvalue(), float(vmin), float(vmax)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload, default=_json_ready).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/defaults":
            return self._send_json({"stacks_dir": DEFAULT_STACKS})
        if parsed.path == "/api/trend":
            try:
                return self._send_json(STATE.trend())
            except Exception as exc:  # noqa: BLE001 - convert API errors to JSON
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/timelapse":
            try:
                q = parse_qs(parsed.query)
                return self._send_json(
                    STATE.timelapse_manifest(
                        q.get("region", ["on"])[0],
                        int(q["wavenumber"][0]),
                        start_frame=(
                            int(q["start_frame"][0]) if "start_frame" in q else None
                        ),
                        end_frame=(
                            int(q["end_frame"][0]) if "end_frame" in q else None
                        ),
                        low=float(q.get("low", [0])[0]),
                        high=float(q.get("high", [100])[0]),
                        exclude_invalid=q.get("exclude_invalid", ["false"])[0]
                        == "true",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - convert API errors to JSON
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/timelapse/frame":
            try:
                q = parse_qs(parsed.query)
                array = STATE.timelapse_absorbance(
                    q.get("region", ["on"])[0],
                    q["pattern"][0],
                    int(q["wavenumber"][0]),
                )
                data, _, _ = render_data_png(
                    array,
                    limits=(float(q["vmin"][0]), float(q["vmax"][0])),
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            except Exception as exc:  # noqa: BLE001 - convert API errors to JSON
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/image":
            try:
                q = parse_qs(parsed.query)
                kind = q.get("kind", ["raw"])[0]
                array = STATE.image(
                    kind,
                    q["pattern"][0],
                    int(q["wavenumber"][0]),
                )
                low = float(q.get("low", [0])[0])
                high = float(q.get("high", [100])[0])
                scale_patterns = [
                    pattern
                    for pattern in q.get("scale_patterns", [""])[0].split(",")
                    if pattern
                ]
                limits = None
                if scale_patterns:
                    wavenumber = int(q["wavenumber"][0])
                    finite_parts = [
                        part[np.isfinite(part)]
                        for part in (
                            STATE.image(kind, pattern, wavenumber)
                            for pattern in scale_patterns
                        )
                    ]
                    finite_parts = [part for part in finite_parts if part.size]
                    if finite_parts:
                        limits = tuple(
                            float(value)
                            for value in np.percentile(
                                np.concatenate(finite_parts), [low, high]
                            )
                        )
                colorbar_label = (
                    "Intensity"
                    if kind == "raw"
                    else "Absorbance"
                    if kind.endswith("absorbance")
                    else "Reflectance"
                )
                data, vmin, vmax = render_data_png(
                    array,
                    low=low,
                    high=high,
                    cmap=q.get("cmap", ["inferno"])[0],
                    brightest=int(q.get("brightest", [0])[0]),
                    limits=limits,
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Image-Width", str(array.shape[1]))
                self.send_header("X-Image-Height", str(array.shape[0]))
                self.send_header("X-Colorbar-Min", str(vmin))
                self.send_header("X-Colorbar-Max", str(vmax))
                self.send_header("X-Colorbar-Label", colorbar_label)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            except Exception as exc:  # noqa: BLE001 - convert API errors to JSON
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/export":
            try:
                data, filename = STATE.export_zip()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            except Exception as exc:  # noqa: BLE001 - convert API errors to JSON
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return super().do_GET()

    def do_POST(self):
        routes = {
            "/api/index": STATE.index,
            "/api/regions": STATE.set_regions,
            "/api/calculate": STATE.calculate,
        }
        if self.path not in routes:
            return self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        try:
            result = routes[self.path](self._body())
            return self._send_json(result)
        except Exception as exc:  # noqa: BLE001 - convert API errors to JSON
            return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="QCL Image Workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"QCL Image Workbench is running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
