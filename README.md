# Polimi Bead Counter

A Python desktop app for finding and counting beads in HDF5 microscope movies. Load a recording, inspect every frame with boxes, IDs and brightness values, and save a combined image and count tables.

**This is version 2.** Each flowing bead is counted once: a spot within a **radius** of a bead during its first **max frames** is the same bead. Version 1, which linked a bead only at exactly the same pixel with falling brightness, is on the [`master` branch](https://github.com/pourialaghayee/Bioparticle_Detection_Software/tree/master) and kept permanently as the [`v1.0` tag](https://github.com/pourialaghayee/Bioparticle_Detection_Software/tree/v1.0).

## What's new in version 2

- **New inputs** under *Detection settings*: **Flow rate** (recorded only), **Radius** and **Max frames**, next to the existing **Threshold**.
- **New counting rule:** a bead keeps its ID while it moves, and also after frames where it faded below the threshold. Brightness is no longer used for counting.
- **Simpler window:** the *Mask dilation* setting is removed; it stays fixed inside the software.
- **Original levels:** frames are shown without contrast enhancement by default, and an **Original levels** checkbox restores them after changes.
- **More detailed results:** how many frames each bead was seen and how far it moved.
- Checkboxes now show their state clearly on macOS.

The software is in the [`bead-counter`](bead-counter/) folder; run all commands from there. This repository contains **code only**. Supply your own `.h5` recording; experimental data, generated results, images and local Python environments are excluded from Git.

## What it does

- Loads `.h5` image stacks and detects spots across all frames.
- Provides playback, a frame slider, zoom and adjustable bounding boxes.
- Shows each detection's bead ID, brightness and how far it moved.
- Counts each bead once, even when it moves or fades, under the [rule below](#how-counting-works).
- Saves an overview image, CSV tables and an optional boxed TIFF movie.

## Requirements

- **Python 3.12 recommended**, including `pip` and `venv`. Newer Python versions are accepted.
- A desktop session for the viewer; command-line processing runs without a window.
- Internet access for the first start, which installs the packages. Later starts reuse them.
- Free disk space for your recordings and optional boxed TIFF exports.

The software has been run on Linux and macOS. The Windows instructions have not yet been tested on a Windows PC.

## Download the code

The repository is private, so sign in to a GitHub account with access. Version 2 is on the **`v2` branch**: on the repository page, switch the branch selector at the top left from `master` to **`v2`**, then use **Code → Download ZIP** and extract it. Or clone this branch with Git:

```bash
git clone -b v2 https://github.com/pourialaghayee/Bioparticle_Detection_Software.git
cd Bioparticle_Detection_Software/bead-counter
```

Ask the owner for collaborator access if the repository is unavailable.

## Installation

### Windows

1. **Install Python 3.12** from [python.org](https://www.python.org/downloads/windows/) using the 64-bit Windows installer. Keep **py launcher** selected; adding Python to PATH is optional. Python 3.13 or newer also works.
2. **Download the code:** on GitHub, switch the branch selector to **`v2`**, click **Code → Download ZIP**, then right-click the ZIP and choose **Extract All…**.
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

To update, copy your `results` folder somewhere safe and replace the code with a new ZIP download. With [Git for Windows](https://git-scm.com/download/win), you can instead clone the `v2` branch into `C:\Polimi` (`git clone -b v2 …`) and update with `git pull`; `.venv\` and `results\` are kept.

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
2. Under **Detection settings**, enter the **Flow rate**, **Radius** and **Max frames** (see [How counting works](#how-counting-works)). Then click **Count beads in all frames**. Processing runs in the background with progress and a **Cancel** button.
3. Select a frame with its **number**, the **slider** or **Play**. Increase **Delay** for slower playback; 1000 ms is about one frame per second.
4. Inspect the boxes and the table. **Green** shows a new bead; **orange** shows the same bead seen again, with how far it moved.
5. Open **All counted beads** for the combined image. **Open results folder** shows the saved files.
6. **Save boxed TIFF movie…** exports the annotated frames as a TIFF stack for Fiji/ImageJ.

Boxes start at **40 × 40 pixels**. The mouse wheel zooms and dragging pans. After zooming or panning, click **Fit image** to see the whole image again. Box size, black/white levels, playback delay and label visibility change only the display. Changing **Detection settings** requires counting again.

Frames are shown at their **original levels**: black is the darkest and white the brightest raw value in the recording, the same for every frame, with no contrast enhancement. After changing **Black level** or **White level**, tick **Original levels** to go back. A recording with one very bright spot can look dark at its original levels; lower the white level to see dim beads.

Use **File → Open saved result…** to reopen an analysis without counting again. Keep the source HDF5 file available. A moved recording can be located when prompted; its checksum is checked before the saved boxes are shown.

## Input format

Select a numeric HDF5 dataset with shape `(frames, height, width)` and at least **three frames**. The Polimi image dataset path is:

```text
measurement/IDSmeasurement/t0/c0/image
```

Other numeric 3-D arrays can be selected. The app assumes this axis order and does not reorder axes. NaN or infinite values are rejected. Input files are opened read-only.

## How counting works

Four inputs under **Detection settings** control a run:

| Input | Default | Meaning |
|---|---|---|
| **Flow rate** | not set | Saved in the results for reference only; it does not change the count |
| **Threshold** | 6 noise σ | How bright a spot must be to be detected |
| **Radius** | 20 px | A spot within this distance of a bead's last position is the same bead |
| **Max frames** | 7 | How many frames one bead can last, counted from its first frame |

A newly seen spot is a **new bead**. During that bead's first *max frames*, any spot within the *radius* of where the bead was last seen is the **same bead** and is not counted again. The bead may be missed in some frames, for example when it fades below the threshold, and still continue. Because the radius is measured from the last position, it follows a flowing bead. If two spots are near the same bead, the nearest one joins it and the other is a new bead. After *max frames*, a spot at the same place counts as a new bead.

With radius 20 px and max frames 7:

| Spots near one position | Counted beads |
|---|---:|
| Seen in one frame only | 1 |
| Frames 10, 11, 12, moving 5 px per frame | 1 |
| Frames 10, 11, missed in 12–13, back in 14 | 1 |
| Frames 10 to 18 continuously | 2 (the second starts at frame 17) |
| Frame 10, then a spot 30 px away in frame 11 | 2 |

**Brightness is not used for counting.** **#12 B=23** means bead ID 12 with brightness 23 camera counts: the largest raw value in a **7 × 7 pixel patch** around the detected centre. It is shown for review only and is not a photon measurement.

**Choosing values:** faster flow means fewer frames per bead. As a starting point, beads at 5 µl/min were seen for about 3–4 frames and at 0.5 µl/min for up to 7–10. After a run, `beads_by_frames_seen` in `summary.json` and `distance_px` in `detections.csv` show how long beads actually lasted and how far they moved.

On three test recordings with the defaults, version 2 counted 221, 194 and 98 beads where version 1 counted 242, 213 and 136. Detection was identical; the difference is beads seen in more than one frame, which version 2 counts once.
## Detection method and accuracy

The detector subtracts each pixel's median across time, then subtracts broad from narrow Gaussian filtering (widths 1.5 and 12 pixels) to highlight spots. Each frame's noise is estimated as `1.4826 × median absolute deviation`, and the default threshold is **6 noise units**. Masks are expanded by **20 four-connected dilation steps**, connected regions are joined, and their strongest filtered pixels define the centres. This joins the faint glow around a bright bead, which reaches about 40 px, into one spot; it is fixed and not shown in the window. Spots in one frame closer than the radius are also merged, keeping the brightest.

Background and noise adapt to each recording; the threshold and dilation defaults are shared and are not established optimum values. Dilation can merge nearby beads, while blurred halos can still create extra candidates. Objects that stay in place for most of the recording may be removed by the background subtraction. Frames with zero estimated noise are skipped and listed in the summary.

**The total counts possible beads and needs visual checking.** A new bead arriving within the radius of a recent bead is merged with it, and a bead that moves farther than the radius in one frame is counted twice. The tests check the software's behaviour, not physical counting accuracy. This version does not estimate concentration per volume.

Display levels change contrast only; they are not a detection cutoff.

## Outputs

Each run creates a new folder under `bead-counter/results/<recording>_<timestamp>/`.

| File | Contents |
|---|---|
| `all_beads.png` | Maximum projection with all bead IDs and the total |
| `maximum_projection_raw.tif` | Maximum projection in the input data type, without boxes |
| `events.csv` | One row per counted bead: first and last position and frame, `frames_seen`, `displacement_px` |
| `detections.csv` | Every frame detection: position, bead ID, B, SNR, `new_bead`/`same_bead` and `distance_px` moved |
| `per_frame.csv` | Frame detections, new beads, same bead again and cumulative count |
| `summary.json` | Totals, flow rate, radius, max frames, `beads_by_frames_seen`, original levels, source checksum and counting rule |
| `boxed_stack.tif` | Optional RGB TIFF stack with boxes, IDs and brightness |

The combined image takes the largest value at each pixel across all frames. Counting uses the **individual frames**; bead IDs are then drawn at each bead's first position on the combined image. Repeated positions share a box listing several IDs, and nearby labels may overlap; the CSV files keep the separate records.

Share **all_beads.png** for the overview, IDs and total. Include **boxed_stack.tif** when someone needs to inspect detections frame by frame.

Boxed TIFFs contain 8-bit display images; quantitative raw values remain in the HDF5 recording. Frame numbers in the app and `*_frame_number` fields start at 1; `frame_index`, `first_frame`, `last_frame` and pixel coordinates start at 0.

## Command-line use

Process a recording without opening the viewer:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 --flow-rate 0.5 --radius 20 --max-frames 10 --save-stack
```

`--radius` and `--max-frames` default to 20 and 7; `--flow-rate` is optional and only recorded. Exports use the original levels unless you give both `--display-min` and `--display-max`.

Use `--key` if a file contains several image datasets, and `--output` to choose where the results folder is created:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 \
  --key measurement/IDSmeasurement/t0/c0/image \
  --output /path/to/output_folder
```

Use `bash run.sh --help` for all options, or `bash run.sh --result /path/to/results/run_folder` to reopen a saved analysis. Results saved by version 1 can also be opened. On Windows, use `run_windows.bat` instead of `bash run.sh`.

## Tests

The tests create temporary synthetic recordings, so no experimental data is needed. After setup, from `bead-counter` on macOS/Linux:

```bash
.venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/gui_smoke.py
```

On Windows, use `.venv\Scripts\python.exe`.

The tests cover single-frame beads, moving beads within the radius, missed frames, the max-frames limit, nearest-spot matching, parallel beads, same-frame merging, settings validation, original levels, opening version 1 results, input preservation, exports, cancellation, source verification and sidebar layout. The GUI checks exercise the new inputs, the Original levels checkbox, the Count button, navigation, playback, brightness values, display controls, the overview and TIFF export.

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

In `bead-counter`: `bead_counter.py` starts the app or the command line. `counter_core.py` reads HDF5, detects spots and counts each bead once. `rendering.py` draws and exports results. `viewer_gui.py` contains the window and background workers. `setup_environment.py`, `run.sh` and `run_windows.bat` handle installation, and `requirements.txt` pins the package versions.

Keep recordings, results and `.venv/` out of commits; `.gitignore` excludes them and common data and image formats. The project uses the [MIT license](LICENSE).
