# QCL Processing Workbench: from first import to export and reproduction

Start with the [macOS / Windows installation guide](INSTALLATION.md). This guide follows the current ten-section interface. For algorithms, detailed parameters, and archive structure, see the [Processing reference](README_PROCESSING.md). Bold control names correspond to the interface.

## Before you start: terminology

| Term | Meaning |
| --- | --- |
| Dataset / folder / data tab | One dataset; each occupies a tab in the multi-folder workspace |
| Pattern | A group of images from one scan/time point, not a wavenumber |
| Wavenumber (cm⁻¹) | Spectral coordinate identified from the CSV filename |
| Center wavenumber | A target band to analyze; you can select multiple centers |
| Reference wavenumber | A spectral band used for baseline correction |
| ROI | A rectangular region of interest selected on an image, in pixel coordinates |
| On-MS ROI | The sample region cropped for subsequent processing |
| Analyte-free region | A spatial reference without the target analyte, used for absorbance |
| CNR background / target | Regions used to measure background variation and target signal |
| Image stage | Raw, after Fourier, after rolling-ball, absorbance, after baseline, etc. |

Spectral reference wavenumbers, the gold reference, and spatial background ROIs serve different purposes. Choose them according to your experiment. The software does not automatically determine whether a bright region is gold or whether a region is analyte-free.

## 1. Prepare and import data (Section 1)

Prepare raw CSVs in a structure like this. These numbers illustrate naming; they are not required bands:

```text
my_acquisition/
  stacks/
    pattern0/
      lineScan_1700_0invcm.csv
      lineScan_1725_0invcm.csv
      lineScan_1750_0invcm.csv
    pattern1/
      lineScan_1700_0invcm.csv
      lineScan_1725_0invcm.csv
      lineScan_1750_0invcm.csv
```

Each CSV must be a non-empty, comma-separated 2D numeric matrix without column headers, row labels, NaN, or infinity. Wavenumbers come from `lineScan_<integer wavenumber>_0invcm.csv` filenames. Selected images must satisfy the processing pipeline's matching-dimension requirements; do not mix scans of different dimensions in one dataset.

1. Start the app and open **Import data & inspect full spectrum**.
2. Set **Input type** to **Data folder**. Use the folder chooser to select an acquisition, stacks, or single-pattern folder.
3. Click **Import files and detect wavenumbers**. Check the detected patterns and bands.
4. Alternatively, choose CSV input and select **all required bands from one pattern** together. The browser cannot read unselected neighboring files. Do not combine multiple patterns through this input method.

Folders are read from local disk; selected CSVs are copied to local temporary storage. Processing does not overwrite the originals, but source files must remain available while you work. No external website upload is needed.

Optionally, draw analyte and analyte-free ROIs to inspect the full spectrum, and use **Assign centers and baseline bands** to select bands. The spectrum preview's 1D Fourier / Savitzky–Golay controls affect only the spectrum preview, not the 2D image filtering in Section 5. First-time users can proceed with the main workflow below.

## 2. Select centers and baseline references (Section 2)

1. Select the center wavenumbers you want to analyze.
2. For each center, decide whether to enable **Apply baseline correction**.
3. If enabled, select at least two distinct reference bands bracketing the center, excluding the center itself. Two references interpolate; additional references use pixelwise linear fitting.
4. If suitable reference bands are unavailable, disable baseline correction for that center. No reference bands are then required, and you can still calculate absorbance and CNR.
5. Select the patterns/range to process and submit the configuration. Patterns missing required bands cannot be used with that configuration.

The processing set includes all centers and their references. Preview pattern/wavenumber controls change the preview only; they do not replace the batch-range configuration.

## 3. Decide whether to normalize to gold (Section 3)

Under **Gold patch reference**, explicitly indicate whether the images contain a gold reference.

- **Yes**: the mean of the N brightest pixels in each full raw image becomes its gold reference for relative reflectance. Verify the marked pixels are actually on gold. Set N and QC thresholds for your data, then calculate.
- **No**: skip reflectance normalization and continue using raw intensity. Do not select Yes merely to advance the workflow.

Absorbance can still be calculated without gold. Section 6 uses each corrected image's own analyte-free intensity as the denominator.

## 4. Select the processing region (Section 4)

Drag an **on-MS ROI** covering the sample region to analyze. Switch previews to check that the region is appropriate across selected bands and patterns, then commit it.

The ROI is reused within the dataset; different folders can use different regions. Coordinates are pixels, not micrometers. Read the detailed reference and inspect tracking before enabling gold drift tracking; you can leave it off for your first analysis.

## 5. Fourier and rolling-ball (Section 5)

**Enable Fourier** and **Enable rolling-ball** both default off. Enable either as appropriate and inspect the preview. Fourier controls frequency-domain filtering; rolling-ball performs flat-field correction. Parameters suitable for one dataset are not necessarily suitable for another.

Once satisfied, click **Process all involved bands**. Complete this step even when both optional corrections are disabled. Previewing alone does not commit the batch processing. Wait for completion before moving on.

## 6. Calculate absorbance (Section 6)

1. Choose an analyte-free reference method: a manually drawn ROI, or brightest/darkest pixels.
2. For the manual method, select a region without the target analyte. For an extreme-pixel method, choose the reference band and pixel count, then inspect the marked positions. Within each pattern, those positions are reused across bands, but each image calculates its own reference mean.
3. Calculate absorbance and inspect the image and reference mean.

With gold, A = −log₁₀(R<sub>corrected</sub> / R₀). Without gold, A = −log₁₀(I<sub>corrected</sub> / I<sub>bg</sub>). The denominator is the current image's spatial reference, not a reference wavenumber from Section 2.

If all centers have baseline correction disabled, use **Continue to CNR**; Section 7 is marked **Skipped**. Otherwise proceed to Section 7.

## 7. Baseline correction (Section 7)

Click **Calculate baseline correction**, compare before/after images, and inspect individual pixel fits as needed.

Only centers enabled in Section 2 produce after-baseline images. Disabled centers retain their original absorbance, without a fabricated after-baseline result. Mixed configurations process only the enabled centers.

Before/after colorbars are independently calculated from their images by default. Compare numerical values and ticks, not just apparent brightness.

## 8. CNR, image inspection, and downloads (Section 8)

1. Select the background by drawing an ROI or reusing Section 6's analyte-free pixels.
2. Background statistics A<sub>bg</sub> and σ<sub>bg</sub> appear once the background is selected, before a target ROI is required.
3. Select a target ROI without overlapping the background. Check the valid pixel counts.
4. Click **Calculate CNR for all images** and wait for results.

CNR uses the target mean, background mean, and background standard deviation. Insufficient valid background pixels or zero background standard deviation do not give a valid CNR. Recalculate after changing upstream parameters or ROIs.

- Each stage has an independent colorbar and X/Y pixel axes. Default percentiles are 0–100.
- Changing display/CNR percentiles affects adjusted CNR. **Set lower limit to 0 · display only** changes the display only.
- **Horizontal flip / Vertical flip** change display orientation, not raw values. Line endpoints move with the image while S/E lettering remains readable.
- For **Select line start / end**, choose Horizontal or Vertical, then click the start and end to inspect the line profile. Distance is in pixels.
- **Download current image · PNG** saves the current image and its information/parameters. A complete line profile is included when present.

## 9. Timelapse (Section 9, optional)

Select the stage, wavenumber, pattern range, and frame rate, then build and inspect the preview. Use **Skip Timelapse** if no video is needed.

One colorbar range applies to the entire video. At default percentiles, limits use the global minimum and maximum across **all included patterns at the selected wavenumber and stage**. Changing stage or wavenumber establishes a new range; before/after-baseline stages are not mixed. Percentile limits also use the included video data.

Video timing depends on source-file timestamps, which copying can change; check against your acquisition records. MP4 export requires FFmpeg; see the [installation guide](INSTALLATION.md). Download videos separately: they are not automatically included in the processing ZIP.

## 10. Export and retain raw data (Section 10)

Enter a ZIP filename and open the export-content options. **Required reproduction settings and selections always remain included.** Raw arrays, stage CSVs, auxiliary arrays, and result tables are selectable.

| Export choice | Contents and purpose |
| --- | --- |
| Lightweight reproducible settings (default) | Required processing settings, selections, verification information, and default summary tables; no embedded full raw arrays or large stage image matrices |
| Complete reproducible project | Raw input arrays and all optional outputs, suitable for archiving without the original input directory; potentially large |
| Custom export | Select raw arrays, stage CSVs, auxiliary arrays, and tables; required items cannot be deselected |

Stage CSVs contain numeric matrices. Download PNGs using the corresponding image button. Line profiles, videos, and complete display state are not automatically restored from the project.

**Keep matching original data with a lightweight ZIP: the ZIP alone is insufficient for later recalculation.** Projects containing raw inputs can reproduce selected patterns/bands using those embedded inputs. Retain raw data, the project ZIP, software version, and any needed PNG/MP4 files. Confirm downloads finish before exiting.

## 11. Reopen a project or apply its settings to new data

Choose a project ZIP under **Import processing ZIP** in Section 1, or under **Add a dataset** in the multi-folder workspace.

### Reproduce the original analysis

1. Select **Reproduce original processing**.
2. If the project includes raw inputs, select **Raw images inside the ZIP**.
3. For a lightweight project, select **Choose local raw data folder** or **Choose raw CSV files · one pattern** and provide matching originals.
4. Start import/reproduction and wait while Sections 2–8 are recalculated using the saved parameters and ROIs.
5. Inspect the verification report rather than relying on the appearance of an image.

Raw inputs are checked for pattern, wavenumber, dimensions, and numeric fingerprint. Substituting different data is not reproduction. **exact** means an exact match; **within_tolerance** means agreement within the recorded tolerance; **mismatch** means disagreement; **unverified** means verification was incomplete. Inspect the report and environment differences for the latter two outcomes.

Project import limits are **1 GiB compressed / 4 GiB expanded**. Selecting external raw data does not bypass the ZIP upload limit for an older large project. If the original session remains available, export a new lightweight project. Legacy result-only ZIPs without reproduction metadata cannot restore the full processing workflow.

### Apply saved parameters to another dataset

Select **Apply saved settings to new raw data** and provide a new folder or CSV inputs. This reuses band mappings and processing parameters, without reusing old crops, spatial ROIs, selected pixels, or results for a new sample. New data must contain the required bands. After import, start at Section 3 to review normalization, choose new regions, and process through CNR.

## 12. Compare multiple folders

Enable **Compare multiple folders in dataset tabs** in Section 1. In the workspace, use **Add a dataset** to import each dataset. Complete the required processing and CNR in each tab.

Double-click a tab name to rename it. Its **×** button removes that dataset from the current session after confirmation; it does not delete original disk files. The tab's `n/10` indicates its current Section, not necessarily its highest completed processing step.

### Default parameter sharing

| Section | Shared settings | Default |
| --- | --- | --- |
| 2 | Center/reference wavenumbers and baseline configuration | Off |
| 3 | Gold normalization parameters | On |
| 5 | Fourier / rolling-ball parameters | Off |
| 6 | Analyte-free selection method and related parameters | On |

Sharing switches apply across the workspace; spatial ROIs remain independent. Disable the corresponding switch when folders need different settings. Re-enabling sharing uses the first folder that completed that Section and may require recalculation in other folders.

### Final comparison

1. Calculate CNR in each tab, then open **Final comparison**.
2. Select the shared **Image stage**.
3. **Wavenumber selection** defaults to **Choose wavenumber per folder**. Choose each folder's band and pattern on its card. Alternatively, use the common-wavenumber mode.
4. Click **Refresh comparison**.
5. Colorbars are independent by default. For a common scale, enable **Use the same colorbar limits across folders · current stage only**. Automatic limits use the current compared images' minimum and maximum. Enter manual limits if needed, or select **Use selected images’ min / max** to restore automatic limits.
6. Use display flips, each folder's line profile, and PNG downloads as needed. **Export all datasets** creates a multi-dataset project, with lightweight contents by default.

Shared limits apply only to the currently selected stage and images. They do not include other stages or change CNR.

### If comparison images do not appear

Read **Why comparison is blocked**. It identifies the folders and Sections with conflicting enabled sharing settings, displays the relevant parameters, and provides **Open Section** buttons. If differences are intentional, turn off the corresponding sharing switch. Otherwise, unify the settings and recompute affected steps. Incomplete or outdated CNR results must also be resolved.

If there is no common wavenumber, use per-folder selection. A center with baseline correction disabled has no after-baseline image; choose **Absorbance before baseline** or a center with completed baseline correction.

Import multi-dataset ZIPs through the workspace. When folders require different external raw-data directories, extract the outer ZIP and import each dataset's inner project ZIP separately, selecting its matching raw directory. Imports do not restore every display setting, sharing switch, line profile, or video; review these again.

## 13. Before ending an analysis

- Confirm the detected patterns, bands, centers, and baseline settings match the experiment.
- Inspect gold, on-MS, analyte-free, and CNR selections.
- Recalculate after upstream changes and check CNR validity and background statistics.
- Know which stage, band, and independent/shared color scale you are comparing.
- Confirm the ZIP download completed, matching raw data is retained for lightweight projects, and needed PNG/MP4 files are saved separately.

For setup or launch errors, see the [installation guide](INSTALLATION.md). For algorithms and exported-file details, see the [Processing reference](README_PROCESSING.md).
