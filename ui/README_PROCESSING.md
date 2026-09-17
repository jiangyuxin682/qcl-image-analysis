# QCL Processing Workbench

Run `python ui/app_processing.py` from the repository in the Python 3.12 `qcl`
environment, or use `ui/launch_processing_macos.command` on macOS. The separate
interface opens at http://127.0.0.1:8766. The original `ui/app.py` remains intact.
Install the project with `python -m pip install -e '.[ui,dev]'` if needed.

On Windows, run `ui/setup_windows.bat` once, then
`ui/launch_processing_windows.bat`. For a standalone EXE with all runtime
dependencies included, follow [Windows packaging](../packaging/README.md).

## How the workflow works

1. Scan a stacks directory, a pattern directory, an acquisition directory with
   a stacks child, or a spectral CSV. Wavenumbers come only from filenames
   `lineScan_<integer>_0invcm.csv`; there is no manual wavenumber entry field.
2. Select center bands and at least two references per center. References must
   bracket the center and exclude the center itself. The union of all center
   and reference bands is the processing set. Select one or more complete
   patterns; missing-band patterns are shown and cannot be selected.
3. **Calculate reflectance:** explicitly choose whether a gold patch reference
   is available. With gold, each full image is divided by its brightest-N-pixel
   mean. Cyan crosses show the exact normalization pixels beside the resulting
   reflectance image; verify that they belong to gold. QC measures reference
   variation across patterns. Without gold, skip normalization and retain raw
   MCT intensity. This choice is independent for each dataset tab.
4. Draw one shared on-MS ROI on the selected signal (raw intensity without gold,
   reflectance with gold), checking alignment across bands/patterns. Gold drift
   tracking is available only with a gold reference.
5. Apply paired Gaussian notches or an elliptical Gaussian low-pass, then a
   rolling-ball multiplicative flat-field correction to every selected image.
   Fourier can be bypassed explicitly. Parameter meanings appear next to the
   controls. Inspection-window settings affect only the spectrum preview.
6. Choose a shared rectangular analyte-free ROI, or select a fixed number of the
   brightest or darkest valid pixels in a chosen reference band for each pattern.
   All bands within that pattern share those coordinates and calculate their
   own reference mean from their own corrected signal values. With gold,
   A = −log10(R_corrected / R0); without gold,
   A = −log10(I_corrected / I_bg). No reflectance array is created without gold.
   Thin cyan crosses identify the selected positions in the current preview. Each
   image gets its own R0 and absorbance, followed by its configured pixelwise
   spectral baseline correction. Two references interpolate; more fit least
   squares.
7. Calculate baseline correction separately, compare absorbance before and after
   correction, and inspect individual pixel fits.
8. Inspect six stages with gold, or five without gold, using inferno. Different
   bands have independent scales; each band's input/Fourier/rolling stages
   share a scale, as do its two absorbance
   stages. Draw shared CNR background and target ROIs. Export all selected
   patterns and bands, including metadata, masks, QC, R0 and CNR arrays/tables.
   Gold-normalized exports include full-image normalization pixel coordinates.
   Raw-only exports omit reflectance arrays. Metadata records the signal basis.

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
The before/Fourier/rolling images share an input-signal scale. Use Process all
involved bands to commit the settings before calculating absorbance and CNR.

- Notch coordinates are `(fy, fx)` in cycles/pixel, unrelated to cm^-1. Their
  symmetric partners are added automatically. Sigma X and Sigma Y independently control the Gaussian
  widths, strength controls rejection depth, and protect radius passes low
  frequencies unchanged.
- Low-pass x/y cutoffs are half-amplitude frequency semi-axes. Equal widths
  give a circular mask. Lower widths smooth more strongly along that axis.
- Rolling-ball radius is spatial pixels; cap height is in input-signal units.
  Dark-feature mode estimates an upper background; bright-feature mode a lower
  background. Correction multiplies by median(background)/background.
- A rectangular analyte-free ROI must contain only finite positive values in every
  selected image. Extreme-pixel modes rank only finite positive signal,
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

## CNR and display contrast

Section 8 CNR uses numerical values clipped to the current display percentile
limits, before color mapping. The default 0–100 leaves finite values unchanged.
The percentile setting applies to every selected pattern/band; the actual bounds
follow each stage's shared display scale. No image-processing arrays are changed.
Changing percentiles requires recalculating CNR before exporting. In multi-folder
comparison, changing a folder's percentile automatically recalculates its CNR.

Clipping can suppress background variation and inflate CNR, so this is a measure
of the adjusted display, not an independent measure of acquisition quality.
Unadjusted CNR remains available alongside the adjusted value. `cnr_summary.csv`
and `metadata.json` record each pattern, band and stage, both CNR values,
percentiles, actual clipping bounds, adjustment method and validity status.

Each image has its own optional **Set lower limit to 0** switch, including raw
inspection, individual processing diagnostics, baseline inspection and timelapse.
Multi-folder comparison has an independent switch on each dataset image.
Selections are retained per plot within the current page session; changing one
plot does not change any other plot's scale.
It changes only color mapping: negative values saturate at the lowest color,
while numerical arrays, spectra, percentile-based CNR and unadjusted CNR remain
unchanged. If the display upper bound is nonpositive, a small positive bound is
used to keep the color scale valid. Turn the switch off to restore the normal
display range. Exported videos use the selected display scale.

## Pixel baseline inspection

Step 6 calculates absorbance and shows it alongside the corrected signal previews.
Continue to step 7 and click Calculate baseline correction to commit the
pixelwise fit. Step 7 shows before/after absorbance and the pixel inspector.
Reference-only bands have no corrected center image. Step 8 provides stage
comparison, CNR, timelapse, and export.

The pixel inspector has independent pattern and center-band selectors. Click
its absorbance image or enter zero-based crop-local x/y coordinates to inspect
the committed fit. The chart shows reference absorbances, the fitted line,
the baseline at the center, and the center absorbance before and after
subtraction. A table lists each reference's fitted value and residual. Two
references interpolate; additional references use unweighted linear least
squares. Invalid pixels are reported without substituting zero. Editing the
analyte-free selection hides these results until absorbance is recalculated.

Video stages follow processing order: raw, reflectance, Fourier, rolling ball,
absorbance before baseline, and absorbance after baseline.

## CNR display and pattern ranges

Section 8 calculates only CNR = abs(signal-background)/noise. Signal is the
target mean, background is the background mean, and noise is the background
sample standard deviation (ddof=1). The same finite-pixel intersection is used
across stages. Each image has a title followed by a separate parameter line.
CNR is displayed as an integer; signal, background, noise and absolute contrast
use scientific notation with two decimal places. These are display formatting rules only: calculations
and CSV exports retain full precision. Undefined values display as a dash.

In section 2, enter start and end pattern indices and click Select range to
replace the current selection with complete patterns in that inclusive range.
Incomplete and missing patterns are skipped. Empty or invalid ranges leave
the current selection unchanged; individual checkboxes remain editable.

Notch sigma X/Y are standard deviations in cycles/pixel along the frequency
axes. Equal values reproduce the circular notch; legacy `sigma` remains a
fallback for callers that omit an axis. Live previews include the signed
spatial signal removed by Fourier filtering (input minus filtered), with a
symmetric color range. Adding/removing notches and editing either width trigger
the same debounced preview as other filter parameters. Combined mode's removed
image includes low-pass filtering. This preview does not commit batch results.

Section 2 also provides Unselect all, which clears pattern checkboxes and
invalidates downstream steps until a new selection is confirmed.

## Import-stage raw spectrum viewer

After scanning, section 1 stays open so you can inspect the full raw spectrum
before assigning center/reference bands. Choose a discovered pattern and any
available preview wavenumber. Click the raw image or enter zero-based full-image
x/y coordinates. The plot and table include every available spectral CSV for
that pattern, sorted by wavenumber; the preview band is highlighted in orange.
Missing bands are listed, and differing image shapes are rejected. No spectral
interpolation, normalization, cropping, or registration is applied. Plot lines
only connect measured points. Inspection does not alter processing selections
or committed results. Use Assign centers and baseline bands to continue.

## Optional multi-folder comparison

In section 1, check Compare multiple folders in dataset tabs, then open the
multi-folder workspace. Add each folder (and optionally a dataset name) to
create a tab. Tabs retain their own processing state and can be switched at
any section; a folder that has not reached that section opens its latest
available step. The original single-folder interface remains available.

Center/reference mappings, gold-reference pixel count, QC thresholds,
Fourier/rolling-ball parameters, and analyte-free method/count synchronize across
tabs. Pattern selections, spatial ROIs, drift references, per-pattern analyte-free
reference bands, CNR ROIs, and display limits remain independent. Changes to
shared settings lock dependent steps in every affected tab until recomputed.
Each folder is processed using its own buttons; processing one folder does not
implicitly process the other folders.

After calculating CNR in every folder, open Final comparison. Select a common
stage and wavenumber, and independently choose each folder's pattern and display
percentiles. Each image has its own colorbar, CNR parameters and ROI outlines.
The page checks that committed shared settings agree before displaying results.
Export all datasets downloads one ZIP with a result archive per folder and a
JSON dataset/CNR summary. All datasets remain in local server memory; restarting
the server clears them, and reloading the workspace resets the browser tabs.

## Full-raw ROI absorbance spectrum

Section 1 includes an independent **ROI absorbance spectrum** panel after file
discovery. Select a pattern and preview wavenumber, then drag the cyan analyte
rectangle and green analyte-free rectangle on the full raw MCT image. The
preview band only assists selection; calculation reads every measured band
available in that pattern. Both rectangles use full-image coordinates with
exclusive upper bounds, and do not change the processing or analyte-free ROIs.
Changing the pattern clears both rectangles; changing a rectangle clears the
previous spectrum and disables export until recalculation.

For each band, `I` and `I_bg` are the respective ROI means, and
`A = -log10(I / I_bg)` (the ratio of means, not the mean of pixel absorbances).
The two plots show the raw mean signals and absorbance. No normalization,
baseline correction, registration or interpolation is performed. Non-finite
ROI pixels or non-positive means invalidate the corresponding absorbance;
invalid values appear as gaps, with a status in the table. Mismatched image
shapes and out-of-bounds ROIs are rejected. Missing bands are reported.

**Export CSV** includes measured wavenumber, `I`, `I_bg`, ratio, absorbance,
status, pattern, preview band, ROI pixel counts and both rectangles' coordinates.
Numeric exports preserve calculation precision. Color bar ticks use three
fixed decimal places.

ROI selection rectangles use opaque, unfilled 1 px dashed vector outlines,
including the final folder comparison. Import data shows ROI spectra as lines
without point markers; the separate full-raw single-pixel inspector is removed.

The Section 1 **Assign centers and baseline bands** button opens the existing
band editor inline. **Done · keep viewing spectrum** closes it without changing
sections. Section 2 remains available through the sidebar. The same mapping is
used for processing and spectrum annotations. Vertical dashed lines mark centers and their baseline references in the same
color per group, with colored wavenumber labels on the horizontal axis. Use the
center selector to inspect one center/reference group or all groups. Selected bands within the plotted wavenumber range are marked.

Optional Savitzky–Golay (SG) smoothing applies only to the ROI absorbance curve.
It defaults off, with an 11-band window and polynomial order 2. The window must
be odd, at least 3, and no larger than the number of measured bands; the order
must be non-negative and smaller than the window. SG requires finite absorbance
and evenly spaced, increasing wavenumbers. No missing bands are interpolated.
When enabled, the raw curve remains gray and the SG curve is black. Without SG, raw absorbance is black. CSV export retains raw absorbance and adds `absorbance_sg`,
SG settings, and the center/reference mapping. This smoothing does not alter
subsequent image processing or baseline correction.


Section 1 preview wavenumbers are restricted to selected centers available in
that pattern. The current selection is preserved when possible. With no
available selected center, the preview is disabled and prompts for a center;
the calculated spectrum still includes all measured bands, including references.

The ROI spectrum supports independent Fourier and SG switches, both off by
default. Fourier is a one-dimensional hard low-pass with a configurable cutoff
in cycles per sampled band (default 0.1, range >0 to 0.5). It reflects N−1 samples
on each side before the FFT, preserves frequencies at or below the cutoff, and
crops the inverse FFT back to the original samples. At 0.5 all frequencies pass.
When both switches are enabled, Fourier runs before SG. All enabled filters
require finite values and uniformly spaced spectral samples.

The main plot compares raw absorbance (gray) with the final output (black).
Fourier diagnostics separately show raw versus Fourier output before SG,
Fourier amplitudes before/after/removal, the cutoff and rejected frequency
region, and the removed component (raw minus Fourier output). FFT amplitudes
are |FFT| divided by the reflected sample count. CSV export includes raw,
Fourier, SG and final absorbance columns, along with the enabled filters and
settings. These filters do not alter later image processing stages.

ROI Fourier filtering also offers **Notch** and **Low-pass + notch** modes.
Enter one or more comma-separated notch centers in cycles/band (0 < f ≤ 0.5)
and a full width. Each notch rejects frequencies within center ± width/2;
zero frequency (DC) is preserved. Combined mode rejects the union of the
notches and frequencies above the low-pass cutoff. The frequency plot labels
each notch center and shades rejected ranges. The status reports how many FFT
bins were removed; very narrow notches may contain no sampled frequency bins.
CSV metadata includes the mode, notch centers and width. SG, if enabled, still
runs after the chosen Fourier filter.
