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
5. Choose a shared rectangular cell-free ROI, or select a fixed number of the
   brightest or darkest valid pixels in a chosen reference band for each pattern.
   All bands within that pattern share those coordinates and calculate their
   own R0 from their own reflectance values.
   Thin cyan crosses identify the selected positions in the current preview. Each
   image gets its own R0 and absorbance, followed by its configured pixelwise
   spectral baseline correction. Two references interpolate; more fit least
   squares.
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

### Optional stages and live preview

The Fourier and rolling-ball checkboxes independently enable each stage.
A disabled stage passes its input values through unchanged. Its diagnostic
mask/gain is one; a bypassed rolling-ball background is an identity field,
not an estimated physical background. Both enabled flags are exported.

The inspection spectrum shows up to ten candidate conjugate pairs, following
notebook 06: 5-by-5 local maxima, one half-plane, and a central exclusion radius
(default 0.025 cycles/pixel). Rankings use FFT amplitude before display scaling.
The table shows both coordinates, period, amplitude, and Added/Not added status.
Add pair and Remove pair update both conjugate coordinates together. Clicking Add pair or
a spectrum point puts both signs into the notch list without duplicates.
The underlying mask combines rejection by maximum, so explicitly listing both
partners does not double the suppression. Candidates are not confirmed noise.

Parameter edits automatically preview the current pattern and band after a
450 ms pause. Preview runs at full crop resolution using the exact same
processing function as batch processing, without changing committed arrays.
Only one preview runs at a time; newer edits replace pending work and stale
responses are discarded. Larger rolling-ball radii may take longer to update.
The before/Fourier/rolling images share a reflectance scale. Use Process all
involved bands to commit the settings before calculating absorbance and CNR.

- Notch coordinates are `(fy, fx)` in cycles/pixel, unrelated to cm^-1. Their
  symmetric partners are added automatically. Sigma controls the Gaussian
  width, strength controls rejection depth, and protect radius passes low
  frequencies unchanged.
- Low-pass x/y cutoffs are half-amplitude frequency semi-axes. Equal widths
  give a circular mask. Lower widths smooth more strongly along that axis.
- Rolling-ball radius is spatial pixels; cap height is reflectance units.
  Dark-feature mode estimates an upper background; bright-feature mode a lower
  background. Correction multiplies by median(background)/background.
- A rectangular cell-free ROI must contain only finite positive values in every
  selected image. Extreme-pixel modes rank only finite positive reflectance,
  break ties in row-major order, and reject counts larger than the available
  pixels. Selection coordinates and a mask are exported for every image.
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
