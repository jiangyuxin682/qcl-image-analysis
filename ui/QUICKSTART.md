# Processing Workbench: new-user quick start

This guide covers the current ten-section interface. For numerical definitions
and detailed controls, see the [processing reference](README_PROCESSING.md).

## 1. Start the application

**Standalone Windows app:** extract the entire application distribution ZIP,
keep `QCL Processing.exe` next to `_internal/`, and double-click the EXE.
The controller opens the workbench in your browser. No Python installation is
needed. Use the controller's **Quit** button when finished.

**From source:** install Python 3.12, obtain the complete repository, then run:

| Platform | Run once | Run each time |
| --- | --- | --- |
| macOS | `ui/setup_macos.command` | `ui/launch_processing_macos.command` |
| Windows | `ui/setup_windows.bat` | `ui/launch_processing_windows.bat` |

For an existing Python 3.12 environment, run these commands from the repository root:

```bash
python -m pip install -e ".[ui]"
python ui/app_processing.py
```

Open <http://127.0.0.1:8766> if necessary. Keep the terminal or desktop controller
running. The standalone app may choose another port if 8766 is occupied; use
its displayed address. The original app on port 8765 is a different interface.

## 2. Import your first dataset

In Section 1, choose **Data folder** and select your `stacks` folder, one pattern
folder, or an acquisition folder containing `stacks`. A typical layout is:

```text
acquisition/
  stacks/
    pattern0/
      lineScan_1675_0invcm.csv
      lineScan_1725_0invcm.csv
      lineScan_1775_0invcm.csv
    pattern1/
      lineScan_1675_0invcm.csv
      lineScan_1725_0invcm.csv
      lineScan_1775_0invcm.csv
```

Wavenumbers are read from `lineScan_<integer>_0invcm.csv` filenames. Only matching
spectral CSV files are sent to the local server. Your original files are unchanged.
Alternatively, choose **Spectral CSV files** and select all needed bands from
**one pattern**. Files you do not select cannot be discovered automatically;
use folder import to include multiple patterns or all bands.

For a saved processing project, use the ZIP workflow below instead. An
application distribution ZIP or an arbitrary ZIP of CSV files is not a
processing project ZIP.

## 3. Complete the processing sections

| Section | What to do |
| --- | --- |
| **1 · Import data & inspect full spectrum** | Import data. Use **Assign centers and baseline bands** to enable a center-band preview. Optionally draw analyte and analyte-free rectangles to inspect the full measured ROI absorbance spectrum. Its optional Fourier/SG filters affect this spectrum only. |
| **2 · Choose center wavenumbers and baseline references** | Assign each center at least two distinct references that bracket it. Select complete patterns, individually or with an inclusive range. All center and reference bands are processed. |
| **3 · Calculate reflectance** | Choose whether gold is present. With gold, check that the marked brightest pixels actually lie on gold. Without gold, retain raw intensity. |
| **4 · Select the on-MS region** | Draw the crop and check its placement across selected patterns/bands. Optional gold drift tracking is available with gold normalization. |
| **5 · Fourier and flat-field correction** | Choose filter parameters, or bypass either stage. Preview changes affect the current image; click **Process all involved bands** to commit them for the dataset. |
| **6 · Calculate absorbance** | Select an analyte-free rectangle, or brightest/darkest pixels in a reference band. Check the marked positions, then calculate absorbance. The exact selected pixels are saved. |
| **7 · Baseline correction** | Calculate the pixelwise spectral baseline. Inspect a pixel's fit and compare absorbance before/after correction. |
| **8 · Calculate CNR** | Draw the background, or enable **Use Section 6 analyte-free selection as background**. Draw a non-overlapping target ROI and calculate CNR for all images. Optional line profiles are described below. |
| **9 · Timelapse** | Optionally select a stage, band, frame range and playback settings to create a video. **Skip Timelapse** proceeds to export. |
| **10 · Export results** | Enter a ZIP filename and download the project ZIP. A video is not required. |

Upstream edits invalidate dependent results. Recalculate the affected sections
before exporting. Check the selected reference pixels and ROIs rather than
assuming the brightest/darkest pixels identify the intended material.

CNR defaults to the full 0–100 percentile range. Changing display percentiles
also changes the **adjusted CNR**, so recalculate after a change; unadjusted CNR
is retained for comparison. **Set lower limit to 0** changes only the color map.

### Draw a line profile

In Section 8, choose **Horizontal** (default) or **Vertical**, click
**Select line start / end**, and click two positions on an image. The endpoint
snaps to the selected axis. The same dashed line appears across all stages,
each with a profile of its own numerical values.

The horizontal axis is distance from the start in **pixels**, not physical
length; the vertical axis is intensity, reflectance or absorbance for that
image. Display clipping does not change these values. Use **Clear line** to
remove it. Line selection does not change the CNR regions.

## 4. Compare multiple folders

In Section 1, enable **Compare multiple folders in dataset tabs** and open the
workspace. Add each dataset using its folder or CSV chooser, or choose
**Processing project ZIP** to restore saved projects into tabs. The ZIP chooser
also accepts multiple projects or one complete multi-dataset export.

Process each tab. With more than one tab, sharing switches appear in:

| Section | Shared by default |
| --- | --- |
| 2 | Center and reference wavenumber mappings |
| 3 | Gold-reference choice, pixel count and QC thresholds |
| 5 | Fourier and rolling-ball parameters and enabled flags |
| 6 | Analyte-free selection method and brightest/darkest pixel count |

The shared source is the first folder to complete the relevant section.
Turn off a group's switch to use independent parameters. Re-enabling it applies
that source folder's last committed settings; affected folders need recalculation.
**Spatial selections are not shared between folders:** crops, analyte-free
rectangles, search areas, selected pixels and CNR ROIs remain independent.
Section 6 reference-band choices also remain per-pattern, per-folder.

After all folders have current CNR results, open **Final comparison**. Choose a
common stage and wavenumber; set each folder's pattern and display range
independently. Each image has its own color scale. Draw horizontal/vertical
line profiles independently for each folder, allowing for different image sizes
and feature positions.

Imported projects retain their saved settings. If they disagree with an enabled
sharing group, disable that group or deliberately align and recalculate the
settings before comparison. A common stage and wavenumber are still required.

Enter a filename beside **Export all datasets** to download one outer ZIP
containing a project ZIP per dataset and a dataset summary.

## 5. Save and reproduce a project

In Section 10, edit the ZIP filename before downloading. The default is
`qcl-processing.zip`; multi-folder export defaults to `qcl-folder-comparison.zip`.
Chinese names are supported. The app adds `.zip` when needed and replaces
characters that cannot be used in filenames. Leaving the name blank uses the
default. Your browser controls the download location and duplicate-name handling.

A project includes result CSVs, masks, QC/CNR tables, raw numerical inputs for
**selected patterns and involved bands**, the effective processing recipe,
saved reference/crop coordinates, and environment information. It does not
preserve the original CSV formatting or include unselected acquisition data.

To reproduce a single project:

1. Open Section 1 and choose **Import processing ZIP**.
2. Select the saved project and click **Reproduce processing**.
3. Review the verification report, normally in Section 10. It reports exact
   agreement, agreement within tolerance, or numerical differences.

The original data directory is unnecessary. The app verifies the archive and
recalculates with the currently installed code. Saved gold/analyte-free pixels
and crop positions are reused, rather than selected again. Different software
environments can produce differences; review the report before treating a
reproduction as equivalent. The archive does not install software or run code.

For an entire multi-folder export, import it through the comparison workspace.
The standalone importer accepts one dataset project, not the outer comparison ZIP.
ZIPs exported by older versions without full inputs and a manifest cannot be
reproduced; re-export them from a processed session with this version.

Reproduction restores numerical processing, not every screen setting. Section 1
spectra, drawn line profiles, video settings, sharing switches and per-image
display preferences are not restored. Download spectrum CSVs and videos
separately if needed. See the [format reference](README_PROCESSING.md#reproducible-project-zip-format-version-1)
for the verification details.

## Common problems

| Symptom | What to check |
| --- | --- |
| No bands found | Check the filename convention and selected folder. With CSV import, explicitly select every needed file. |
| Section 1 preview is unavailable | Assign at least one center band available in the selected pattern. The spectrum itself uses all measured bands. |
| A pattern cannot be selected | It is missing a required center/reference band. Adjust the mapping or choose a complete pattern. |
| Later sections are locked | Finish or recalculate the preceding section after parameter edits. A Section 5 live preview does not commit processing. |
| CNR cannot be calculated | Select both background and target; they must not overlap. The background needs enough valid pixels and nonzero variation for a defined CNR. |
| Final comparison is blocked | Calculate current CNR in every tab; resolve enabled sharing-group conflicts and select a common stage/band. |
| Import exceeds limits | Uploads are limited to 1 GiB; processing ZIPs also have a 4 GiB expanded limit. Use a smaller selected dataset/project. |
| Source installation cannot export MP4 | The source app needs an available FFmpeg executable. The standalone Windows distribution includes it. Timelapse can be skipped. |
| A session disappears after restart/reload | Sessions are held in server memory and workspace tabs are not persisted. Import an exported project ZIP to reproduce the work. |

Export before quitting or reloading; the workbench has no automatic persistent
project save. Keep acquisition files and downloaded projects in your normal
research storage, or the checkout's ignored `data/` and `outputs/` directories.
