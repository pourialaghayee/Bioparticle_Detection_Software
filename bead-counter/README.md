# Polimi Bead Counter

A Python desktop app for finding and counting bead appearances in an HDF5 microscope movie. Load a recording, inspect every frame with boxes, IDs and brightness values, and save a combined image and count tables.

This repository contains **code and setup instructions only**. Provide your own `.h5` recording. Experimental data, generated results, images, local Python environments and native binaries are excluded from Git.

## Requirements

- **Python 3.12 recommended**, including `pip` and `venv`. Setup accepts newer Python versions, but this release was verified with Python 3.12 on Linux.
- A desktop session for the GUI; command-line processing can run without opening a window.
- Internet access for the first dependency installation. Later launches reuse the local environment.
- Free disk space for your recording and optional boxed TIFF exports.

Windows and macOS instructions are provided; those operating systems have not been tested.

## Download the code

This repository is private. Sign in to a GitHub account with access, then use **Code → Download ZIP**, extract it, and open the `bead-counter` subfolder. With Git authentication already configured, you can instead clone it:

```bash
git clone https://github.com/pourialaghayee/Pollimi-Software.git
cd Pollimi-Software/bead-counter
```

Ask the owner for collaborator access if the repository is unavailable. The setup and run commands do not change repository visibility.

## Linux setup

Install Python 3.12 first if it is unavailable. On Ubuntu/Debian, these packages provide virtual-environment support and commonly needed Qt libraries:

```bash
sudo apt update
sudo apt install python3-venv libxcb-cursor0 libxkbcommon-x11-0
```

Use the `venv` package matching your interpreter if Python 3.12 is installed separately. Open the `bead-counter` subfolder, then run:

```bash
bash run.sh
```

The launcher creates `.venv/`, installs the pinned dependencies and starts the app. Later launches check the installed versions. If installation was interrupted, running the launcher again retries it.

To choose a particular Python interpreter when creating the environment:

```bash
POLIMI_PYTHON=/path/to/python3.12 bash run.sh
```

An existing `.venv/` is reused. Rename or remove it before switching Python versions.

## Windows setup

Install Python 3.12 with the Python launcher, then double-click **run_windows.bat**. You can also run it from Command Prompt:

```bat
cd C:\path\to\Pollimi-Software\bead-counter
run_windows.bat
```

Setup is automatic and does not need PowerShell activation. Manual installation is also possible:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe bead_counter.py
```

## macOS setup

Install Python 3.12, open Terminal in its `bead-counter` subfolder and run:

```bash
bash run.sh
```

The launcher prefers `python3.12` when available. The Linux `apt` commands do not apply to macOS.

## Use the app

1. Click **Load .h5 file…** and select a recording. If several image arrays exist, choose one with axes **frame × row × column**.
2. Click **Count beads in all frames**. Processing runs in the background with progress and cancellation controls.
3. Select a frame using its **number**, the **slider**, or **Play**. Increase **Delay** for slower playback: 1000 ms is approximately one frame per second.
4. Inspect the boxes and table. **Green** shows new events; **orange** shows fading continuations with the same ID.
5. Open **All counted beads** for the combined image. **Open results folder** shows the saved files.
6. **Save boxed TIFF movie…** exports the annotated frames as an image stack for Fiji/ImageJ. It is a TIFF stack rather than an MP4.

Boxes start at **40 × 40 pixels**. Mouse wheel zooms and dragging pans. After zooming or panning, click **Fit image** to see the whole image again; it resets the view without changing the count or saved image. Box size, image contrast, playback delay and label visibility affect only the display. Changing **Detection settings** requires counting again.

Use **File → Open saved result…** to reopen an analysis without rerunning detection. Keep the source HDF5 file available. A moved recording can be located when prompted; its checksum is checked before saved overlays are shown.

## Input format

Select a numeric HDF5 dataset with shape `(frames, height, width)` and at least **three frames**. The Polimi image dataset path is:

```text
measurement/IDSmeasurement/t0/c0/image
```

Other numeric 3-D arrays can be selected. The app assumes this axis order and does not reorder axes automatically. NaN or infinite values are rejected. Input files are opened read-only.

## Counting rule and brightness

A detection keeps the preceding frame's event ID only if its detected integer **(x, y) centre is exactly the same pixel**, it appears in the **immediately following frame**, and its displayed brightness **B strictly decreases**.

A rare longer fade can retain its ID beyond two frames. A gap, shifted coordinate, brightness rise or equal brightness starts a new event. Equal brightness is marked uncertain. No movement tolerance or gap closing is used.

| Observations at the same pixel | Counted events |
|---|---:|
| B = 100 → 60 | 1 |
| B = 100 → 60 → 30 | 1 |
| B = 100 → 60 → 120 | 2 |
| A spot, an empty frame, then a spot | 2 |
| B = 100 → 100 | 2, marked uncertain |

**#12 B=23** means event ID 12, brightness 23 camera counts. B is the largest raw value in a **7 × 7 pixel patch** around the detected centre, clipped at image edges. The same B is used to check fading. It is not a bead count or photon measurement. There is no bright/dim classification.

## Detection method and accuracy

The detector subtracts each pixel's median across time, then subtracts broad from narrow Gaussian filtering to highlight spots. Filter widths are 1.5 and 12 pixels. Each frame's filtered noise is estimated using `1.4826 × median absolute deviation`. The shared default threshold is **6 noise units**. Masks are expanded by **20 four-connected dilation steps**, connected regions are joined, and their strongest filtered pixels define the centres.

Background and noise adapt to the recording; the threshold and dilation defaults stay shared. These defaults are not established optimum values. Dilation can merge nearby beads, while blurred halos can still create extra candidates. Persistent objects may be removed by background subtraction. Frames with zero estimated noise are skipped and listed in the summary.

**The total counts possible bead events and requires visual validation.** Noise can shift a stationary bead's detected centre by one pixel, which this strict rule counts separately. A new, dimmer bead at the identical pixel can look like fading. Software tests verify implementation behavior, not physical counting accuracy. This version does not estimate concentration per volume.

The default display white level of **30** changes contrast only; it is not a detection cutoff.

## Outputs

Each run creates a separate folder under `results/<recording>_<timestamp>/`.

| File | Contents |
|---|---|
| `all_beads.png` | Maximum projection with all event IDs and the total |
| `maximum_projection_raw.tif` | Maximum projection in the input data type, without boxes |
| `events.csv` | One row per counted event |
| `detections.csv` | Every frame detection, position, ID, B, SNR and association reason |
| `per_frame.csv` | Frame detections, new events, continuations and cumulative count |
| `summary.json` | Totals, source checksum, metadata, settings and counting rule |
| `boxed_stack.tif` | Optional RGB TIFF stack with boxes, IDs and brightness |

The combined image takes the largest value at each pixel across all frames. Counting uses the **individual frames**, then event IDs are drawn on the combined image. Repeated positions may share a box listing several IDs; nearby labels may overlap. CSV files preserve the separate records.

Share **all_beads.png** for the combined overview, event IDs and total count. Include **boxed_stack.tif** when your colleague needs to inspect detections frame by frame.

Boxed TIFFs contain 8-bit RGB display images. Quantitative raw values remain in the HDF5 recording. GUI frame numbers and `*_frame_number` fields start at 1; `frame_index`, `first_frame`, `last_frame` and pixel coordinates start at 0.

## Command-line use

Process without opening the GUI:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 --save-stack
```

Use `--key` if a file contains several image datasets:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 \
  --key measurement/IDSmeasurement/t0/c0/image \
  --output /path/to/output_folder
```

Use `bash run.sh --help` for all options, or `bash run.sh --result /path/to/results/run_folder` to reopen a saved analysis. On Windows, replace `bash run.sh` with `run_windows.bat`.

## Tests

Tests create temporary synthetic recordings; no experimental data is required. After setup, on Linux/macOS:

```bash
.venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/gui_smoke.py
```

On Windows, use `.venv\Scripts\python.exe`. The GUI test selects offscreen mode itself.

Tests cover fading, longer continuations, resets, missing frames, exact coordinates, equal brightness, simultaneous spots, input preservation, exports, cancellation and source verification. GUI checks exercise the Count button, navigation, playback, brightness values, display controls, overview and TIFF export.

## Troubleshooting

- **Python version error:** install Python 3.12; select it with `POLIMI_PYTHON` on Linux/macOS or `py -3.12` on Windows.
- **Missing `venv` or `ensurepip`:** install virtual-environment support for your Python interpreter.
- **Download failed:** restore internet access and run the launcher again.
- **Qt `xcb` / `libxcb-cursor.so.0` error on Linux:** install the runtime libraries listed above. Other requirements depend on the distribution; see [Qt Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html).
- **No desktop display:** use `--headless` for processing; offscreen mode is intended for tests.
- **No image dataset found:** check the numeric 3-D shape and axis order.

## Source files

`bead_counter.py` starts the app or CLI. `counter_core.py` reads HDF5, detects spots and assigns IDs. `rendering.py` draws and exports results. `viewer_gui.py` contains the GUI and background workers. `setup_environment.py` and the launchers handle installation. `requirements.txt` pins the package versions.

Keep recordings, results, `.venv/` and `.native/` out of commits. `.gitignore` excludes these folders and common data/image formats.
