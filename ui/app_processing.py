"""Local QCL processing interface combining the existing app and notebook 06.

Run ``python ui/app_processing.py`` from the repository (default port 8766).
Filename discovery precedes explicit center/reference-band assignment. The
union of selected bands is processed independently for each selected pattern:
full raw normalization -> shared on-MS crop -> Fourier -> rolling-ball field
-> per-image cell-free reference -> absorbance -> pixelwise baseline -> CNR.

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
import webbrowser
import zipfile
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "qcl-processing-mpl")
)

import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter

from qcl_analysis.absorbance import calculate_absorbance
from qcl_analysis.baseline import correct_absorbance_baselines
from qcl_analysis.cnr import compare_stage_cnr
from qcl_analysis.cropping import crop_image
from qcl_analysis.flat_field import FlatFieldResult, rolling_ball_flat_field
from qcl_analysis.fourier import (
    FourierFilterResult,
    apply_fourier_lowpass_filter,
    apply_fourier_notch_filter,
    fourier_spectrum,
)
from qcl_analysis.io import load_qcl_csv
from qcl_analysis.qc import add_frame_quality_flags, add_reference_quality_flags
from qcl_analysis.reflectance import calculate_gold_reference
from qcl_analysis.roi import ROI
from ui.app import render_data_png

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


def select_cell_free_pixels(image, method, count):
    """Return stable (y, x) coordinates for extreme positive finite pixels."""
    if method not in {"brightest", "darkest"}:
        raise ValueError("Cell-free pixel method must be brightest or darkest.")
    count = integer(count, "Cell-free pixel count")
    if count < 1:
        raise ValueError("Cell-free pixel count must be at least 1.")
    image = np.asarray(image, dtype=float)
    valid_flat = np.flatnonzero(np.isfinite(image.ravel()) & (image.ravel() > 0))
    if count > valid_flat.size:
        raise ValueError(
            f"Cell-free pixel count ({count}) exceeds the number of positive finite pixels ({valid_flat.size})."
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
        self.qc = pd.DataFrame()
        self.on_roi = None
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
            "cropped",
            "processed",
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
        n_pixels = integer(payload.get("n_pixels", 100), "Brightest pixels")
        raw, ref, signals = {}, {}, []
        for row in selected.itertuples(index=False):
            image = load_qcl_csv(row.path)
            gold = calculate_gold_reference(image, n_pixels)
            key = (row.pattern, int(row.wavenumber))
            raw[key], ref[key] = image, image / gold
            signals.append(gold)
        if len({a.shape for a in raw.values()}) != 1:
            raise ValueError(
                "All selected images must have the same spatial shape. Registration is not performed."
            )
        selected["i_goldref"] = signals
        selected["gold_reference_n_pixels"] = n_pixels
        z = float(payload.get("robust_z_threshold", 5))
        deviation = float(payload.get("relative_threshold", 0.1))
        selected = add_reference_quality_flags(
            selected, robust_z_threshold=z, min_relative_deviation=deviation
        )
        selected = add_frame_quality_flags(selected, expected_wavenumbers=set(bands))
        self.reset_analysis()
        self.mapping, self.patterns, self.bands = mapping, patterns, bands
        self.raw, self.ref, self.qc = raw, ref, selected
        self.n_pixels = n_pixels
        self.qc_settings = {
            "robust_z_threshold": z,
            "min_relative_deviation": deviation,
        }
        self.stage = "configured"
        self.version += 1
        return {
            **self.status(),
            "shape": list(next(iter(raw.values())).shape),
            "qc": selected.drop(columns="path").to_dict(orient="records"),
        }

    def crop(self, payload):
        self.require("configured")
        roi = roi_from(payload["roi"])
        crops = {key: crop_image(a, roi) for key, a in self.ref.items()}
        if min(next(iter(crops.values())).shape) < 2:
            raise ValueError("The on-MS crop must be at least 2 × 2 pixels.")
        self.on_roi, self.crops = roi, crops
        self.clear_processed()
        self.stage = "cropped"
        self.version += 1
        return {**self.status(), "shape": list(next(iter(crops.values())).shape)}

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
        if mode not in {"notch", "lowpass", "none"}:
            raise ValueError("Choose notch, lowpass or none.")
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
        low, high = float(payload.get("low", 1)), float(payload.get("high", 99))
        if not 0 <= low < high <= 100:
            raise ValueError("Display percentiles must satisfy 0 <= low < high <= 100.")
        limits = self.limits(arrays, low, high)
        cards = []
        for title, array in zip(
            ("Before processing", "After Fourier", "After rolling ball"), arrays
        ):
            png, lo, hi = render_data_png(array, limits=limits)
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
            png, lo, hi = render_data_png(array, limits=scale)
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
        enabled = bool(payload["rolling"].get("enabled", True))
        diagnostic(
            "Estimated rolling-ball background",
            flat.background,
            self.limits([output.filtered, flat.background], low, high),
            "Estimated illumination field (reflectance). Correction divides by this field and rescales; it is not subtracted.",
            enabled,
        )
        diagnostic(
            "Rolling-ball correction gain",
            flat.gain,
            self.limits([flat.gain], low, high),
            "Gain = reference level / background. Corrected reflectance = input reflectance × gain.",
            enabled,
        )
        removed = output.filtered - flat.corrected
        finite = removed[np.isfinite(removed)]
        bound = max(float(np.max(np.abs(finite))) if finite.size else 0.0, 1e-12)
        diagnostic(
            "Rolling-ball difference: input − corrected",
            removed,
            (-bound, bound),
            "Signed change in reflectance, distinct from the estimated illumination background.",
        )
        return {
            "images": cards,
            "diagnostics": diagnostics,
            "version": self.version,
            "invalid_pixels": int((~flat.valid_mask).sum()),
        }

    def process(self, payload):
        self.require("cropped")
        f, r = payload["fourier"], payload["rolling"]
        ff, flat = {}, {}
        for key, image in self.crops.items():
            ff[key], flat[key] = self.process_image(image, payload)
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
            raise ValueError("Unknown cell-free reference method.")
        roi = roi_from(payload["roi"]) if method == "roi" else None
        count = integer(payload.get("count", 1), "Cell-free pixel count") if method != "roi" else None
        absorbance, baselines, records = {}, {}, []
        selections = {}
        reference_bands = {}
        pattern_pixels = {}
        if method != "roi":
            requested = payload.get("reference_bands", {})
            for pattern in self.patterns:
                wn = integer(requested.get(pattern, self.bands[0]), "Reference wavenumber")
                if (pattern, wn) not in self.flat:
                    raise ValueError(f"Choose a processed reference wavenumber for {pattern}.")
                reference_bands[pattern] = wn
                pattern_pixels[pattern] = select_cell_free_pixels(
                    self.flat[(pattern, wn)].corrected, method, count
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
                    f"Cell-free selection contains invalid reflectance at {key}. Select another reference."
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
        for pattern in self.patterns:
            results = correct_absorbance_baselines(
                {wn: absorbance[(pattern, wn)] for wn in self.bands}, self.mapping
            )
            baselines.update(
                {(pattern, int(wn)): result for wn, result in results.items()}
            )
        self.r0_roi, self.r0_selection, self.r0_pixels = (
            roi,
            {"method": method, **({"count": count, "reference_bands": reference_bands} if count is not None else {})},
            selections,
        )
        self.absorbance, self.baselines, self.r0_records = (
            absorbance,
            baselines,
            records,
        )
        self.cnr_records, self.cnr_rois = [], None
        self.stage = "complete"
        self.version += 1
        return {**self.status(), "r0": records}

    def stage_arrays(self, key):
        self.require("cropped")
        return {
            "raw": crop_image(self.raw[key], self.on_roi),
            "reflectance": self.crops[key],
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
        rows = []
        for key in self.crops:
            rows.extend(
                {"pattern": key[0], "wavenumber": key[1], **r}
                for r in compare_stage_cnr(self.stage_arrays(key), bg, target)
            )
        self.cnr_records, self.cnr_rois = (
            rows,
            {"background": asdict(bg), "target": asdict(target)},
        )
        return {"records": rows, "rois": self.cnr_rois}

    @staticmethod
    def limits(arrays, low=1, high=99):
        values = np.concatenate([a[np.isfinite(a)] for a in arrays if a is not None])
        if not values.size:
            return (0.0, 1.0)
        lo, hi = np.percentile(values, [low, high])
        return (float(lo), float(max(hi, lo + 1e-12)))

    def image(self, payload):
        self.require("configured")
        key = (payload["pattern"], integer(payload["wavenumber"], "Wavenumber"))
        if key not in self.ref:
            raise ValueError("Choose a configured pattern and wavenumber.")
        kind = payload.get("kind", "full_reflectance")
        low, high = float(payload.get("low", 1)), float(payload.get("high", 99))
        if not 0 <= low < high <= 100:
            raise ValueError("Display percentiles must satisfy 0 <= low < high <= 100.")
        extra = {}
        limits = None
        if kind == "full_reflectance":
            array = self.ref[key]
        elif kind == "full_raw":
            array = self.raw[key]
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
            group = (
                ("reflectance", "fourier", "rolling")
                if kind in ("reflectance", "fourier", "rolling")
                else (
                    ("absorbance", "baseline")
                    if kind in ("absorbance", "baseline")
                    else (kind,)
                )
            )
            limits = self.limits([arrays[k] for k in group], low, high)
        if kind == "rolling" and payload.get("r0_method") in {
            "brightest",
            "darkest",
        }:
            wn = integer(payload.get("r0_reference_band", self.bands[0]), "Reference wavenumber")
            if (key[0], wn) not in self.flat:
                raise ValueError("Choose a processed reference wavenumber.")
            pixels = select_cell_free_pixels(
                self.flat[(key[0], wn)].corrected,
                payload["r0_method"], payload.get("r0_count", 1)
            )
            extra["reference_wavenumber"] = wn
            reference = array[pixels[:, 0], pixels[:, 1]]
            if not np.isfinite(reference).all() or (reference <= 0).any():
                raise ValueError("Selected reference positions contain invalid reflectance in this band.")
            extra["cell_free_pixels"] = pixels.tolist()
            extra["cell_free_r0"] = float(
                np.mean(array[pixels[:, 0], pixels[:, 1]])
            )
        png, lo, hi = render_data_png(
            array,
            low=low,
            high=high,
            limits=limits,
            brightest=self.n_pixels
            if kind == "full_raw" and payload.get("brightest") == "true"
            else 0,
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
        if kind not in {"absorbance", "baseline"}:
            raise ValueError("Timelapse stage must be absorbance or baseline.")
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
        limits = self.limits(arrays, low, high)
        for f, a in zip(frames, arrays):
            png, _, _ = render_data_png(a, limits=limits)
            f["png"] = base64.b64encode(png).decode()
            f["elapsed_seconds"] = f["timestamp"] - frames[0]["timestamp"]
        return {
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

    def export(self):
        self.require("complete")
        buffer = io.BytesIO()
        metadata = {
            "source": str(self.path),
            "centers_and_references": self.mapping,
            "patterns": self.patterns,
            "processed_wavenumbers": self.bands,
            "n_reference_pixels": self.n_pixels,
            "on_ms_roi": asdict(self.on_roi),
            "cell_free_roi_local": asdict(self.r0_roi) if self.r0_roi else None,
            "cell_free_selection": self.r0_selection,
            "roi_coordinates": "half-open pixel coordinates; cell-free and CNR ROIs local to on-MS crop",
            "processing": self.parameters,
            "qc_settings": self.qc_settings,
            "r0": self.r0_records,
            "baseline_method": "pixelwise unweighted linear least squares; two references give interpolation",
            "cnr_rois": self.cnr_rois,
            "cnr_formula": "abs(mean(target)-mean(background))/std(background,ddof=1)",
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
        }
        try:
            if url.path in assets:
                name, mime = assets[url.path]
                return self.send((STATIC / name).read_bytes(), mime)
            with STATE.lock:
                if url.path == "/api/status":
                    return self.json(STATE.status())
                if url.path == "/api/image":
                    return self.json(
                        STATE.image({k: v[0] for k, v in parse_qs(url.query).items()})
                    )
                if url.path == "/api/export":
                    data = STATE.export()
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
            routes = {
                "/api/discover": STATE.discover,
                "/api/configure": STATE.configure,
                "/api/crop": STATE.crop,
                "/api/process": STATE.process,
                "/api/preview": STATE.preview,
                "/api/calculate": STATE.calculate,
                "/api/cnr": STATE.cnr,
                "/api/timelapse": STATE.timelapse,
            }
            if self.path not in routes:
                return self.json({"error": "Not found"}, 404)
            with STATE.lock:
                self.json(routes[self.path](payload))
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
