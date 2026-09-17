"""Local QCL processing interface combining the existing app and notebook 06.

Run ``python ui/app_processing.py`` from the repository (default port 8766).
Filename discovery precedes explicit center/reference-band assignment. The
union of selected bands is processed independently for each selected pattern:
optional gold normalization -> shared on-MS crop -> Fourier -> rolling-ball field
-> per-image analyte-free reference -> absorbance -> pixelwise baseline -> CNR.

All operations run locally. Mutations commit complete results under a lock and
invalidate dependent stages. Raw files are never changed. This module reuses
the scientific functions exercised by notebooks 04-06 and the original image
renderer, while serving an independent frontend from static_processing.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import re
import sys
import threading
import tempfile
import time
import webbrowser
import zipfile
import uuid
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "qcl-processing-mpl")
)

import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter
from scipy.signal import savgol_filter

from qcl_analysis.absorbance import calculate_absorbance
from qcl_analysis.baseline import correct_absorbance_baselines
from qcl_analysis.cnr import compare_stage_cnr
from qcl_analysis.cropping import crop_image
from qcl_analysis.drift import gold_drift_rois
from qcl_analysis.flat_field import FlatFieldResult, rolling_ball_flat_field
from qcl_analysis.fourier import (
    FourierFilterResult,
    apply_fourier_combined_filter,
    apply_fourier_lowpass_filter,
    apply_fourier_notch_filter,
    fourier_spectrum,
)
from qcl_analysis.io import load_qcl_csv
from qcl_analysis.qc import add_frame_quality_flags, add_reference_quality_flags
from qcl_analysis.reflectance import get_brightest_pixel_indices
from qcl_analysis.roi import ROI
from ui.app import render_data_png
from ui.video_export import encode_video


def display_limits(limits, payload):
    """Zero anchoring changes only the renderer, never analytical clipping."""
    if payload.get("colorbar_zero") in (True, "true", "1"):
        return (0.0, max(float(limits[1]), 1e-12))
    return limits


def render_processing_png(array, payload, *, limits=None, low=0, high=100):
    if limits is None:
        finite = array[np.isfinite(array)]
        limits = tuple(np.percentile(finite, [low, high])) if finite.size else (0.0, 1.0)
    return render_data_png(array, limits=display_limits(limits, payload))

STATIC = Path(__file__).with_name("static_processing")
FILE_RE = re.compile(r"^lineScan_(\d+)_0invcm\.csv$", re.IGNORECASE)
STAGES = ("raw", "reflectance", "fourier", "rolling", "absorbance", "baseline")


def clean_json(value):
    """Convert NumPy/path values and undefined statistics to strict JSON."""
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean_json(value.tolist())
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def integer(value, name):
    """Reject fractional coordinates/bands rather than truncating silently."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer.")
    number = float(value)
    if not np.isfinite(number) or not number.is_integer():
        raise ValueError(f"{name} must be an integer.")
    return int(number)


def roi_from(payload):
    return ROI(
        **{k: integer(payload[k], k) for k in ("x_min", "x_max", "y_min", "y_max")}
    )


def select_cell_free_pixels(image, method, count, search_roi=None):
    """Return stable (y, x) coordinates for extreme positive finite pixels."""
    if method not in {"brightest", "darkest"}:
        raise ValueError("Analyte-free pixel method must be brightest or darkest.")
    count = integer(count, "Analyte-free pixel count")
    if count < 1:
        raise ValueError("Analyte-free pixel count must be at least 1.")
    image = np.asarray(image, dtype=float)
    eligible = np.isfinite(image) & (image > 0)
    if search_roi is not None:
        crop_image(image, search_roi, copy=False)
        inside = np.zeros(image.shape, dtype=bool)
        inside[search_roi.as_slices()] = True
        eligible &= inside
    valid_flat = np.flatnonzero(eligible.ravel())
    if count > valid_flat.size:
        raise ValueError(
            f"Analyte-free pixel count ({count}) exceeds the number of positive finite pixels ({valid_flat.size})."
        )
    values = image.ravel()[valid_flat]
    order = np.argsort(-values if method == "brightest" else values, kind="stable")
    selected = valid_flat[order[:count]]
    return np.column_stack(np.unravel_index(selected, image.shape)).astype(int)


def discover_files(path):
    """Discover spectral filenames in a pattern folder or a stacks directory.

    A CSV path selects its sibling spectral files. A directory containing a
    stacks child is also accepted. Only the documented lineScan name is parsed;
    metadata CSVs are ignored. Duplicate (pattern, band) pairs are errors.
    """
    path = str(path).strip()
    while len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
        path = path[1:-1].strip()
    if not path:
        raise ValueError("Choose a data path.")
    source = Path(path).expanduser().resolve()
    if source.is_file():
        if not FILE_RE.fullmatch(source.name):
            raise ValueError(
                "Choose a lineScan_<wavenumber>_0invcm.csv file or its folder."
            )
        source = source.parent
    if not source.is_dir():
        raise ValueError(f"Directory not found: {source}")
    if (source / "stacks").is_dir():
        source = source / "stacks"
    folders = (
        [source]
        if any(FILE_RE.fullmatch(p.name) for p in source.iterdir() if p.is_file())
        else [
            p
            for p in source.iterdir()
            if p.is_dir() and re.fullmatch(r"pattern\d+", p.name)
        ]
    )
    records = []
    for folder in folders:
        match = re.fullmatch(r"pattern(\d+)", folder.name)
        frame = int(match[1]) if match else 0
        for file in folder.iterdir():
            name = FILE_RE.fullmatch(file.name)
            if file.is_file() and name:
                wn = int(name[1])
                if wn <= 0:
                    raise ValueError("Filename wavenumbers must be positive.")
                stat = file.stat()
                timestamp = getattr(
                    stat,
                    "st_birthtime",
                    stat.st_ctime if os.name == "nt" else stat.st_mtime,
                )
                records.append(
                    {
                        "pattern": folder.name,
                        "frame": frame,
                        "wavenumber": wn,
                        "path": file,
                        "created_timestamp": timestamp,
                        "timestamp_source": "creation_time"
                        if hasattr(stat, "st_birthtime") or os.name == "nt"
                        else "modified_time_fallback",
                    }
                )
    if not records:
        raise ValueError("No lineScan_<wavenumber>_0invcm.csv images were found.")
    dataset = (
        pd.DataFrame(records)
        .sort_values(["frame", "wavenumber"])
        .reset_index(drop=True)
    )
    if dataset.duplicated(["pattern", "wavenumber"]).any():
        raise ValueError("Duplicate pattern/wavenumber files found.")
    return source, dataset


class ProcessingState:
    """Own one local session with shared spatial ROIs across patterns and bands."""

    def __init__(self):
        self.lock = threading.RLock()
        self.progress_lock = threading.Lock()
        self.progress = {"status": "idle", "completed": 0, "total": 0}
        self.last_video = None
        self.dataset = None
        self.path = None
        self.version = 0
        self.stage = "empty"
        self.reset_analysis()

    def reset_analysis(self):
        self.mapping = {}
        self.patterns = []
        self.bands = []
        self.raw = {}
        self.ref = {}
        self.has_gold = None
        self.gold_pixels = {}
        self.n_pixels = 0
        self.qc_settings = {}
        self.qc = pd.DataFrame()
        self.on_roi = None
        self.on_rois = {}
        self.drift = {}
        self.crops = {}
        self.clear_processed()

    def clear_processed(self):
        self.ff = {}
        self.flat = {}
        self.parameters = {}
        self.clear_absorbance()

    def clear_absorbance(self):
        self.r0_roi = None
        self.r0_selection = {"method": "roi"}
        self.r0_pixels = {}
        self.absorbance = {}
        self.baselines = {}
        self.r0_records = []
        self.cnr_records = []
        self.cnr_rois = None

    def require(self, stage):
        order = [
            "empty",
            "discovered",
            "configured",
            "referenced",
            "cropped",
            "processed",
            "absorbed",
            "complete",
        ]
        if order.index(self.stage) < order.index(stage):
            raise ValueError(f"Complete the {stage} step first.")

    def status(self):
        return {
            "stage": self.stage,
            "version": self.version,
            "patterns": self.patterns,
            "bands": self.bands,
            "mapping": self.mapping,
            "has_gold": self.has_gold,
            "processing_basis": "reflectance" if self.has_gold else "raw_intensity",
            "on_roi": asdict(self.on_roi) if self.on_roi else None,
            "r0_roi": asdict(self.r0_roi) if self.r0_roi else None,
            "r0_selection": self.r0_selection,
        }

    def discover(self, payload):
        path, dataset = discover_files(payload["path"])
        self.reset_analysis()
        self.path, self.dataset = path, dataset
        self.stage = "discovered"
        self.version += 1
        return {
            **self.status(),
            "path": str(path),
            "files": len(dataset),
            "wavenumbers": sorted(int(v) for v in dataset.wavenumber.unique()),
            "availability": [
                {"pattern": p, "wavenumbers": sorted(int(x) for x in g.wavenumber)}
                for p, g in dataset.groupby("pattern", sort=False)
            ],
        }

    def raw_inspection(self, payload):
        """Read full-image raw spectra before selecting processing bands or ROIs."""
        self.require("discovered")
        pattern = payload["pattern"]
        rows = self.dataset[self.dataset.pattern == pattern].sort_values("wavenumber")
        if rows.empty:
            raise ValueError("Choose a discovered pattern.")
        wn = integer(payload["wavenumber"], "Preview wavenumber")
        selected = rows[rows.wavenumber == wn]
        if selected.empty:
            raise ValueError("Choose a wavenumber available in this pattern.")
        image = load_qcl_csv(selected.iloc[0].path)
        height, width = image.shape
        common = {"pattern": pattern, "wavenumber": wn, "width": width,
                  "height": height, "version": self.version}
        if payload.get("mode") == "image":
            png, lo, hi = render_processing_png(image, payload)
            return {**common, "png": base64.b64encode(png).decode(), "vmin": lo, "vmax": hi}
        x, y = integer(payload["x"], "Pixel x"), integer(payload["y"], "Pixel y")
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("Pixel coordinates must be inside the full image.")
        points = []
        for row in rows.itertuples(index=False):
            array = image if row.wavenumber == wn else load_qcl_csv(row.path)
            if array.shape != image.shape:
                raise ValueError(f"Image shape differs at {row.wavenumber} cm^-1; a shared pixel spectrum requires matching image shapes.")
            points.append({"wavenumber": int(row.wavenumber), "raw_signal": float(array[y, x])})
        return {**common, "x": x, "y": y, "points": points,
                "missing_wavenumbers": sorted(set(int(v) for v in self.dataset.wavenumber) - set(int(v) for v in rows.wavenumber))}

    def raw_roi_spectrum(self, payload):
        """Average two full-image ROIs across all measured bands of a pattern."""
        self.require("discovered")
        pattern = payload["pattern"]
        rows = self.dataset[self.dataset.pattern == pattern].sort_values("wavenumber")
        if rows.empty:
            raise ValueError("Choose a discovered pattern.")
        wn = integer(payload["wavenumber"], "Preview wavenumber")
        if wn not in set(rows.wavenumber):
            raise ValueError("Choose a wavenumber available in this pattern.")
        rois = {name: roi_from(payload[name]) for name in ("analyte_roi", "background_roi")}
        points, shape = [], None
        for row in rows.itertuples(index=False):
            image = load_qcl_csv(row.path)
            if shape is not None and image.shape != shape:
                raise ValueError(f"Image shape differs at {row.wavenumber} cm^-1; shared ROIs require matching image shapes.")
            shape = image.shape
            means = []
            for roi in rois.values():
                values = crop_image(image, roi, copy=False)
                means.append(float(np.mean(values)) if np.isfinite(values).all() else None)
            signal, background = means
            valid = all(v is not None and np.isfinite(v) and v > 0 for v in means)
            ratio = signal / background if valid else None
            valid = valid and np.isfinite(ratio) and ratio > 0
            points.append({"wavenumber": int(row.wavenumber), "I": signal,
                           "I_bg": background, "ratio": ratio if valid else None,
                           "absorbance": float(-np.log10(ratio)) if valid else None,
                           "status": "valid" if valid else "Non-finite or non-positive ROI mean / ratio"})
        return {"pattern": pattern, "wavenumber": wn,
                **{name: asdict(roi) for name, roi in rois.items()},
                "analyte_pixels": (rois["analyte_roi"].x_max-rois["analyte_roi"].x_min)*(rois["analyte_roi"].y_max-rois["analyte_roi"].y_min),
                "background_pixels": (rois["background_roi"].x_max-rois["background_roi"].x_min)*(rois["background_roi"].y_max-rois["background_roi"].y_min),
                "points": points,
                "missing_wavenumbers": sorted(set(int(v) for v in self.dataset.wavenumber)-set(int(v) for v in rows.wavenumber))}

    def smooth_roi_spectrum(self, payload):
        """Smooth a uniformly sampled absorbance spectrum without altering raw data."""
        window = integer(payload["window"], "SG window")
        order = integer(payload["order"], "SG polynomial order")
        x = np.asarray(payload["wavenumbers"], dtype=float)
        y = np.asarray(payload["absorbance"], dtype=float)
        if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
            raise ValueError("SG requires matching one-dimensional wavenumbers and absorbance.")
        if window < 3 or window % 2 != 1 or window > y.size:
            raise ValueError("SG window must be odd, at least 3, and no larger than the measured band count.")
        if order < 0 or order >= window:
            raise ValueError("SG polynomial order must be non-negative and smaller than the window.")
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("SG requires finite absorbance at every band; invalid bands cannot be smoothed.")
        spacing = np.diff(x)
        if not (spacing > 0).all() or not np.allclose(spacing, spacing[0], rtol=1e-7, atol=1e-9):
            raise ValueError("SG requires evenly spaced measured wavenumbers; missing or uneven bands are not interpolated.")
        return {"window": window, "order": order,
                "absorbance_sg": savgol_filter(y, window, order, mode="interp").tolist()}

    def filter_roi_spectrum(self, payload):
        """Apply optional reflected-padding Fourier filtering, followed by optional SG."""
        x = np.asarray(payload["wavenumbers"], dtype=float)
        y = np.asarray(payload["absorbance"], dtype=float)
        fourier = bool(payload.get("fourier_enabled", False))
        sg = bool(payload.get("sg_enabled", False))
        if x.ndim != 1 or y.ndim != 1 or x.size != y.size or y.size < 3:
            raise ValueError("Filtering requires at least three matching spectral samples.")
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Filtering requires finite absorbance at every band.")
        spacing = np.diff(x)
        if not (spacing > 0).all() or not np.allclose(spacing, spacing[0], rtol=1e-7, atol=1e-9):
            raise ValueError("Filtering requires evenly spaced measured wavenumbers; missing bands are not interpolated.")
        output = y.copy()
        result = {"fourier_enabled": fourier, "sg_enabled": sg}
        if fourier:
            mode = payload.get("fourier_mode", "lowpass")
            if mode not in {"lowpass", "notch", "combined"}:
                raise ValueError("Choose lowpass, notch, or combined Fourier filtering.")
            cutoff, centers, width, rejected = None, [], None, []
            if mode in {"lowpass", "combined"}:
                cutoff = float(payload.get("cutoff", 0.1))
                if not np.isfinite(cutoff) or not 0 < cutoff <= 0.5:
                    raise ValueError("Fourier cutoff must be greater than 0 and at most 0.5 cycles/band.")
                rejected.append([cutoff, 0.5])
            if mode in {"notch", "combined"}:
                centers = np.asarray(payload.get("notch_centers", []), dtype=float)
                width = float(payload.get("notch_width", 0.02))
                if centers.ndim != 1 or not centers.size or not np.isfinite(centers).all() or not ((centers > 0) & (centers <= 0.5)).all():
                    raise ValueError("Enter at least one notch frequency greater than 0 and at most 0.5 cycles/band.")
                if not np.isfinite(width) or not 0 < width <= 1:
                    raise ValueError("Notch full width must be greater than 0 and at most 1 cycle/band.")
                centers = sorted(set(centers.tolist()))
                rejected.extend([[max(0., c-width/2), min(0.5, c+width/2)] for c in centers])
            pad = y.size - 1
            padded = np.pad(y, pad, mode="reflect")
            coefficients = np.fft.rfft(padded)
            frequency = np.fft.rfftfreq(padded.size)
            mask = np.ones(frequency.shape, dtype=bool)
            if cutoff is not None:
                mask &= frequency <= cutoff
            for center in centers:
                mask &= ~((np.abs(frequency-center) <= width/2) & (frequency > 0))
            filtered = coefficients * mask
            output = np.fft.irfft(filtered, n=padded.size)[pad:pad+y.size]
            amplitude = np.abs(coefficients) / padded.size
            result.update({"cutoff": cutoff, "padding": pad, "fourier_mode": mode,
                           "notch_centers": centers, "notch_width": width,
                           "rejected_ranges": rejected,
                           "removed_bins": int(np.count_nonzero(~mask)),
                           "absorbance_fourier": output.tolist(),
                           "fourier_removed": (y-output).tolist(),
                           "frequency": frequency.tolist(),
                           "fft_before": amplitude.tolist(),
                           "fft_after": (amplitude*mask).tolist(),
                           "fft_removed": (amplitude*(~mask)).tolist(),
                           "mask": mask.astype(int).tolist()})
        if sg:
            smoothed = self.smooth_roi_spectrum({**payload, "absorbance": output.tolist()})
            result.update(smoothed)
            output = np.asarray(smoothed["absorbance_sg"])
        result["absorbance_filtered"] = output.tolist()
        return result

    def configure(self, payload):
        self.require("discovered")
        mapping = {}
        available = set(self.dataset.wavenumber)
        for center, refs in payload.get("mapping", {}).items():
            center = integer(center, "Center")
            refs = [integer(v, "Reference") for v in refs]
            if center not in available or not set(refs) <= available:
                raise ValueError(
                    "Every center and reference must be an identified filename wavenumber."
                )
            if len(refs) < 2 or len(refs) != len(set(refs)) or center in refs:
                raise ValueError(
                    f"Center {center} needs at least two distinct references, excluding itself."
                )
            if not min(refs) < center < max(refs):
                raise ValueError(
                    f"References must bracket center {center}; extrapolation is disabled."
                )
            mapping[center] = sorted(refs)
        if not mapping:
            raise ValueError(
                "Select at least one center and its baseline reference bands."
            )
        patterns = list(dict.fromkeys(payload.get("patterns", [])))
        if not patterns or not set(patterns) <= set(self.dataset.pattern):
            raise ValueError("Select one or more discovered patterns.")
        bands = sorted(set(mapping) | {v for refs in mapping.values() for v in refs})
        selected = self.dataset[
            self.dataset.pattern.isin(patterns) & self.dataset.wavenumber.isin(bands)
        ].copy()
        for pattern in patterns:
            missing = set(bands) - set(selected[selected.pattern == pattern].wavenumber)
            if missing:
                raise ValueError(
                    f"{pattern} is missing required bands: {sorted(missing)}"
                )
        raw = {}
        for row in selected.itertuples(index=False):
            image = load_qcl_csv(row.path)
            key = (row.pattern, int(row.wavenumber))
            raw[key] = image
        if len({a.shape for a in raw.values()}) != 1:
            raise ValueError(
                "All selected images must have the same spatial shape. Registration is not performed."
            )
        self.reset_analysis()
        self.mapping, self.patterns, self.bands = mapping, patterns, bands
        self.raw, self.qc = raw, selected
        self.stage = "configured"
        self.version += 1
        return {
            **self.status(),
            "shape": list(next(iter(raw.values())).shape),
            "qc": selected.drop(columns="path").to_dict(orient="records"),
        }

    def normalize(self, payload):
        """Commit either per-image gold normalization or the unchanged raw path."""
        self.require("configured")
        has_gold = payload.get("has_gold")
        if not isinstance(has_gold, bool):
            raise ValueError("Specify whether a gold patch reference is available.")
        selected = self.dataset[self.dataset.pattern.isin(self.patterns) & self.dataset.wavenumber.isin(self.bands)].copy()
        ref, pixels, signals = {}, {}, []
        n_pixels = integer(payload.get("n_pixels", 100), "Brightest pixels") if has_gold else 0
        qc_settings = {}
        if has_gold:
            for row in selected.itertuples(index=False):
                key = (row.pattern, int(row.wavenumber))
                yy, xx, values = get_brightest_pixel_indices(self.raw[key], n_pixels)
                gold = float(np.mean(values))
                if not np.isfinite(gold) or gold <= 0:
                    raise ValueError("Gold-reference signal must be finite and positive.")
                ref[key] = self.raw[key] / gold
                pixels[key] = np.column_stack((yy, xx))
                signals.append(gold)
            selected["i_goldref"] = signals
            selected["gold_reference_n_pixels"] = n_pixels
            qc_settings = {"robust_z_threshold": float(payload.get("robust_z_threshold", 5)),
                           "min_relative_deviation": float(payload.get("relative_threshold", .1))}
            selected = add_reference_quality_flags(selected, **qc_settings)
            selected = add_frame_quality_flags(selected, expected_wavenumbers=set(self.bands))
        else:
            selected["i_goldref"] = np.nan
            selected["gold_reference_n_pixels"] = 0
            selected["reference_valid"] = None
            selected["frame_valid"] = selected.pattern.map({
                p: all(np.isfinite(a).all() for (pattern, _), a in self.raw.items() if pattern == p)
                for p in self.patterns})
        selected["reflectance_calculated"] = has_gold
        self.ref, self.gold_pixels, self.has_gold = ref, pixels, has_gold
        self.n_pixels, self.qc, self.qc_settings = n_pixels, selected, qc_settings
        self.on_roi, self.on_rois, self.drift, self.crops = None, {}, {}, {}
        self.clear_processed()
        self.last_video = None
        self.stage = "referenced"
        self.version += 1
        return {**self.status(), "qc": selected.drop(columns="path").to_dict(orient="records")}

    def processing_images(self):
        self.require("referenced")
        return self.ref if self.has_gold else self.raw

    def crop_plan(self, payload):
        """Preview exactly the crop coordinates later used by every stage."""
        self.require("referenced")
        images = self.processing_images()
        roi = roi_from(payload["roi"])
        drift = payload.get("drift", {})
        rois = {pattern: roi for pattern in self.patterns}
        records = []
        if drift.get("enabled", False):
            if not self.has_gold:
                raise ValueError("Gold drift tracking requires a gold patch reference.")
            pattern = drift["reference_pattern"]
            wn = integer(drift["wavenumber"], "Drift reference wavenumber")
            if pattern not in self.patterns or wn not in self.bands:
                raise ValueError("Choose a configured drift reference pattern and band.")
            rois, records = gold_drift_rois(
                {p: images[(p, wn)] for p in self.patterns}, pattern, roi,
                drift.get("side", "both"), integer(drift.get("max_shift", 20), "Maximum drift")
            )
        for key, image in images.items():
            crop_image(image, rois[key[0]], copy=False)
        return {"rois": {p: asdict(r) for p, r in rois.items()}, "records": records}

    def crop(self, payload):
        plan = self.crop_plan(payload)
        roi = roi_from(payload["roi"])
        rois = {p: roi_from(r) for p, r in plan["rois"].items()}
        crops = {key: crop_image(a, rois[key[0]]) for key, a in self.processing_images().items()}
        if min(next(iter(crops.values())).shape) < 2:
            raise ValueError("The on-MS crop must be at least 2 × 2 pixels.")
        self.on_roi, self.on_rois, self.crops = roi, rois, crops
        self.drift = {"settings": payload.get("drift", {}), "records": plan["records"]}
        self.clear_processed()
        self.stage = "cropped"
        self.version += 1
        return {**self.status(), **plan, "shape": list(next(iter(crops.values())).shape)}

    @staticmethod
    def process_image(image, payload):
        """Run enabled stages identically for preview and committed batch results."""
        f = payload["fourier"]
        r = payload["rolling"]
        mode = f.get("mode", "notch") if f.get("enabled", True) else "none"
        allowed_f = {
            "enabled",
            "mode",
            "centers",
            "sigma",
            "sigma_x",
            "sigma_y",
            "strength",
            "protect_radius",
            "cutoff_x",
            "cutoff_y",
            "pad_pixels",
            "preserve_mean",
        }
        allowed_r = {
            "enabled",
            "radius",
            "kernel_height",
            "feature_polarity",
            "smooth_sigma",
            "pad_pixels",
            "min_background",
            "reference_level",
        }
        if set(f) - allowed_f or set(r) - allowed_r:
            raise ValueError("Unknown processing parameter.")
        if mode not in {"notch", "lowpass", "combined", "none"}:
            raise ValueError("Choose notch, lowpass, combined or none.")
        shared = {
            "pad_pixels": integer(f.get("pad_pixels", 0), "Fourier padding"),
            "preserve_mean": bool(f.get("preserve_mean", True)),
        }
        if mode == "none":
            spectrum, fy, fx = fourier_spectrum(image)
            output = FourierFilterResult(
                image.copy(),
                np.zeros_like(image),
                np.ones_like(image),
                spectrum,
                spectrum.copy(),
                fy,
                fx,
            )
        elif mode == "combined":
            output = apply_fourier_combined_filter(
                image, f.get("centers", []),
                sigma=float(f.get("sigma", 0.01)),
                sigma_x=float(f.get("sigma_x", f.get("sigma", 0.01))),
                sigma_y=float(f.get("sigma_y", f.get("sigma", 0.01))),
                strength=float(f.get("strength", 0.9)),
                protect_radius=float(f.get("protect_radius", 0.02)),
                cutoff_x=float(f.get("cutoff_x", 0.15)),
                cutoff_y=float(f.get("cutoff_y", 0.15)), **shared)
        elif mode == "lowpass":
            output = apply_fourier_lowpass_filter(
                image,
                cutoff_x=float(f.get("cutoff_x", 0.15)),
                cutoff_y=float(f.get("cutoff_y", 0.15)),
                **shared,
            )
        else:
            output = apply_fourier_notch_filter(
                image,
                f.get("centers", []) if mode == "notch" else [],
                sigma=float(f.get("sigma", 0.01)),
                sigma_x=float(f.get("sigma_x", f.get("sigma", 0.01))),
                sigma_y=float(f.get("sigma_y", f.get("sigma", 0.01))),
                strength=float(f.get("strength", 0.9)),
                protect_radius=float(f.get("protect_radius", 0.02)),
                **shared,
            )
        if not r.get("enabled", True):
            # Identity field: disabling rolling ball preserves every input value.
            ones = np.ones_like(output.filtered)
            flat_output = FlatFieldResult(
                output.filtered.copy(),
                ones,
                ones.copy(),
                np.isfinite(output.filtered),
                np.zeros_like(output.filtered),
                1.0,
            )
            return output, flat_output
        flat_output = rolling_ball_flat_field(
            output.filtered,
            radius=integer(r.get("radius", 30), "Rolling-ball radius"),
            kernel_height=float(r.get("kernel_height", 0.05)),
            feature_polarity=r.get("feature_polarity", "dark"),
            smooth_sigma=float(r.get("smooth_sigma", 1)),
            pad_pixels=integer(r.get("pad_pixels", 0), "Rolling padding"),
            min_background=float(r.get("min_background", 1e-6)),
            reference_level=r.get("reference_level"),
        )
        return output, flat_output

    def preview(self, payload):
        """Preview only the selected crop without changing committed processing state."""
        self.require("cropped")
        key = (payload["pattern"], integer(payload["wavenumber"], "Wavenumber"))
        image = self.crops[key]
        output, flat = self.process_image(image, payload)
        arrays = [image, output.filtered, flat.corrected]
        low, high = float(payload.get("low", 0)), float(payload.get("high", 100))
        if not 0 <= low < high <= 100:
            raise ValueError("Display percentiles must satisfy 0 <= low < high <= 100.")
        limits = self.limits(arrays, low, high)
        cards = []
        for title, array in zip(
            ("Before processing", "After Fourier", "After rolling ball"), arrays
        ):
            card_payload = {**payload, "colorbar_zero": title in payload["colorbar_zero_titles"]} if "colorbar_zero_titles" in payload else payload
            png, lo, hi = render_processing_png(array, card_payload, limits=limits)
            cards.append(
                {
                    "title": title,
                    "png": base64.b64encode(png).decode(),
                    "vmin": lo,
                    "vmax": hi,
                }
            )
        # Use the actual padded filtering spectra, not the Hann inspection FFT.
        before = np.log1p(np.abs(output.spectrum_before))
        after = np.log1p(np.abs(output.spectrum_after))
        fft_limits = (0.0, max(float(before.max()), float(after.max()), 1e-12))
        axes = (
            f"fx: {output.fx[0]:.4f} to {output.fx[-1]:.4f}; "
            f"fy: {output.fy[0]:.4f} (top) to {output.fy[-1]:.4f} (bottom), cycles/pixel"
        )
        diagnostics = []

        def diagnostic(title, array, scale, caption, available=True):
            if not available:
                diagnostics.append(
                    {
                        "title": title,
                        "available": False,
                        "caption": "Rolling ball is bypassed; no background was estimated.",
                    }
                )
                return
            card_payload = {**payload, "colorbar_zero": title in payload["colorbar_zero_titles"]} if "colorbar_zero_titles" in payload else payload
            png, lo, hi = render_processing_png(array, card_payload, limits=scale)
            diagnostics.append(
                {
                    "title": title,
                    "available": True,
                    "png": base64.b64encode(png).decode(),
                    "vmin": lo,
                    "vmax": hi,
                    "caption": caption,
                }
            )

        diagnostic(
            "FFT before filtering",
            before,
            fft_limits,
            "log(1 + FFT amplitude). Actual filtering FFT; no Hann window. " + axes,
        )
        diagnostic(
            "Fourier transmission mask",
            output.mask,
            (0.0, 1.0),
            "Transmission: 0 = rejected, 1 = retained. " + axes,
        )
        diagnostic(
            "FFT after filtering",
            after,
            fft_limits,
            "log(1 + FFT amplitude). Same scale as the input FFT. " + axes,
        )
        removed_bound = max(float(np.max(np.abs(output.removed))), 1e-12)
        diagnostic(
            "Signal removed by Fourier: input − filtered",
            output.removed,
            (-removed_bound, removed_bound),
            "Signed signal removed by the current Fourier filter. Updates when notches or widths change; combined mode includes low-pass removal. May include specimen detail.",
        )
        enabled = bool(payload["rolling"].get("enabled", True))
        diagnostic(
            "Estimated rolling-ball background",
            flat.background,
            self.limits([output.filtered, flat.background], low, high),
            "Estimated illumination field (input signal units). Correction divides by this field and rescales; it is not subtracted.",
            enabled,
        )
        diagnostic(
            "Rolling-ball correction gain",
            flat.gain,
            self.limits([flat.gain], low, high),
            "Gain = reference level / background. Corrected signal = input signal × gain.",
            enabled,
        )
        removed = output.filtered - flat.corrected
        finite = removed[np.isfinite(removed)]
        bound = max(float(np.max(np.abs(finite))) if finite.size else 0.0, 1e-12)
        diagnostic(
            "Rolling-ball difference: input − corrected",
            removed,
            (-bound, bound),
            "Signed change in signal, distinct from the estimated illumination background.",
        )
        return {
            "images": cards,
            "diagnostics": diagnostics,
            "version": self.version,
            "invalid_pixels": int((~flat.valid_mask).sum()),
        }

    def processing_progress(self):
        """Read progress without acquiring the long-running analysis lock."""
        with self.progress_lock:
            result = dict(self.progress)
        started = result.pop("started", None)
        ended = result.pop("ended", None)
        result["elapsed_seconds"] = (ended or time.monotonic()) - started if started else 0
        return result

    def set_progress(self, **values):
        with self.progress_lock:
            self.progress.update(values)

    def process(self, payload):
        self.set_progress(status="running", completed=0, total=len(self.crops),
                          pattern=None, wavenumber=None, started=time.monotonic(), ended=None)
        try:
            result = self._process_batch(payload)
        except Exception:
            self.set_progress(status="failed", ended=time.monotonic())
            raise
        self.set_progress(status="complete", ended=time.monotonic())
        return result

    def _process_batch(self, payload):
        self.require("cropped")
        f, r = payload["fourier"], payload["rolling"]
        ff, flat = {}, {}
        for index, (key, image) in enumerate(self.crops.items()):
            self.set_progress(pattern=key[0], wavenumber=key[1])
            ff[key], flat[key] = self.process_image(image, payload)
            self.set_progress(completed=index + 1)
        self.ff, self.flat = ff, flat
        self.parameters = json.loads(json.dumps({"fourier": f, "rolling": r}))
        self.clear_absorbance()
        self.stage = "processed"
        self.version += 1
        return {
            **self.status(),
            "summary": [
                {
                    "pattern": k[0],
                    "wavenumber": k[1],
                    "invalid_pixels": int((~v.valid_mask).sum()),
                    "flat_reference": v.reference_level,
                }
                for k, v in flat.items()
            ],
        }

    def calculate(self, payload):
        self.require("processed")
        method = payload.get("method", "roi")
        if method not in {"roi", "brightest", "darkest"}:
            raise ValueError("Unknown analyte-free reference method.")
        roi = roi_from(payload["roi"]) if method == "roi" else None
        count = integer(payload.get("count", 1), "Analyte-free pixel count") if method != "roi" else None
        absorbance, baselines, records = {}, {}, []
        selections = {}
        reference_bands = {}
        pattern_pixels = {}
        search_roi = roi_from(payload["search_roi"]) if payload.get("search_roi") else None
        if method != "roi":
            requested = payload.get("reference_bands", {})
            for pattern in self.patterns:
                wn = integer(requested.get(pattern, self.bands[0]), "Reference wavenumber")
                if (pattern, wn) not in self.flat:
                    raise ValueError(f"Choose a processed reference wavenumber for {pattern}.")
                reference_bands[pattern] = wn
                pattern_pixels[pattern] = select_cell_free_pixels(
                    self.flat[(pattern, wn)].corrected, method, count, search_roi
                )
        for key, flat in self.flat.items():
            if method == "roi":
                reference = crop_image(flat.corrected, roi)
                yy, xx = np.mgrid[roi.y_min : roi.y_max, roi.x_min : roi.x_max]
                pixels = np.column_stack((yy.ravel(), xx.ravel()))
            else:
                pixels = pattern_pixels[key[0]]
                reference = flat.corrected[pixels[:, 0], pixels[:, 1]]
            if not np.isfinite(reference).all() or (reference <= 0).any():
                raise ValueError(
                    f"Analyte-free selection contains invalid signal at {key}. Select another reference."
                )
            r0 = float(np.mean(reference))
            a = calculate_absorbance(flat.corrected, r0)
            absorbance[key] = a
            selections[key] = pixels
            records.append(
                {
                    "pattern": key[0],
                    "wavenumber": key[1],
                    "method": method,
                    "reference_wavenumber": reference_bands.get(key[0]),
                    "pixel_count": int(pixels.shape[0]),
                    "r0": r0,
                    "reference_mean_absorbance": float(
                        np.mean(a[pixels[:, 0], pixels[:, 1]])
                    ),
                }
            )
        self.r0_roi, self.r0_selection, self.r0_pixels = (
            roi,
            {"method": method, **({"count": count, "reference_bands": reference_bands} if count is not None else {})},
            selections,
        )
        if search_roi is not None and method != "roi":
            self.r0_selection["search_roi"] = asdict(search_roi)
        self.absorbance, self.baselines, self.r0_records = (
            absorbance,
            baselines,
            records,
        )
        self.cnr_records, self.cnr_rois = [], None
        self.stage = "absorbed"
        self.version += 1
        return {**self.status(), "r0": records}

    def correct_baseline(self, payload):
        """Commit baseline correction separately from absorbance calculation."""
        self.require("absorbed")
        baselines = {}
        for pattern in self.patterns:
            results = correct_absorbance_baselines(
                {wn: self.absorbance[(pattern, wn)] for wn in self.bands}, self.mapping
            )
            baselines.update(
                {(pattern, int(wn)): result for wn, result in results.items()}
            )
        self.baselines = baselines
        self.cnr_records, self.cnr_rois = [], None
        self.stage = "complete"
        self.version += 1
        return self.status()

    def baseline_pixel(self, payload):
        """Inspect the committed baseline fit at a crop-local pixel."""
        self.require("complete")
        pattern = payload["pattern"]
        center = integer(payload["wavenumber"], "Center wavenumber")
        key = (pattern, center)
        if key not in self.baselines:
            raise ValueError("Choose a processed pattern and configured center wavenumber.")
        x, y = integer(payload["x"], "Pixel x"), integer(payload["y"], "Pixel y")
        result = self.baselines[key]
        height, width = result.corrected.shape
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("Pixel coordinates must be inside the on-MS crop.")
        refs = self.mapping[center]
        slope = float(result.slope[y, x])
        baseline = float(result.baseline[y, x])
        points = [
            {"wavenumber": wn, "absorbance": float(self.absorbance[(pattern, wn)][y, x]),
             "fitted": baseline + slope * (wn - center)}
            for wn in refs
        ]
        valid = bool(result.valid_mask[y, x])
        return {
            "pattern": pattern, "wavenumber": center, "x": x, "y": y,
            "version": self.version, "references": points,
            "slope": slope, "baseline": baseline,
            "before": float(self.absorbance[key][y, x]),
            "after": float(result.corrected[y, x]), "valid": valid,
            "method": "Two-reference linear interpolation" if len(refs) == 2
                      else "Unweighted linear least-squares fit",
            "status": "Valid" if valid else "Invalid center or reference absorbance; no corrected value is available.",
        }

    def stage_arrays(self, key):
        self.require("cropped")
        return {
            "raw": crop_image(self.raw[key], self.on_rois[key[0]]),
            "reflectance": self.crops[key] if self.has_gold else None,
            "fourier": self.ff[key].filtered if key in self.ff else None,
            "rolling": self.flat[key].corrected if key in self.flat else None,
            "absorbance": self.absorbance.get(key),
            "baseline": self.baselines[key].corrected
            if key in self.baselines
            else None,
        }

    def cnr(self, payload):
        self.require("complete")
        bg, target = roi_from(payload["background"]), roi_from(payload["target"])
        low, high = float(payload.get("low", 0)), float(payload.get("high", 100))
        if not 0 <= low < high <= 100:
            raise ValueError("CNR percentiles must satisfy 0 <= low < high <= 100.")
        rows = []
        for key in self.crops:
            arrays = self.stage_arrays(key)
            bounds = {name: self.stage_display_limits(arrays, name, low, high)
                      for name, array in arrays.items() if array is not None}
            # Preserve NaN/Inf so clipping cannot make an invalid pixel valid.
            adjusted = {name: None if array is None else
                        np.where(np.isfinite(array), np.clip(array, *bounds[name]), array)
                        for name, array in arrays.items()}
            original = {r["stage"]: r for r in compare_stage_cnr(arrays, bg, target)}
            for r in compare_stage_cnr(adjusted, bg, target):
                limits = bounds.get(r["stage"], (None, None))
                rows.append({"pattern": key[0], "wavenumber": key[1], **r,
                             "cnr_unadjusted": original[r["stage"]]["cnr"],
                             "unadjusted_status": original[r["stage"]]["status"],
                             "contrast_adjusted": low != 0 or high != 100,
                             "contrast_low_percentile": low, "contrast_high_percentile": high,
                             "contrast_vmin": limits[0], "contrast_vmax": limits[1],
                             "contrast_method": "clip_to_display_limits"})
        self.cnr_records, self.cnr_rois = (
            rows,
            {"background": asdict(bg), "target": asdict(target)},
        )
        return {"records": rows, "rois": self.cnr_rois}

    def stage_display_limits(self, arrays, kind, low, high):
        signal = ("reflectance", "fourier", "rolling") if self.has_gold else ("raw", "fourier", "rolling")
        group = signal if kind in signal else ("absorbance", "baseline") if kind in {"absorbance", "baseline"} else (kind,)
        return self.limits([arrays[name] for name in group], low, high)

    @staticmethod
    def limits(arrays, low=0, high=100):
        values = np.concatenate([a[np.isfinite(a)] for a in arrays if a is not None])
        if not values.size:
            return (0.0, 1.0)
        lo, hi = np.percentile(values, [low, high])
        return (float(lo), float(max(hi, lo + 1e-12)))

    def image(self, payload):
        self.require("configured")
        key = (payload["pattern"], integer(payload["wavenumber"], "Wavenumber"))
        if key not in self.raw:
            raise ValueError("Choose a configured pattern and wavenumber.")
        kind = payload.get("kind", "full_reflectance" if self.has_gold else "full_raw")
        low, high = float(payload.get("low", 0)), float(payload.get("high", 100))
        if not 0 <= low < high <= 100:
            raise ValueError("Display percentiles must satisfy 0 <= low < high <= 100.")
        extra = {}
        limits = None
        if kind == "full_reflectance":
            if key not in self.ref:
                return {"available": False, "reason": "Reflectance was not calculated. The processing input is raw intensity."}
            array = self.ref[key]
        elif kind == "full_raw":
            array = self.raw[key]
            if self.has_gold and key in self.gold_pixels:
                extra["gold_pixels"] = self.gold_pixels[key].tolist()
                extra["i_goldref"] = float(array[self.gold_pixels[key][:, 0], self.gold_pixels[key][:, 1]].mean())
        elif kind == "spectrum":
            self.require("cropped")
            spectrum, fy, fx = fourier_spectrum(
                self.crops[key], window=payload.get("window", "true") == "true"
            )
            array = np.log1p(np.abs(spectrum))
            extra = {"fy": fy.tolist(), "fx": fx.tolist()}
            minimum = float(payload.get("min_frequency", 0.025))
            if not 0 <= minimum < 0.5:
                raise ValueError("Candidate minimum frequency must be in [0, 0.5).")
            amplitude = np.abs(spectrum)
            FY, FX = np.meshgrid(fy, fx, indexing="ij")
            # Match notebook 06: local maxima, one half-plane, exclude the center.
            candidates = (
                (amplitude == maximum_filter(amplitude, size=5, mode="wrap"))
                & (amplitude > 0)
                & (np.hypot(FY, FX) > minimum)
                & ((FY > 0) | ((FY == 0) & (FX > 0)))
            )
            positions = np.argwhere(candidates)
            order = np.argsort(-amplitude[candidates], kind="stable")[:10]
            extra["peaks"] = [
                {
                    "rank": rank,
                    "iy": int(iy),
                    "ix": int(ix),
                    "fy": float(fy[iy]),
                    "fx": float(fx[ix]),
                    "period_pixels": float(1 / np.hypot(fy[iy], fx[ix])),
                    "amplitude": float(amplitude[iy, ix]),
                }
                for rank, (iy, ix) in enumerate(positions[order], 1)
            ]
        elif kind in {"mask", "background", "gain"}:
            self.require("processed")
            array = {
                "mask": self.ff[key].mask,
                "background": self.flat[key].background,
                "gain": self.flat[key].gain,
            }[kind]
        elif kind == "linear_baseline":
            self.require("complete")
            if key not in self.baselines:
                return {"available": False}
            array = self.baselines[key].baseline
        else:
            arrays = self.stage_arrays(key)
            if kind not in arrays:
                raise ValueError("Unknown image stage.")
            array = arrays[kind]
            if array is None:
                return {"available": False}
            limits = self.stage_display_limits(arrays, kind, low, high)
        if kind == "rolling" and payload.get("r0_method") in {
            "brightest",
            "darkest",
        }:
            wn = integer(payload.get("r0_reference_band", self.bands[0]), "Reference wavenumber")
            if (key[0], wn) not in self.flat:
                raise ValueError("Choose a processed reference wavenumber.")
            pixels = select_cell_free_pixels(
                self.flat[(key[0], wn)].corrected,
                payload["r0_method"], payload.get("r0_count", 1),
                roi_from(json.loads(payload["r0_search_roi"])) if payload.get("r0_search_roi") else None
            )
            extra["reference_wavenumber"] = wn
            reference = array[pixels[:, 0], pixels[:, 1]]
            if not np.isfinite(reference).all() or (reference <= 0).any():
                raise ValueError("Selected reference positions contain invalid signal in this band.")
            extra["cell_free_pixels"] = pixels.tolist()
            extra["cell_free_r0"] = float(
                np.mean(array[pixels[:, 0], pixels[:, 1]])
            )
        png, lo, hi = render_processing_png(
            array, payload,
            low=low,
            high=high,
            limits=limits,
        )
        return {
            "available": True,
            "png": base64.b64encode(png).decode(),
            "width": array.shape[1],
            "height": array.shape[0],
            "vmin": lo,
            "vmax": hi,
            "kind": kind,
            **extra,
        }

    def timelapse(self, payload):
        self.require("complete")
        wn = integer(payload["wavenumber"], "Wavenumber")
        kind = payload.get("kind", "baseline")
        if kind not in STAGES:
            raise ValueError("Unknown timelapse stage.")
        if kind == "reflectance" and not self.has_gold:
            raise ValueError("Reflectance was skipped; choose a raw-intensity stage.")
        start, end = int(payload.get("start", 0)), int(payload.get("end", 10**12))
        if start > end:
            raise ValueError("Start pattern must not exceed end pattern.")
        rows = self.qc[
            (self.qc.wavenumber == wn)
            & (self.qc.frame >= start)
            & (self.qc.frame <= end)
        ]
        if payload.get("skip_invalid"):
            rows = rows[rows.frame_valid]
        rows = rows.sort_values("frame")
        frames = []
        arrays = []
        for row in rows.itertuples(index=False):
            a = self.stage_arrays((row.pattern, wn))[kind]
            if a is not None:
                arrays.append(a)
                frames.append(
                    {
                        "pattern": row.pattern,
                        "timestamp": row.created_timestamp,
                        "timestamp_source": row.timestamp_source,
                        "valid": bool(row.frame_valid),
                    }
                )
        if not frames:
            raise ValueError("No processed frames are available for this selection.")
        low, high = float(payload.get("low", 0)), float(payload.get("high", 100))
        if not 0 <= low < high <= 100:
            raise ValueError("Contrast percentiles must satisfy 0 <= low < high <= 100.")
        limits = display_limits(self.limits(arrays, low, high), payload)
        for f, a in zip(frames, arrays):
            png, _, _ = render_data_png(a, limits=limits)
            f["png"] = base64.b64encode(png).decode()
            f["elapsed_seconds"] = f["timestamp"] - frames[0]["timestamp"]
        extrema = []
        for frame, array in zip(frames, arrays):
            finite = array[np.isfinite(array)]
            if finite.size:
                extrema.append((frame['pattern'], float(finite.min()), float(finite.max())))
        if extrema:
            minimum = min(row[1] for row in extrema)
            maximum = max(row[2] for row in extrema)
            min_patterns = ', '.join(row[0] for row in extrema if row[1] == minimum)
            max_patterns = ', '.join(row[0] for row in extrema if row[2] == maximum)
            extrema_label = f"Data extrema · Max value {maximum:.4f}: {max_patterns} · Min value {minimum:.4f}: {min_patterns}"
        else:
            extrema_label = "Data extrema: no finite values"
        self.last_video = {
            "colorbar_zero": payload.get("colorbar_zero") in (True, "true", "1"),
            "processing_basis": "reflectance" if self.has_gold else "raw_intensity",
            "extrema_label": extrema_label,
            "video_id": uuid.uuid4().hex,
            "version": self.version,
            "frames": frames,
            "wavenumber": wn,
            "kind": kind,
            "low": low,
            "high": high,
            "vmin": limits[0],
            "vmax": limits[1],
            "median_interval_seconds": float(
                np.median(np.diff([f["timestamp"] for f in frames]))
            )
            if len(frames) > 1
            else 0,
        }
        return self.last_video

    def export(self):
        self.require("complete")
        buffer = io.BytesIO()
        metadata = {
            "source": str(self.path),
            "has_gold_patch_reference": self.has_gold,
            "processing_basis": "reflectance" if self.has_gold else "raw_intensity",
            "normalization_formula": "R = I_raw / mean(brightest N raw pixels per image)" if self.has_gold else None,
            "absorbance_formula": "-log10(corrected signal / mean(analyte-free corrected signal))",
            "centers_and_references": self.mapping,
            "patterns": self.patterns,
            "processed_wavenumbers": self.bands,
            "n_reference_pixels": self.n_pixels,
            "on_ms_roi": asdict(self.on_roi),
            "on_ms_rois_by_pattern": {p: asdict(r) for p, r in self.on_rois.items()},
            "drift_correction": self.drift,
            "cell_free_roi_local": asdict(self.r0_roi) if self.r0_roi else None,
            "cell_free_selection": self.r0_selection,
            "roi_coordinates": "half-open pixel coordinates; analyte-free and CNR ROIs local to on-MS crop",
            "processing": self.parameters,
            "qc_settings": self.qc_settings,
            "r0": self.r0_records,
            "baseline_method": "pixelwise unweighted linear least squares; two references give interpolation",
            "cnr_rois": self.cnr_rois,
            "cnr_formula": "abs(mean(target)-mean(background))/std(background,ddof=1)",
            "cnr_contrast": {
                "method": "clip_to_display_limits; no RGB conversion or quantization",
                "scope": "Percentiles apply to all selected patterns/bands; bounds match each stage's displayed shared scale.",
                "default": "0–100: no clipping of finite values",
                "interpretation": "Display-adjusted CNR; clipping can reduce background noise and inflate CNR.",
                "records": self.cnr_records,
            },
            "timestamp": datetime.now().astimezone().isoformat(),
            "flat_reference_levels": [
                {"pattern": k[0], "wavenumber": k[1], "level": f.reference_level}
                for k, f in self.flat.items()
            ],
        }
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "metadata.json",
                json.dumps(clean_json(metadata), indent=2, allow_nan=False),
            )
            z.writestr("quality_control.csv", self.qc.to_csv(index=False))
            z.writestr(
                "r0_summary.csv", pd.DataFrame(self.r0_records).to_csv(index=False)
            )
            if self.cnr_records:
                z.writestr(
                    "cnr_summary.csv",
                    pd.DataFrame(self.cnr_records).to_csv(index=False),
                )
            for key in self.crops:
                folder = f"{key[0]}/{key[1]}cm-1"
                arrays = self.stage_arrays(key)
                if self.has_gold:
                    gold_coordinates = io.StringIO()
                    np.savetxt(gold_coordinates, self.gold_pixels[key], fmt="%d", delimiter=",", header="y_full_raw,x_full_raw", comments="")
                    z.writestr(f"{folder}/gold_reference_pixels.csv", gold_coordinates.getvalue())
                arrays.update(
                    {
                        "fourier_mask": self.ff[key].mask,
                        "background": self.flat[key].background,
                        "gain": self.flat[key].gain,
                        "flat_valid_mask": self.flat[key].valid_mask.astype(int),
                        "cell_free_pixel_mask": np.zeros(
                            self.crops[key].shape, dtype=int
                        ),
                    }
                )
                pixels = self.r0_pixels[key]
                arrays["cell_free_pixel_mask"][pixels[:, 0], pixels[:, 1]] = 1
                coordinates = io.StringIO()
                np.savetxt(
                    coordinates,
                    pixels,
                    fmt="%d",
                    delimiter=",",
                    header="y,x",
                    comments="",
                )
                z.writestr(f"{folder}/cell_free_pixels.csv", coordinates.getvalue())
                if key in self.baselines:
                    arrays["linear_baseline"] = self.baselines[key].baseline
                    arrays["baseline_valid_mask"] = self.baselines[
                        key
                    ].valid_mask.astype(int)
                for name, array in arrays.items():
                    if array is not None:
                        output = io.StringIO()
                        np.savetxt(output, array, delimiter=",")
                        z.writestr(f"{folder}/{name}.csv", output.getvalue())
        return buffer.getvalue()


STATE = ProcessingState()


class ComparisonSession:
    """Independent datasets, addressed explicitly; the original session is retained."""

    def __init__(self):
        self.lock = threading.RLock()
        self.datasets = {"default": STATE}
        self.names = {"default": "Single dataset"}

    def get(self, dataset_id="default"):
        with self.lock:
            if dataset_id not in self.datasets:
                raise ValueError("Unknown dataset. Import this folder again.")
            return self.datasets[dataset_id]

    def add(self, payload):
        dataset = ProcessingState()
        discovered = dataset.discover({"path": payload["path"]})
        dataset_id = uuid.uuid4().hex
        name = str(payload.get("name", "")).strip() or dataset.path.parent.name + "/" + dataset.path.name
        with self.lock:
            self.datasets[dataset_id] = dataset
            self.names[dataset_id] = name
        return {"id": dataset_id, "name": name, "path": str(dataset.path), "discovery": discovered}

    def info(self, ids):
        result = []
        for dataset_id in ids:
            dataset = self.get(dataset_id)
            with dataset.lock:
                result.append({"id": dataset_id, "name": self.names[dataset_id],
                    **dataset.status(), "parameters": dataset.parameters,
                    "n_pixels": getattr(dataset, "n_pixels", None),
                    "qc_settings": getattr(dataset, "qc_settings", {}),
                    "cnr": dataset.cnr_records, "cnr_rois": dataset.cnr_rois})
        return result

    def export(self, ids):
        if len(set(ids)) < 2:
            raise ValueError("Choose at least two datasets.")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, dataset_id in enumerate(dict.fromkeys(ids), 1):
                dataset = self.get(dataset_id)
                with dataset.lock:
                    archive.writestr(f"dataset_{index}/results.zip", dataset.export())
            archive.writestr("datasets.json", json.dumps(clean_json(self.info(ids)), indent=2, allow_nan=False))
        return output.getvalue()


COMPARISON = ComparisonSession()


class Handler(BaseHTTPRequestHandler):
    """Serve only explicit frontend assets and local processing API routes."""

    def log_message(self, *_):
        pass

    def send(self, data, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def json(self, data, status=200):
        self.send(json.dumps(clean_json(data), allow_nan=False).encode(), status=status)

    def do_GET(self):
        url = urlparse(self.path)
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/compare": ("compare.html", "text/html; charset=utf-8"),
            "/compare.js": ("compare.js", "text/javascript; charset=utf-8"),
        }
        try:
            if url.path in assets:
                name, mime = assets[url.path]
                return self.send((STATIC / name).read_bytes(), mime)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/comparison-info":
                return self.json(COMPARISON.info(query.get("ids", "").split(",")))
            if url.path == "/api/comparison-export":
                return self.send(COMPARISON.export(query.get("ids", "").split(",")), "application/zip")
            session = COMPARISON.get(query.get("dataset", "default"))
            if url.path == "/api/process-progress":
                return self.json(session.processing_progress())
            with session.lock:
                if url.path == "/api/status":
                    return self.json(session.status())
                if url.path == "/api/image":
                    return self.json(
                        session.image({k: v[0] for k, v in parse_qs(url.query).items()})
                    )
                if url.path == "/api/export":
                    data = session.export()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header(
                        "Content-Disposition",
                        'attachment; filename="qcl-processing.zip"',
                    )
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.json({"error": "Not found"}, 404)
        except (ValueError, KeyError, RuntimeError, OSError) as exc:
            self.json({"error": str(exc)}, 400)

    def do_POST(self):
        # Browser cross-origin writes are rejected; normal same-origin calls work.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.json({"error": "Cross-origin request rejected."}, 403)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 1_000_000:
                raise ValueError("Invalid request size.")
            payload = json.loads(self.rfile.read(length))
            url = urlparse(self.path)
            if url.path == "/api/datasets":
                return self.json(COMPARISON.add(payload))
            session = COMPARISON.get(parse_qs(url.query).get("dataset", ["default"])[0])
            if url.path == "/api/export-video":
                with session.lock:
                    video = session.last_video
                    if not video or video['video_id'] != payload.get('video_id') or video['version'] != session.version:
                        raise ValueError("Rebuild the current video before exporting.")
                data = encode_video(video, float(payload['fps']), payload['labels'])
                return self.send(data, "video/mp4")
            routes = {
                "/api/discover": session.discover,
                "/api/raw-inspection": session.raw_inspection,
                "/api/raw-roi-spectrum": session.raw_roi_spectrum,
                "/api/roi-spectrum-sg": session.smooth_roi_spectrum,
                "/api/roi-spectrum-filter": session.filter_roi_spectrum,
                "/api/configure": session.configure,
                "/api/normalize": session.normalize,
                "/api/crop": session.crop,
                "/api/crop-preview": session.crop_plan,
                "/api/process": session.process,
                "/api/preview": session.preview,
                "/api/calculate": session.calculate,
                "/api/baseline": session.correct_baseline,
                "/api/cnr": session.cnr,
                "/api/baseline-pixel": session.baseline_pixel,
                "/api/timelapse": session.timelapse,
            }
            if url.path not in routes:
                return self.json({"error": "Not found"}, 404)
            with session.lock:
                self.json(routes[url.path](payload))
        except (ValueError, KeyError, RuntimeError, OSError, TypeError) as exc:
            self.json({"error": str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser(description="QCL processing workbench")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"QCL processing workbench: {url}", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
