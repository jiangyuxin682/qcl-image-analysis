"""Checks executed inside the packaged executable before a build is distributed."""
import base64
import io
from pathlib import Path
import sys
import tempfile
import threading
from urllib.request import urlopen
import zipfile


def run_checks(check_window=True):
    import numpy as np
    from ui.app_processing import ProcessingState
    from ui.desktop import create_server
    from ui.video_export import encode_video, find_ffmpeg

    checks = []
    if check_window:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        checks.append("native window / Tcl-Tk")

    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ("/", "/app.js", "/styles.css", "/compare", "/compare.js", "/api/status"):
            with urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=10) as response:
                if response.status != 200 or not response.read():
                    raise RuntimeError(f"Packaged asset/API failed: {path}")
        checks.append("HTTP server, processing and comparison assets")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    with tempfile.TemporaryDirectory(prefix="qcl-desktop-check-") as directory:
        folder = Path(directory) / "测试 data" / "pattern0"
        folder.mkdir(parents=True)
        yy, xx = np.mgrid[:16, :20]
        for band in (1675, 1725, 1775):
            raw = 100 + .1*xx + .2*yy + np.sin(xx*2)
            raw -= (band == 1725)*2*np.exp(-((xx-10)**2+(yy-8)**2)/10)
            np.savetxt(folder / f"lineScan_{band}_0invcm.csv", raw, delimiter=",")
        state = ProcessingState()
        state.discover({"path": str(folder)})
        roi = {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3}
        target = {"x_min": 8, "x_max": 13, "y_min": 5, "y_max": 10}
        spectra = state.raw_roi_spectrum({"pattern": "pattern0", "wavenumber": 1725,
                                         "analyte_roi": target, "background_roi": roi})
        if len(spectra["points"]) != 3:
            raise RuntimeError("ROI spectrum did not read all bands")
        state.filter_roi_spectrum({"wavenumbers": list(range(21)), "absorbance": np.sin(np.arange(21)/4).tolist(),
                                   "fourier_enabled": True, "fourier_mode": "combined", "cutoff": .3,
                                   "notch_centers": [.2], "notch_width": .03,
                                   "sg_enabled": True, "window": 5, "order": 2})
        checks.append("Unicode data path, CSV, ROI spectrum, Fourier/notch/SG")
        state.configure({"mapping": {"1725": [1675, 1775]}, "patterns": ["pattern0"], "n_pixels": 5})
        state.normalize({"has_gold": True, "n_pixels": 5})
        state.crop({"roi": {"x_min": 0, "x_max": 20, "y_min": 0, "y_max": 16}})
        state.process({"fourier": {"mode": "lowpass", "cutoff_x": .2, "cutoff_y": .1},
                       "rolling": {"radius": 3, "kernel_height": .05}})
        state.calculate({"roi": roi})
        state.correct_baseline({})
        state.cnr({"background": roi, "target": target})
        preview = state.image({"kind": "baseline", "pattern": "pattern0", "wavenumber": 1725})
        if not base64.b64decode(preview["png"]).startswith(b"\x89PNG"):
            raise RuntimeError("Packaged heatmap rendering failed")
        with zipfile.ZipFile(io.BytesIO(state.export())) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise RuntimeError("Results ZIP is invalid")
        checks.append("normalization, image Fourier, rolling ball, absorbance, baseline, CNR, PNG, ZIP")
        encoder = find_ffmpeg()
        if not encoder:
            raise RuntimeError("FFmpeg is missing")
        if getattr(sys, "frozen", False) and not Path(encoder).resolve().is_relative_to(Path(sys._MEIPASS).resolve()):
            raise RuntimeError("The frozen application did not include its own FFmpeg")
        video = {"kind": "baseline", "wavenumber": 1725, "low": 0, "high": 100,
                 "vmin": preview["vmin"], "vmax": preview["vmax"],
                 "frames": [{"png": preview["png"]}]}
        mp4 = encode_video(video, 2, ["pattern0"])
        if b"ftyp" not in mp4[:32]:
            raise RuntimeError("MP4 encoding failed")
        checks.append("FFmpeg / H.264 MP4")
    return {"ok": True, "platform": sys.platform, "frozen": bool(getattr(sys, "frozen", False)), "checks": checks}
