# QCL Processing Workbench

New here? Start with the [new-user quick start](QUICKSTART.md) for installation,
a first dataset, saving projects and troubleshooting. This page is the detailed
reference for the current ten-section interface.

Run `python ui/app_processing.py` from the repository in the Python 3.12 `qcl`
environment, or use `ui/launch_processing_macos.command` on macOS. The separate
interface opens at http://127.0.0.1:8766. The original `ui/app.py` remains intact.
Install the project with `python -m pip install -e '.[ui,dev]'` if needed.

On Windows, run `ui/setup_windows.bat` once, then
`ui/launch_processing_windows.bat`. For a standalone EXE with all runtime
dependencies included, follow [Windows packaging](../packaging/README.md).

## How the workflow works

1. Use the file chooser to select a stacks directory, a pattern directory, an
   acquisition directory with a stacks child, or spectral CSV files from one pattern. Wavenumbers come only from filenames
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
   MCT intensity. In multi-folder mode, Section 3 settings are shared by default;
   disable its sharing switch to configure datasets independently.
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
   image gets its own R0 and absorbance. Baseline correction is calculated
   separately in Section 7. Two references interpolate; more fit least squares.
7. Calculate baseline correction separately, compare absorbance before and after
   correction, and inspect individual pixel fits.
8. Inspect six stages with gold, or five without gold, using inferno. Every image has an independent colorbar calculated from its own values. Draw CNR background and target ROIs shared across stages within the
   dataset, or reuse the exact Section 6 analyte-free selection as background.
   Horizontal/vertical line profiles sample the same positions across stages.
9. Optionally build a timelapse of the selected patterns, or click **Skip Timelapse**.
10. **Export results:** choose a filename and download the reproducible project
   ZIP with selected inputs, parameters, metadata, masks, QC, R0 and CNR results.
   Gold-normalized exports include full-image normalization pixel coordinates.
   Raw-only exports omit reflectance arrays. Metadata records the signal basis.

The new processing path follows notebook 06's on-MS workflow. The original app
still provides its independent on-MS/out-MS workflow. This interface also
supports a common-scale timelapse across already processed selected patterns,
with an inclusive pattern range and optional QC-frame exclusion. Browser CSV
imports use file modification timestamps (`browser_last_modified`); original
creation times are unavailable. Local folder imports use creation times
when available, with modification-time fallback recorded.

## Scientific parameters and boundaries

### Optional stages and live preview

The Fourier and rolling-ball checkboxes start unchecked in a new UI session
and independently enable each stage. Imported projects and shared dataset
settings retain their saved enabled flags.
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
The before/Fourier/rolling images each use their own colorbar limits. Use Process all
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
separate local interface. `ui/uploads.py` handles file-chooser imports and ZIP
filenames; `ui/reproduction.py` handles project recipes and verification.
`uploads.js` and `line_profile.js` provide shared browser helpers.
No frontend package installation or remote hosting is
needed. The server serves only named frontend assets and binds to localhost.

Mutation requests run serially under a session lock and commit complete stage
results. Reconfiguring bands, crops, processing or R0 clears dependent numerical
results; the browser also locks downstream pages when inputs are edited.
This is a single-user in-memory session, not a persistent multi-user service.

## CNR and display contrast

Section 8 CNR uses numerical values clipped to the current display percentile
limits, before color mapping. The default 0–100 leaves finite values unchanged.
The percentile setting applies to every selected pattern/band; the actual bounds
follow each image’s independent display scale. No image-processing arrays are changed.
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
Reference-only bands have no corrected center image. Step 8 (Calculate CNR) provides stage comparison and CNR. After calculating
CNR, step 9 provides optional timelapse creation; Skip Timelapse goes directly
to step 10 (Export results). No video needs to be built to export results.

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

## Optional multi-folder comparison

In section 1, check Compare multiple folders in dataset tabs, then open the
multi-folder workspace. Choose a folder or spectral CSV files (and optionally a dataset name) to
create a tab. Processing ZIPs can also be imported and reproduced into tabs. Tabs retain their own processing state and can be switched at
any section; a folder that has not reached that section opens its latest
available step. The original single-folder interface remains available.

Sections 2, 3, 5 and 6 each have a workspace-wide sharing switch, visible when
multiple folder tabs exist. All four default on:

- Section 2: center/reference wavenumber mappings.
- Section 3: gold-reference choice, pixel count and QC thresholds.
- Section 5: Fourier and rolling-ball settings, including enabled flags.
- Section 6: analyte-free selection method and extreme-pixel count.

New folders inherit the current shared settings. Turning a switch off retains
current values and allows each folder to edit that group independently. Turning
it back on restores the settings last committed by the first folder to complete
that section (or the first available folder settings if none has completed it).
The switch state is reflected in every tab. Changes invalidate affected results
only when parameter values change; each folder must be recomputed separately.

Pattern selections, spatial ROIs, drift references, per-pattern analyte-free
reference bands, search bounds, CNR background source/ROIs and display limits
remain independent. No spatial selection is copied between folders.

After calculating CNR in every folder, open Final comparison. Select a common
stage and wavenumber, and independently choose each folder's pattern and display
percentiles. Each image has its own colorbar, CNR parameters and ROI outlines.
The page checks that committed settings agree only for groups whose sharing
switch is on. Different settings are allowed for groups switched off; comparison
still requires a common stage and wavenumber.
Export all datasets downloads one ZIP with a result archive per folder and a
JSON dataset/CNR summary. All datasets remain in local server memory; restarting
the server clears them, and reloading the workspace resets the browser tabs.

## Full-raw ROI absorbance spectrum

Section 1 includes an independent **ROI absorbance spectrum** panel after file
discovery. Assign center/reference bands first to enable a center-band preview.
Select a pattern and preview wavenumber, then drag the cyan analyte
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


## Reuse the absorbance reference for CNR

Section 6 commits the exact analyte-free coordinates when Calculate absorbance
succeeds. In Section 8, **Use Section 6 analyte-free selection as background**
(default off) reuses those saved coordinates for each pattern and band across
all stages. Rectangular selections appear as cyan dashed outlines; brightest/
darkest selections appear as the same thin cyan crosses used in Section 6.
Pixels are not re-ranked at different stages. A search rectangle for extreme
pixel selection is not itself used as the CNR background.

Select a target ROI that does not overlap the background pixels. Turning reuse
off clears the selection and requires a new manually drawn background rectangle.
Switching modes clears CNR and the target ROI. Upstream edits continue to require
recalculation. CNR exports record `background_source` (`manual` or `analyte_free`);
the existing per-image cell-free coordinate and mask exports identify the saved
background when reused. Multi-folder comparison preserves the source and markers.


## Section 8 line profiles

Choose **Horizontal** (default) or **Vertical**, click **Select line start / end**,
then click a start and end position on any stage images. The end snaps to the
selected axis; diagonal lines cannot be drawn. Changing direction clears the
existing line. A cyan dashed line with S/E labels appears at the same
crop-local coordinates on every stage. Each available image gets its own
profile underneath: horizontal position is distance from the start in pixels;
vertical values are the actual intensity, reflectance or absorbance for that
stage. Samples include both endpoints, are at most one pixel apart, and use
bilinear interpolation. Invalid contributing pixels create gaps. Display
percentiles and colorbar zero anchoring do not change profile values.

Changing the preview pattern or wavenumber retains the line and refreshes all
profiles. **Clear line** removes it. Upstream configuration changes clear it.
Line selection does not modify CNR regions, calculated CNR or processing arrays,
and remains independent between folder tabs.


Final comparison also provides a Horizontal/Vertical selector, line-selection
button and Clear line button beneath each dataset image. Each folder retains
its own line in crop-local coordinates, allowing for different image shapes and
feature positions. Changing stage, wavenumber or pattern refreshes its profile
with the selected dataset's values. Out-of-bounds saved lines are cleared.
The chart uses the same actual-value sampling and distance axis as Section 8.
Neither selecting nor clearing a line changes CNR or its ROI overlays.


## Reproducible project ZIP (format version 1)

Section 10 exports a self-contained project. Enter a **ZIP file name** before
downloading (default `qcl-processing.zip`). Final comparison has its own filename
field (default `qcl-folder-comparison.zip`). Chinese names are supported; an
omitted `.zip` is added, invalid filename characters are replaced, and a blank
name uses the default. The browser determines the download location.

Result CSVs use the descriptive filenames listed below. Metadata remains
compatible, and older project filenames are accepted on import. The ZIP also includes:

- `inputs/*.npy`: full, uncropped raw images as lossless float64 arrays. They
  cover selected patterns and involved bands only. These are the actual loaded
  numerical inputs, not a later reread of original files or their CSV formatting.
- `recipe.json`: complete effective parameters, spectral configuration, committed
  crop positions and reference selections, QC and CNR configuration.
- `environment.json`: Python/package versions, Git commit/dirty status when
  available, and SHA-256 fingerprints of numerical processing source files.
- `manifest.json`: format version and size/SHA-256 inventory for every other file.
- `reproduction_report.json`: verification report when exporting a reproduced
  session whose numerical results have not subsequently been recalculated.

In the standalone Section 1 interface, choose **Import processing ZIP**, select
a previously exported project, and click **Reproduce processing**. The original
source directory is not needed. The importer validates the package, builds an
isolated session, reruns Sections 2–8 using the currently installed code, then
replaces the active session only after successful processing and verification.
Checksum/schema/processing failures leave the prior session intact. Numerical
mismatches are reported and the recomputed results remain inspectable.

Saved full-image gold pixels, crop positions and crop-local analyte-free pixels
are reused without rerunning automatic selection or drift tracking. The signal
values, reference means, Fourier/rolling-ball stages, absorbance, baseline and
CNR are recalculated. Saved result arrays are used only as verification targets.
The report checks shapes, invalid-value positions, arrays/masks, reference
levels, R0, QC and CNR. It distinguishes exact agreement, agreement within
`rtol=1e-10, atol=1e-12`, and mismatches, with numerical error statistics.
Environment differences are reported separately; no code from the archive is executed
and no dependencies are installed automatically.

The UI restores numerical controls and opens Section 10's verification report
(or Section 8 if the package did not contain CNR). A JSON report can be
downloaded. Before exporting, recompute any edited processing/CNR settings.

The standalone importer accepts one project ZIP. The multi-folder workspace
accepts one or more project ZIPs and the complete multi-dataset export ZIP;
its contained projects are reproduced into separate tabs. Dataset names are
retained from multi-dataset bundles. Sharing switches, Section 1 spectra, line
plots, video settings and per-image display preferences are not restored. Previously
exported ZIPs without a manifest/full inputs cannot be replayed; re-export from
a processed session using this version. Uploads are limited to 1 GiB compressed
and 4 GiB expanded. Archive members are never extracted to arbitrary paths.


## File chooser imports

Section 1 and the multi-folder workspace offer **Choose folder…**, which opens
an operating-system directory chooser on the computer running the server.
A pattern, stacks or acquisition folder is read directly from its original
location, with no upload or 1 GiB folder limit. Keep the source available for
the duration of the session. Local folder imports preserve the existing
creation-time/modification-time fallback behavior. Cancelling the chooser leaves
the previous selection unchanged; failed discovery leaves the current session intact.

Alternatively, **Spectral CSV files** selects all required bands from one pattern.
The browser streams a metadata header and file bytes; the server writes them to
a session-owned temporary directory in chunks of at most 1 MiB. No aggregate
1 GiB CSV limit applies. Relative names and declared sizes are validated, and
incomplete uploads are rejected. CSV selection cannot access unselected siblings.
Timestamps use each file's `lastModified`, recorded as `browser_last_modified`.
Original files are untouched. Large datasets still require disk space and memory
for numerical processing; direct folder access avoids an extra input copy.

ZIP requests are also streamed to temporary disk, with incremental checksums
and disk-backed nested project archives. The existing 1 GiB compressed / 4 GiB
expanded ZIP validation limits remain in force. Numerical reproduction still
loads the selected image arrays for processing.

In multi-folder mode, select **Processing project ZIP** to reproduce a project
or an entire multi-dataset ZIP into tabs. Each bundle is fully reproduced
before any of its tabs are registered. Multiple selected ZIP files are imported
sequentially; earlier successful ZIPs remain if a later ZIP fails. Imported
recipes are preserved rather than silently overwritten by workspace settings.
If enabled sharing groups differ, turn off those groups' switches or explicitly
reconfigure and recalculate before Final comparison.

## CNR and timelapse color maps

Sections 8 and 9 have independent **Color map** selectors: Inferno (default),
White → black (RI), Black → white, Black → magenta, Black → yellow, and
Black → blue. The monochrome maps are linear ramps; white-to-black matches the
inverted RI scale. Section 8 applies its selection to all stage images and
refreshes immediately without invalidating CNR or changing ROIs and profiles.
Changing the timelapse map rebuilds an existing video preview. Preview color bars
and exported MP4 color bars use the selected map. Color mapping does not change
arrays, percentile limits, or CNR. These display preferences are local to each
dataset tab and are not restored from project ZIPs.

Timelapse timestamps use the earliest available file timestamp across all
 discovered bands of each pattern, independent of the displayed wavenumber.
Each frame's **dt** is its pattern start minus the start of the immediately
preceding numbered pattern (pattern p−1), including patterns outside the video
range or excluded by QC. Missing predecessor timestamps produce a dash; the
first pattern also has no dt. **elapsed** is relative to the first displayed
pattern start, preserving acquisition pauses. Both are displayed to the nearest
second; playback FPS remains independent. File timestamp sources retain the
creation-time / modification-time fallback rules described above. Only metadata
available in the current dataset can be used (reproduced ZIPs may contain a
subset of the original bands and patterns).

## Temporal signal diagnostics

Section 3 shows **I_goldref vs. pattern** after gold normalization, for the
currently selected **Preview wavenumber**. It uses the full-image gold-pixel
means actually used to calculate reflectance. Editing normalization settings
hides the old graph until normalization is recalculated.

Section 6 shows **R₀ vs. pattern** and **Median R vs. pattern**, also following
Preview wavenumber. R₀ is the committed corrected-signal mean over the exact
cell-free selection. It appears after Calculate absorbance and is cleared when
that selection or upstream processing changes. Median R defaults to the on-MS
crop before Fourier/rolling-ball correction; a selector switches to the full
reflectance image or the corrected on-MS image. The median includes all finite
pixels in the selected image region, including negative values, without display
clipping or color-map transformations. Without gold, the corresponding graphs
are labeled I_bg and Median I and use raw-intensity signal units.

Each curve includes all selected patterns, including QC-flagged ones, in numeric
pattern order. The horizontal axis uses actual pattern indices, preserving gaps
in selection. Expand the values table below each panel to inspect the numbers.
Changing the preview pattern does not change these across-pattern curves.

## Image orientation, PNG downloads and background preview

The Horizontal flip and Vertical flip controls are in Section 8 directly below
Calculate CNR for all images. They apply only to that section's heatmaps and
ROI/point/line overlays. Final comparison has its own independent controls.
Other processing sections and timelapse/video exports retain normal orientation. Pointer selection is mapped
back to original coordinates. Plots and colorbar text keep their normal
orientation. Numerical arrays, CSV exports and saved ROI coordinates retain
acquisition orientation. Each dataset tab keeps its own Section 8 flip settings;
project ZIPs do not restore them.

Each available Section 8 stage image has a Download current image · PNG button.
The PNG includes the pattern/band/stage title, displayed CNR and background
parameters, display limits, current orientation, color scale and ROI/line
overlays. When a line profile is present, its plot and sampling-position details
are included below the image in the same PNG. Text wraps and the export grows
vertically to fit all information. The profile keeps normal axes and S-to-E
ordering even when the heatmap is flipped. Selecting a background ROI immediately shows
A_bg and sigma_bg (sample standard deviation, ddof=1), before selecting a target
or calculating CNR. Reusing the Section 6 reference also previews these values.
Background preview uses the same common finite pixels and percentile clipping
as final CNR. It does not commit a CNR result or unlock result export.

Stage CSV filenames now describe their contents:

| Previous name | Exported name |
| --- | --- |
| raw.csv | Intensity_raw.csv |
| reflectance.csv | Reflectance_gold_normalized.csv |
| fourier.csv | Signal_Fourier_filtered.csv |
| rolling.csv | Signal_flat_field_corrected.csv |
| absorbance.csv | Abs_uncorrected.csv |
| baseline.csv | Abs_baseline_corrected.csv |
| linear_baseline.csv | Abs_fitted_linear_baseline.csv |
| background.csv | Rolling_ball_background.csv |
| gain.csv | Flat_field_gain.csv |

Masks and reference coordinate filenames are unchanged. The importer accepts
both these names and previous project ZIP names.


## Image pixel axes

All processing heatmaps show X (pixel) and Y (pixel) axes, including raw ROI
inspection, normalization, cropping, live processing diagnostics, baseline
inspection, Section 8, timelapse and final folder comparison. Pixel centers are
zero-based (0 through width−1 / height−1); cropped images use crop-local
coordinates. FFT images show their array pixel indices alongside the existing
frequency annotations. Spectral and line-profile plots retain their physical
axes. Image axes use the numerical array dimensions, not the enlarged preview
PNG resolution, and adapt to the display size. Section 8 flips reverse tick
positions while keeping text readable and original pixel coordinates intact.
Section 8 PNG downloads and MP4 exports include the same pixel axes.


## Independent image colorbars

Every processing image uses only its own finite pixel values to calculate the
selected percentile limits. This applies to previews, baseline before/after,
Section 8 and Final comparison (by default). Timelapse/MP4 uses a single
range across included patterns at the selected wavenumber and stage.
Final comparison alone can optionally share limits across folders for the same
selected stage; before/after stages are never pooled together. At 0–100 the limits are that image's
minimum and maximum, apart from the explicit per-image zero-limit switch.
Signed-difference diagnostics retain a symmetric range based on their own data;
transmission masks retain their dimensionless 0–1 scale.

CNR clipping and background previews use each individual stage's range. New
projects record `cnr_contrast.scale_policy = per_image`. When an old ZIP is
imported, historical CNR is first verified under its saved grouped-scale rule;
current CNR is then recalculated with independent image scales. The verification
report states this migration. Processing arrays and unadjusted CNR are unchanged.

## Final comparison image tools

Final comparison includes Horizontal flip and Vertical flip controls for all
currently compared images, independent of the individual dataset tabs. Image,
ROI and line overlays flip together; pixel tick positions follow the original
coordinates and line selection maps clicks back to those coordinates.

The Color map selector offers the same six maps as Section 8 and works with
independent image colorbar limits. Color maps and flips do not alter
CNR or the numerical arrays.

Each available dataset image has Download current image · PNG. It exports the
dataset name, pattern, wavenumber, processing stage/basis, CNR parameters and
pixel counts, active color limits/map, pixel axes and ROI/line overlays. The
dataset's current line profile and sampling information appear beneath the
image in the same PNG. Pending profiles are calculated before export, and the
plot keeps normal axes when the image is flipped.


Line-profile S/E labels keep their normal text orientation when either or both
flip controls are enabled. Their positions follow the selected image pixels.
This applies to Section 8, Final comparison, newly drawn lines, existing lines
and downloaded PNGs.


Final comparison's **Use the same colorbar limits across folders · current stage
only** defaults off. Automatic limits use the selected stage and wavenumber
at each folder's selected pattern. Manual min/max values override these limits;
**Use selected images’ min / max** restores automatic selection. Stage or
wavenumber changes reset to automatic limits. Automatic limits follow pattern
changes, while manual limits stay fixed. Per-folder percentiles and zero-limit
controls are disabled while sharing is on and restored when it is off. Shared
limits affect only the comparison display and downloaded PNGs, not processing
arrays, CNR or the independent stage scales in Section 8.


Section 9 uses one colorbar range for the entire video. At the default 0–100
percentiles, its bounds are the finite minimum and maximum across the included
patterns for the selected wavenumber and processing stage. Patterns outside the
video range, unselected patterns, QC-excluded frames, other bands and other
stages do not contribute. Custom percentiles apply to the combined frame values;
the explicit zero-limit switch can still set the lower display bound to zero.
The preview and exported MP4 retain the same limits on every frame.
