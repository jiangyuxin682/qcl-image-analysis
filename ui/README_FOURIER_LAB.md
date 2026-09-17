# Fourier Image Lab

An independent experimental UI for synthetic or imported images. It uses the
same Fourier filters as the processing workbench, without modifying that
workbench's data or session.

## Start

Use the existing project environment (no additional dependencies):

```bash
python ui/app_fourier_lab.py
```

Or double-click `launch_fourier_lab_macos.command` / `launch_fourier_lab_windows.bat`
in the `ui` folder. The browser opens **http://127.0.0.1:8767**. To use another
port or skip browser launch: `python ui/app_fourier_lab.py --port 8768 --no-browser`.
If the requested port is already in use, the launcher automatically chooses a
free port and prints/opens the actual address. A previously started instance can
also be used directly at its existing address.
For a first source installation, use the project's existing setup script.
This separate launcher is not included in the existing Processing executable;
use the source launcher for this laboratory.

## Experiments

1. Choose constant-width geometric letters, a rectangle, disk, parallel bars,
   checkerboard, straight edge, or an uploaded PNG/JPEG/TIFF/BMP/CSV.
2. For letters choose 1–6 characters A–Z, image size, stroke width in image
   pixels, and square or rounded corners. Rounded paths use quadratic curves
   at centerline corners and round open ends; short segments limit the requested
   rounding distance. This is a geometric stroke alphabet, not a typography font.
   Letter branches/intersections still meet; rounding is not morphological blur.
   **Smooth letter edges** optionally adds Gaussian smoothing after rendering
   the letter geometry and before noise. Set **Edge smoothing σ · pixels**
   from 0 to 20 (default 1.5 when enabled). Larger values widen the grayscale
   transition; strong smoothing can reduce narrow-stroke peak intensity.
   This is independent of square/rounded corner geometry. It is off by default;
   σ = 0 also preserves the original antialiased image. The smoothed image becomes
   the clean source for the experiment, FFT and RMSE comparison. Export records
   the effective setting in `edge_smoothing_effective`.
3. Add optional Gaussian, salt-and-pepper, or periodic stripe interference.
   Gaussian standard deviation and stripe amplitude are fractions of the clean
   intensity range (a constant source uses a range of 1). Noise is applied in
   that order and is not clipped. A fixed seed makes comparisons repeatable.
   New realization changes only the seed; generate to apply it.
4. Generate and inspect the clean source, noisy input, filtered output and
   signed removed signal. Their frequency views show `log(1 + abs(FFT))` on
   a shared scale. No inspection window is used. Padding changes the actual FFT
   grid. The first three spatial images also share a scale.
5. Use Gaussian low-pass, paired Gaussian notch, both, or no filtering.
   Cutoffs are half-amplitude frequencies in cycles/pixel. A notch coordinate
   is `(fy, fx)`; the conjugate partner is automatic. Click the input FFT to add
   coordinates, then apply the filter. The mask shows exactly what passes.
6. Compare the center-row profiles and RMSE relative to the clean source.
   Lower RMSE is useful for synthetic noise experiments, but smoothing can erase
   structures. For imports, the original image is the comparison reference;
   it is not necessarily noise-free ground truth.
7. Export the current experiment ZIP: reproducible settings, CSV arrays,
   frequency axes, and `arrays.npz` containing the full complex FFTs as well.
   Editing settings disables export until regeneration. Original imported
   grayscale values are included as `clean.csv`; no file is modified.

Each image has an independent **Set lower limit to 0** display switch, initially
off. Negative pixels then use the lowest color; arrays, RMSE and filtering stay
unchanged. The switch does not apply pending edits to the experiment settings.
Colorbar values use three decimal places. The spatial removed-signal palette
is diverging; the mask is grayscale.

Ordinary color images are converted to grayscale [0,1], with white behind
transparent pixels. Floating-point/integer numerical TIFF and headerless CSV
values retain their units. Imports must be finite, 8–1024 pixels per axis and
under 8 MB. Synthetic canvases are 128–512 pixels in the UI.
