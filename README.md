# Polimi Bead Counter

A Python desktop app for finding and counting bead appearances in HDF5 microscope movies. Load a recording, inspect every frame with boxes, IDs and brightness values, and save a combined image and count tables.

**This is version 1.** It links a bead across frames only at exactly the same pixel with falling brightness. **Version 2**, which counts each flowing bead once using a radius and a maximum number of frames, is on the [`v2` branch](https://github.com/pourialaghayee/Bioparticle_Detection_Software/tree/v2). Version 1 is also kept permanently as the [`v1.0` tag](https://github.com/pourialaghayee/Bioparticle_Detection_Software/tree/v1.0).

The software is in the [`bead-counter`](bead-counter/) folder; run all commands from there. This repository contains **code only**. Supply your own `.h5` recording; experimental data, generated results, images and local Python environments are excluded from Git.

## What it does

- Loads `.h5` image stacks and detects spots across all frames.
- Provides playback, a frame slider, zoom and adjustable bounding boxes.
- Shows each detection's event ID and brightness value.
- Counts stationary fading continuations once, under the [rule below](#how-counting-works).
- Saves an overview image, CSV tables and an optional boxed TIFF movie.

## Requirements

- **Python 3.12 recommended**, including `pip` and `venv`. Newer Python versions are accepted.
- A desktop session for the viewer; command-line processing runs without a window.
- Internet access for the first start, which installs the packages. Later starts reuse them.
- Free disk space for your recordings and optional boxed TIFF exports.

The software has been run on Linux and macOS. The Windows instructions have not yet been tested on a Windows PC.

## Download the code

The repository is private, so sign in to a GitHub account with access. Then either use **Code → Download ZIP** and extract it, or clone it with Git:

```bash
git clone https://github.com/pourialaghayee/Bioparticle_Detection_Software.git
cd Bioparticle_Detection_Software/bead-counter
```

Ask the owner for collaborator access if the repository is unavailable.

## Installation

### Windows

1. **Install Python 3.12** from [python.org](https://www.python.org/downloads/windows/) using the 64-bit Windows installer. Keep **py launcher** selected; adding Python to PATH is optional. Python 3.13 or newer also works.
2. **Download the code:** on GitHub, click **Code → Download ZIP**, then right-click the ZIP and choose **Extract All…**.
3. **Move it to a short folder.** The extracted folder contains another folder of the same name, which holds `bead-counter`. Move that inner folder to `C:\` and rename it `Polimi`, so the app is in `C:\Polimi\bead-counter`.
4. **Start the app:** open `C:\Polimi\bead-counter` and double-click **`run_windows.bat`**. If Windows shows *Windows protected your PC*, click **More info → Run anyway**.

The first start takes a few minutes. Later starts take seconds. The black Command Prompt window stays open while the app runs; closing it also closes the app.

**Why a short folder:** Windows limits file paths to 260 characters unless long paths are enabled, and the Qt package installs files about 190 characters below the project folder. A folder inside `Downloads` is usually too long. Setup checks this before installing and explains what to do.

To run from Command Prompt, for example with command-line options:

```bat
cd /d C:\Polimi\bead-counter
run_windows.bat --headless --input C:\data\my_stack.h5 --save-stack
```

The launcher uses an existing `.venv\` first, then `py -3.12`, then any Python 3.12 or newer. Manual installation is also possible:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe bead_counter.py
```

To update, copy your `results` folder somewhere safe and replace the code with a new ZIP download. With [Git for Windows](https://git-scm.com/download/win), you can instead clone the repository into `C:\Polimi` and update with `git pull`; `.venv\` and `results\` are kept.

### macOS

Install Python 3.12, open Terminal in the `bead-counter` folder and run:

```bash
bash run.sh
```

The launcher prefers `python3.12` when available.

### Linux

Install Python 3.12 if needed. On Ubuntu/Debian, these packages provide virtual-environment support and common Qt libraries:

```bash
sudo apt update
sudo apt install python3-venv libxcb-cursor0 libxkbcommon-x11-0
```

Use the `venv` package matching your Python version. Then, in the `bead-counter` folder:

```bash
bash run.sh
```

### About the launcher (macOS and Linux)

`run.sh` creates `.venv/`, installs the pinned packages and starts the app. Later starts check the installed versions; if installation was interrupted, running it again retries. To choose a particular Python when the environment is first created:

```bash
POLIMI_PYTHON=/path/to/python3.12 bash run.sh
```

An existing `.venv/` is reused. Delete it before switching Python versions.

## Using the app

1. Click **Load .h5 file…** and select a recording. If several image arrays exist, choose one with axes **frame × row × column**.
2. Click **Count beads in all frames**. Processing runs in the background with progress and a **Cancel** button.
3. Select a frame with its **number**, the **slider** or **Play**. Increase **Delay** for slower playback; 1000 ms is about one frame per second.
4. Inspect the boxes and the table. **Green** shows a new event; **orange** shows a fading continuation with the same ID.
5. Open **All counted beads** for the combined image. **Open results folder** shows the saved files.
6. **Save boxed TIFF movie…** exports the annotated frames as a TIFF stack for Fiji/ImageJ.

Boxes start at **40 × 40 pixels**. The mouse wheel zooms and dragging pans. After zooming or panning, click **Fit image** to see the whole image again. Box size, black/white levels, playback delay and label visibility change only the display. Changing **Detection settings** requires counting again.

Use **File → Open saved result…** to reopen an analysis without counting again. Keep the source HDF5 file available. A moved recording can be located when prompted; its checksum is checked before the saved boxes are shown.

## Input format

Select a numeric HDF5 dataset with shape `(frames, height, width)` and at least **three frames**. The Polimi image dataset path is:

```text
measurement/IDSmeasurement/t0/c0/image
```

Other numeric 3-D arrays can be selected. The app assumes this axis order and does not reorder axes. NaN or infinite values are rejected. Input files are opened read-only.

## How counting works

A detection keeps the preceding frame's event ID only if its detected **(x, y) centre is exactly the same pixel**, it appears in the **immediately following frame**, and its brightness **B strictly decreases**. A longer fade can keep its ID. A gap, shifted centre, brightness rise or equal brightness starts a new event; equal brightness is marked uncertain.

| Observations at the same pixel | Counted events |
|---|---:|
| B = 100 → 60 | 1 |
| B = 100 → 60 → 30 | 1 |
| B = 100 → 60 → 120 | 2 |
| A spot, an empty frame, then a spot | 2 |
| B = 100 → 100 | 2, marked uncertain |

**#12 B=23** means event ID 12 with brightness 23 camera counts. B is the largest raw value in a **7 × 7 pixel patch** around the detected centre, clipped at image edges. It is not a photon measurement, and there is no bright/dim classification.

## Detection method and accuracy

The detector subtracts each pixel's median across time, then subtracts broad from narrow Gaussian filtering (widths 1.5 and 12 pixels) to highlight spots. Each frame's noise is estimated as `1.4826 × median absolute deviation`, and the default threshold is **6 noise units**. Masks are expanded by **20 four-connected dilation steps**, connected regions are joined, and their strongest filtered pixels define the centres.

Background and noise adapt to each recording; the threshold and dilation defaults are shared and are not established optimum values. Dilation can merge nearby beads, while blurred halos can still create extra candidates. Objects that stay in place for most of the recording may be removed by the background subtraction. Frames with zero estimated noise are skipped and listed in the summary.

**The total counts possible bead events and needs visual checking.** Noise can shift a stationary bead's centre by one pixel, which this strict rule counts separately, and a new dimmer bead at the same pixel can look like fading. The tests check the software's behaviour, not physical counting accuracy. This version does not estimate concentration per volume.

The default display white level of **30** changes contrast only; it is not a detection cutoff.

## Outputs

Each run creates a new folder under `bead-counter/results/<recording>_<timestamp>/`.

| File | Contents |
|---|---|
| `all_beads.png` | Maximum projection with all event IDs and the total |
| `maximum_projection_raw.tif` | Maximum projection in the input data type, without boxes |
| `events.csv` | One row per counted event |
| `detections.csv` | Every frame detection: position, ID, B, SNR and association reason |
| `per_frame.csv` | Frame detections, new events, continuations and cumulative count |
| `summary.json` | Totals, source checksum, metadata, settings and counting rule |
| `boxed_stack.tif` | Optional RGB TIFF stack with boxes, IDs and brightness |

The combined image takes the largest value at each pixel across all frames. Counting uses the **individual frames**; event IDs are then drawn on the combined image. Repeated positions share a box listing several IDs, and nearby labels may overlap; the CSV files keep the separate records.

Share **all_beads.png** for the overview, IDs and total. Include **boxed_stack.tif** when someone needs to inspect detections frame by frame.

Boxed TIFFs contain 8-bit display images; quantitative raw values remain in the HDF5 recording. Frame numbers in the app and `*_frame_number` fields start at 1; `frame_index`, `first_frame`, `last_frame` and pixel coordinates start at 0.

## Command-line use

Process a recording without opening the viewer:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 --save-stack
```

Use `--key` if a file contains several image datasets, and `--output` to choose where the results folder is created:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 \
  --key measurement/IDSmeasurement/t0/c0/image \
  --output /path/to/output_folder
```

Use `bash run.sh --help` for all options, or `bash run.sh --result /path/to/results/run_folder` to reopen a saved analysis. On Windows, use `run_windows.bat` instead of `bash run.sh`.

## Tests

The tests create temporary synthetic recordings, so no experimental data is needed. After setup, from `bead-counter` on macOS/Linux:

```bash
.venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/gui_smoke.py
```

On Windows, use `.venv\Scripts\python.exe`.

The tests cover fading, longer continuations, resets, missing frames, exact coordinates, equal brightness, simultaneous spots, input preservation, exports, cancellation, source verification and sidebar layout. The GUI checks exercise the Count button, navigation, playback, brightness values, display controls, the overview and TIFF export.

## Troubleshooting

- **Python version error:** install Python 3.12; select it with `POLIMI_PYTHON` on macOS/Linux or `py -3.12` on Windows.
- **Missing `venv` or `ensurepip`:** install virtual-environment support for your Python.
- **Download failed:** restore internet access and run the launcher again.
- **Qt `xcb` / `libxcb-cursor.so.0` error on Linux:** install the libraries listed under Linux. See also the [Qt Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html).
- **Qt platform plugin "cocoa" not found on macOS:** if the project is in an iCloud-synced folder such as Desktop, macOS may hide the environment's files. Run `chflags -R nohidden .venv` in `bead-counter`, or keep the project outside iCloud.
- **No desktop display:** use `--headless` for processing.
- **No image dataset found:** check the numeric 3-D shape and axis order.

On Windows:

- **"Python 3.12 or newer was not found":** install Python from python.org with **py launcher** selected, then run `run_windows.bat` again. The Microsoft Store `python` shortcut does not count as an installation.
- **"This folder path is too long for Windows":** move the folder to `C:\Polimi\bead-counter`, delete any `.venv` folder created there, and run the launcher again.
- **Installation stopped or failed partway:** delete `.venv` in `bead-counter` and run `run_windows.bat` again with internet access.
- **Windows protected your PC:** click **More info → Run anyway**; the launcher is a plain text file you can open in Notepad to check.

## Project files

In `bead-counter`: `bead_counter.py` starts the app or the command line. `counter_core.py` reads HDF5, detects spots and assigns IDs. `rendering.py` draws and exports results. `viewer_gui.py` contains the window and background workers. `setup_environment.py`, `run.sh` and `run_windows.bat` handle installation, and `requirements.txt` pins the package versions.

Keep recordings, results and `.venv/` out of commits; `.gitignore` excludes them and common data and image formats. The project uses the [MIT license](LICENSE).
