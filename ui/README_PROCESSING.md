# QCL Processing Workbench

Run `python ui/app_processing.py` from the repository in the Python 3.12 `qcl`
environment, or use `ui/launch_processing_macos.command` on macOS. The separate
interface opens at http://127.0.0.1:8766. The original `ui/app.py` remains intact.
Install the project with `python -m pip install -e '.[ui,dev]'` if needed.

## How the workflow works

1. Scan a stacks directory, a pattern directory, an acquisition directory with
   a stacks child, or a spectral CSV. Wavenumbers come only from filenames
   `lineScan_<integer>_0invcm.csv`; there is no manual wavenumber entry field.
2. Select center bands and at least two references per center. References must
   bracket the center and exclude the center itself. The union of all center
   and reference bands is the processing set. Select one or more complete
   patterns; missing-band patterns are shown and cannot be selected.
3. Compute each full image's brightest-pixel mean and relative reflectance.
   QC measures reference variation across the selected patterns. Draw one
   shared on-MS ROI, checking alignment by changing the preview band/pattern.
4. Apply paired Gaussian notches or an elliptical Gaussian low-pass, then a
   rolling-ball multiplicative flat-field correction to every selected image.
   Fourier can be bypassed explicitly. Parameter meanings appear next to the
   controls. Inspection-window settings affect only the spectrum preview.
5. Select a shared cell-free ROI inside the corrected on-MS crop. Each image
   gets its own R0, absorbance and then its configured pixelwise spectral
   baseline correction. Two references interpolate; more fit least squares.
6. Inspect six stages with inferno. Different bands have independent scales;
   each band's three reflectance stages share a scale, as do its two absorbance
   stages. Draw shared CNR background and target ROIs. Export all selected
   patterns and bands, including metadata, masks, QC, R0 and CNR arrays/tables.

The new processing path follows notebook 06's on-MS workflow. The original app
still provides its independent on-MS/out-MS workflow. This interface also
supports a common-scale timelapse across already processed selected patterns,
with an inclusive pattern range and optional QC-frame exclusion. File creation
times are used when available, with modification-time fallback recorded.

## Scientific parameters and boundaries

- Notch coordinates are `(fy, fx)` in cycles/pixel, unrelated to cm^-1. Their
  symmetric partners are added automatically. Sigma controls the Gaussian
  width, strength controls rejection depth, and protect radius passes low
  frequencies unchanged.
- Low-pass x/y cutoffs are half-amplitude frequency semi-axes. Equal widths
  give a circular mask. Lower widths smooth more strongly along that axis.
- Rolling-ball radius is spatial pixels; cap height is reflectance units.
  Dark-feature mode estimates an upper background; bright-feature mode a lower
  background. Correction multiplies by median(background)/background.
- The cell-free ROI must contain only finite positive values at every selected
  image. Elsewhere nonpositive reflectance yields NaN absorbance, and invalid
  selected reference pixels propagate to baseline results.
- CNR is abs(target mean - background mean) / background sample standard
  deviation (ddof=1), using the common finite-pixel intersection per image
  across available stages. Undefined and unavailable values are null in JSON.
- Shared coordinates assume registered images; no automatic registration is
  performed. CNR changes alone do not validate image resolution or calibration.

## Code structure

`ui/app_processing.py` owns a local session, input discovery, workflow state,
API endpoints and ZIP export. Numerical work calls `src/qcl_analysis` functions
used by notebooks 04-06. `ui/static_processing/app.js` coordinates selections,
state-dependent navigation, previews and canvas ROIs. CSS and HTML provide a
separate local interface; no frontend package installation or remote hosting is
needed. The server serves only named frontend assets and binds to localhost.

Mutation requests run serially under a session lock and commit complete stage
results. Reconfiguring bands, crops, processing or R0 clears dependent numerical
results; the browser also locks downstream pages when inputs are edited.
This is a single-user in-memory session, not a persistent multi-user service.
