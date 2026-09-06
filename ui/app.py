from __future__ import annotations

import argparse
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
from PIL import Image

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
        low: float = 1.0,
        high: float = 99.0,
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
        columns = ["frame", "pattern", "wavenumber", "i_goldref", "reference_valid"]
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
    low: float = 1,
    high: float = 99,
    cmap: str = "viridis",
    brightest: int = 0,
    limits: tuple[float, float] | None = None,
) -> bytes:
    finite = image[np.isfinite(image)]
    if finite.size == 0:
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
            rgb[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (239, 68, 68)
    output = io.BytesIO()
    Image.fromarray(rgb).save(output, format="PNG")
    return output.getvalue()


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
                        low=float(q.get("low", [1])[0]),
                        high=float(q.get("high", [99])[0]),
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
                data = render_png(
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
                array = STATE.image(
                    q.get("kind", ["raw"])[0],
                    q["pattern"][0],
                    int(q["wavenumber"][0]),
                )
                low = float(q.get("low", [1])[0])
                high = float(q.get("high", [99])[0])
                scale_patterns = [
                    pattern
                    for pattern in q.get("scale_patterns", [""])[0].split(",")
                    if pattern
                ]
                limits = None
                if scale_patterns:
                    kind = q.get("kind", ["raw"])[0]
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
                data = render_png(
                    array,
                    low=low,
                    high=high,
                    cmap=q.get("cmap", ["viridis"])[0],
                    brightest=int(q.get("brightest", [0])[0]),
                    limits=limits,
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Image-Width", str(array.shape[1]))
                self.send_header("X-Image-Height", str(array.shape[0]))
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
