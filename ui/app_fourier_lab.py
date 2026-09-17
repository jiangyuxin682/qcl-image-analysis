"""Independent synthetic-image Fourier laboratory. Run on localhost:8767."""
from __future__ import annotations

import argparse
import base64
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "qcl-fourier-mpl"))

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter
from matplotlib import colormaps
from qcl_analysis.fourier import (
    apply_fourier_notch_filter, apply_fourier_lowpass_filter,
    apply_fourier_combined_filter,
)

STATIC = Path(__file__).with_name("static_fourier_lab")
# Centerline geometry, not font outlines: the width is identical for every stroke.
GLYPHS = {
    "A": [[(0,1),(.5,0),(1,1)],[(.23,.55),(.77,.55)]],
    "B": [[(0,1),(0,0),(.7,0),(1,.2),(.7,.5),(0,.5)],[(.7,.5),(1,.75),(.7,1),(0,1)]],
    "C": [[(1,0),(0,0),(0,1),(1,1)]],
    "D": [[(0,1),(0,0),(.65,0),(1,.3),(1,.7),(.65,1),(0,1)]],
    "E": [[(1,0),(0,0),(0,1),(1,1)],[(0,.5),(.8,.5)]],
    "F": [[(1,0),(0,0),(0,1)],[(0,.5),(.8,.5)]],
    "G": [[(1,0),(0,0),(0,1),(1,1),(1,.55),(.55,.55)]],
    "H": [[(0,0),(0,1)],[(1,0),(1,1)],[(0,.5),(1,.5)]],
    "I": [[(0,0),(1,0)],[(.5,0),(.5,1)],[(0,1),(1,1)]],
    "J": [[(0,0),(1,0),(1,1),(0,1),(0,.7)]],
    "K": [[(0,0),(0,1)],[(1,0),(0,.5),(1,1)]],
    "L": [[(0,0),(0,1),(1,1)]],
    "M": [[(0,1),(0,0),(.5,.5),(1,0),(1,1)]],
    "N": [[(0,1),(0,0),(1,1),(1,0)]],
    "O": [[(0,0),(1,0),(1,1),(0,1),(0,0)]],
    "P": [[(0,1),(0,0),(1,0),(1,.5),(0,.5)]],
    "Q": [[(0,0),(1,0),(1,1),(0,1),(0,0)],[(.6,.6),(1,1)]],
    "R": [[(0,1),(0,0),(1,0),(1,.5),(0,.5)],[(.5,.5),(1,1)]],
    "S": [[(1,0),(0,0),(0,.5),(1,.5),(1,1),(0,1)]],
    "T": [[(0,0),(1,0)],[(.5,0),(.5,1)]],
    "U": [[(0,0),(0,1),(1,1),(1,0)]],
    "V": [[(0,0),(.5,1),(1,0)]],
    "W": [[(0,0),(.2,1),(.5,.5),(.8,1),(1,0)]],
    "X": [[(0,0),(1,1)],[(1,0),(0,1)]],
    "Y": [[(0,0),(.5,.5),(1,0)],[(.5,.5),(.5,1)]],
    "Z": [[(0,0),(1,0),(0,1),(1,1)]],
}


def number(config, key, default, low, high, integer=False):
    v = float(config.get(key, default))
    if not np.isfinite(v) or not low <= v <= high or (integer and v != int(v)):
        raise ValueError(f"{key} must be {'an integer ' if integer else ''}between {low} and {high}.")
    return int(v) if integer else v


def round_path(points, radius):
    """Round centerline corners using tangent quadratic curves at fixed width."""
    p = np.asarray(points, float)
    if radius <= 0 or len(p) < 3:
        return p
    closed = np.array_equal(p[0], p[-1])
    if closed:
        p = p[:-1]
    result = [] if closed else [p[0]]
    indices = range(len(p)) if closed else range(1, len(p)-1)
    for i in indices:
        prev, vertex, nxt = p[i-1], p[i], p[(i+1) % len(p)]
        a, b = prev-vertex, nxt-vertex
        distance = min(radius, np.linalg.norm(a)*.45, np.linalg.norm(b)*.45)
        start = vertex + a / np.linalg.norm(a) * distance
        end = vertex + b / np.linalg.norm(b) * distance
        for t in np.linspace(0, 1, 17):
            result.append((1-t)**2*start + 2*t*(1-t)*vertex + t*t*end)
    result.append(result[0] if closed else p[-1])
    return np.asarray(result)


def stroke(draw, points, width, rounded):
    """Draw constant-width segments with explicit miter joins (square corners)."""
    points = np.asarray(points, float)
    closed = np.array_equal(points[0], points[-1])
    normals = []
    for a, b in zip(points[:-1], points[1:]):
        d = b-a
        n = np.array([-d[1], d[0]]) / np.linalg.norm(d) * width/2
        normals.append(n)
        draw.polygon([tuple(q) for q in [a+n, b+n, b-n, a-n]], fill=255)
    for i in range(len(points)-1) if closed else range(1, len(points)-1):
        a, b = normals[i-1], normals[i]
        divisor = 1 + np.dot(a, b)/(width/2)**2
        miter = (a+b)/divisor if divisor > .05 else b
        for sign in (-1, 1):
            draw.polygon([tuple(points[i]+v*sign) for v in [np.zeros(2), a, miter, b]], fill=255)
    if rounded and not closed:
        for x, y in (points[0], points[-1]):
            r = width/2
            draw.ellipse((x-r,y-r,x+r,y+r), fill=255)


def make_image(config):
    kind = config.get("source", "letters")
    if kind == "upload":
        data = base64.b64decode(config.get("file_data", ""), validate=True)
        if len(data) > 8_000_000:
            raise ValueError("Upload must be smaller than 8 MB.")
        if config.get("filename", "").lower().endswith(".csv"):
            image = np.loadtxt(io.BytesIO(data), delimiter=",")
        else:
            with Image.open(io.BytesIO(data)) as im:
                if max(im.size) > 1024:
                    raise ValueError("Image dimensions must be at most 1024 pixels. Resize before importing.")
                if im.mode in ("F", "I", "I;16"):
                    image = np.asarray(im, float)
                else:
                    rgba = im.convert("RGBA")
                    white = Image.new("RGBA", im.size, "white")
                    image = np.asarray(Image.alpha_composite(white, rgba).convert("L"), float)/255
        if image.ndim != 2 or min(image.shape) < 8 or max(image.shape) > 1024 or not np.isfinite(image).all():
            raise ValueError("Upload must be a finite grayscale image, 8–1024 pixels per axis. CSV has no header.")
        return image
    size = number(config, "size", 256, 64, 512, True)
    width = number(config, "stroke", 10, 1, size/6)
    radius = number(config, "corner_radius", 16, 0, size/3)
    rounded = config.get("corners", "square") == "round"
    supersample = 4
    canvas = Image.new("L", (size*supersample, size*supersample))
    draw = ImageDraw.Draw(canvas)
    if kind == "letters":
        text = str(config.get("letters", "EHL")).upper()
        if not 1 <= len(text) <= 6 or any(c not in GLYPHS for c in text):
            raise ValueError("Use 1–6 letters A–Z without spaces.")
        gap = max(width*1.5, size*.035)
        glyph_width = (size*.76-gap*(len(text)-1))/len(text)
        if glyph_width < width*2:
            raise ValueError("Letters are too crowded for this stroke width. Use fewer letters or thinner strokes.")
        for index, letter in enumerate(text):
            for path in GLYPHS[letter]:
                points = np.asarray(path)*[glyph_width,size*.56]+[size*.12+index*(glyph_width+gap),size*.22]
                points = round_path(points, radius if rounded else 0)
                stroke(draw, points*supersample, width*supersample, rounded)
    elif kind in ("rectangle", "disk"):
        box = tuple(v*size*supersample for v in (.25,.25,.75,.75))
        if kind == "disk":
            draw.ellipse(box, fill=255)
        else:
            draw.rounded_rectangle(box, radius=radius*supersample if rounded else 0, fill=255)
    elif kind in ("bars", "checkerboard", "edge"):
        y, x = np.mgrid[:size, :size]
        period = number(config, "period", 24, 4, size)
        theta = np.deg2rad(number(config, "angle", 0, -180, 180))
        u = (x-size/2)*np.cos(theta)+(y-size/2)*np.sin(theta)
        v = -(x-size/2)*np.sin(theta)+(y-size/2)*np.cos(theta)
        if kind == "edge":
            return (u >= 0).astype(float)
        if kind == "bars":
            return ((u % period) < min(width, period)).astype(float)
        return ((np.floor(u/period)+np.floor(v/period)) % 2).astype(float)
    else:
        raise ValueError("Unknown image source.")
    image = np.asarray(canvas.resize((size,size), Image.Resampling.LANCZOS), float)/255
    if kind == "letters" and config.get("edge_smoothing", False):
        sigma = number(config, "edge_sigma", 1.5, 0, 20)
        if sigma > 0:
            image = gaussian_filter(image, sigma=sigma, mode="reflect")
    return image


def calculate(config):
    clean = make_image(config)
    seed = number(config, "seed", 42, 0, 2**32-1, True)
    rng = np.random.default_rng(seed)
    signal = clean.copy()
    span = float(np.ptp(clean)) or 1.0
    if config.get("gaussian", False):
        signal += rng.normal(0, number(config,"noise_sigma",.08,0,2)*span, clean.shape)
    if config.get("impulse", False):
        rate = number(config,"impulse_rate",.02,0,1)
        r = rng.random(clean.shape)
        signal[r < rate/2] = clean.min()
        signal[(r >= rate/2) & (r < rate)] = clean.max()
    if config.get("stripes", False):
        amplitude = number(config,"stripe_amplitude",.15,0,2)*span
        period = number(config,"stripe_period",8,2,512)
        angle = np.deg2rad(number(config,"stripe_angle",0,-180,180))
        y,x = np.indices(clean.shape)
        signal += amplitude*np.cos(2*np.pi*(x*np.cos(angle)+y*np.sin(angle))/period)
    mode = config.get("filter", "lowpass")
    shared = {"pad_pixels": number(config,"padding",0,0,64,True), "preserve_mean": True}
    lowpass = {"cutoff_x":number(config,"cutoff_x",.18,.001,.5),"cutoff_y":number(config,"cutoff_y",.18,.001,.5)}
    centers = config.get("notches", [])
    if not isinstance(centers, list) or len(centers) > 40:
        raise ValueError("Specify at most 40 notch centers.")
    notch = {"centers":centers,"sigma":number(config,"sigma",.012,.0001,.25),
             "strength":number(config,"strength",1,0,1),"protect_radius":number(config,"protect",.015,0,.5)}
    if mode == "none":
        output = apply_fourier_notch_filter(signal, [], **shared)
    elif mode == "lowpass":
        output = apply_fourier_lowpass_filter(signal, **lowpass, **shared)
    elif mode == "notch":
        output = apply_fourier_notch_filter(signal, **notch, **shared)
    elif mode == "combined":
        output = apply_fourier_combined_filter(signal, **notch, **lowpass, **shared)
    else:
        raise ValueError("Unknown filter mode.")
    pad = shared["pad_pixels"]
    clean_padded = np.pad(clean, pad, mode="reflect") if pad else clean
    arrays = {"clean":clean,"input":signal,"filtered":output.filtered,"removed":output.removed,
              "fft_clean":np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(clean_padded)))),
              "fft_input":np.log1p(np.abs(output.spectrum_before)),
              "fft_filtered":np.log1p(np.abs(output.spectrum_after)),
              "fft_removed":np.log1p(np.abs(output.spectrum_before-output.spectrum_after)),
              "mask":output.mask}
    return arrays, output


def analyze(config):
    arrays, output = calculate(config)
    spatial = (min(float(arrays[k].min()) for k in ("clean","input","filtered")),
               max(float(arrays[k].max()) for k in ("clean","input","filtered")))
    fft_max = max(float(a.max()) for k,a in arrays.items() if k.startswith("fft_"))
    removed = max(float(np.max(np.abs(arrays["removed"]))), 1e-12)
    cards = []
    for key, array in arrays.items():
        lo, hi = (0,fft_max) if key.startswith("fft_") else (0,1) if key == "mask" else (-removed,removed) if key == "removed" else spatial
        if key in config.get("zero_images", []):
            lo,hi = 0,max(hi,1e-12)
        hi = max(hi,lo+1e-12)
        palette = "coolwarm" if key == "removed" else "gray" if key == "mask" else "inferno"
        rgb = colormaps[palette](np.clip((array-lo)/(hi-lo),0,1), bytes=True)[...,:3]
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG")
        cards.append({"key":key,"png":base64.b64encode(buffer.getvalue()).decode(),"vmin":lo,"vmax":hi,
                      "width":array.shape[1],"height":array.shape[0],"palette":palette})
    row = arrays["clean"].shape[0]//2
    metrics = {"input_rmse":float(np.sqrt(np.mean((arrays['input']-arrays['clean'])**2))),
               "filtered_rmse":float(np.sqrt(np.mean((arrays['filtered']-arrays['clean'])**2))),
               "removed_rms":float(np.sqrt(np.mean(arrays['removed']**2)))}
    return {"cards":cards,"fx":output.fx.tolist(),"fy":output.fy.tolist(),"metrics":metrics,
            "profile_row":row,"profiles":{k:arrays[k][row].tolist() for k in ("clean","input","filtered")}}


def export(config):
    arrays, output = calculate(config)
    data = io.BytesIO()
    metadata = {k:v for k,v in config.items() if k != "file_data"}
    metadata.update({"frequency_units":"cycles/pixel; fftshift ordering", "fft_display":"log1p(abs(FFT)); same scale for every FFT",
                     "edge_smoothing_effective": {"enabled": config.get("source", "letters") == "letters" and bool(config.get("edge_smoothing", False)),
                                                  "sigma_pixels": float(config.get("edge_sigma", 1.5)) if config.get("source", "letters") == "letters" and config.get("edge_smoothing", False) else 0,
                                                  "method": "Gaussian, reflect boundary; applied to rendered letters before noise; sigma 0 is identity"},
                     "geometry":"Constant-width centerline strokes; antialiased 4x; rounded centerline corners use quadratic curves with tangent distance capped at 45% of adjacent segments.",
                     "noise":"Gaussian and stripes relative to clean intensity range; no clipping. Impulse noise sets random pixels to clean extrema.",
                     "fft_after":"Padded masked FFT before output mean restoration; removed spatial image = input - final output."})
    with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("settings.json",json.dumps(metadata,indent=2))
        for key, array in {**arrays,"fx":output.fx,"fy":output.fy}.items():
            stream=io.StringIO();np.savetxt(stream,array,delimiter=",");z.writestr(key+".csv",stream.getvalue())
        npz=io.BytesIO();np.savez_compressed(npz,**arrays,fft_before=output.spectrum_before,fft_after=output.spectrum_after,fx=output.fx,fy=output.fy)
        z.writestr("arrays.npz",npz.getvalue())
    return data.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def send(self,data,kind="application/json",status=200):
        self.send_response(status);self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data)

    def do_GET(self):
        assets={"/":("index.html","text/html; charset=utf-8"),"/app.js":("app.js","text/javascript"),"/styles.css":("styles.css","text/css")}
        asset=assets.get(urlparse(self.path).path)
        if not asset:
            return self.send(b"Not found","text/plain",404)
        self.send((STATIC/asset[0]).read_bytes(),asset[1])

    def do_POST(self):
        try:
            if self.path not in ("/api/analyze","/api/export"):
                return self.send(b"Not found","text/plain",404)
            size=int(self.headers.get("Content-Length",0))
            if not 0 < size <= 12_000_000:
                raise ValueError("Request must be smaller than 12 MB.")
            config=json.loads(self.rfile.read(size))
            if not isinstance(config,dict):
                raise ValueError("Expected a settings object.")
            if self.path == "/api/export":
                return self.send(export(config),"application/zip")
            self.send(json.dumps(analyze(config),allow_nan=False).encode())
        except (ValueError,TypeError,KeyError,OSError) as exc:
            self.send(json.dumps({"error":str(exc)}).encode(),status=400)


def create_server(port):
    """Let the OS choose a free port when the requested port is occupied."""
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE and getattr(exc, "winerror", None) != 10048:
            raise
        return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def main():
    parser=argparse.ArgumentParser(description="Independent Fourier image laboratory")
    parser.add_argument("--port",type=int,default=8767);parser.add_argument("--no-browser",action="store_true")
    args=parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    server=create_server(args.port)
    if args.port and server.server_port != args.port:
        print(f"Port {args.port} is already in use; using free port {server.server_port}.", flush=True)
    url=f"http://127.0.0.1:{server.server_port}";print(f"Fourier Image Lab: {url}",flush=True)
    if not args.no_browser:
        threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
