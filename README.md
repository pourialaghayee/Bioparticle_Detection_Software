# Polimi Bead Counter

A Python interface for finding and counting bead appearances in microscope movies. Load an HDF5 recording, inspect detections frame by frame, and export a combined image and count tables.

**Source code:** [bead-counter](bead-counter/) · **Detailed guide:** [software documentation](bead-counter/README.md)

## What it does

- Loads `.h5` image stacks and detects spots across all frames.
- Provides playback, a frame slider, zoom, and adjustable bounding boxes.
- Shows each detection's event ID and brightness value.
- Counts stationary fading continuations under the rule described below.
- Saves an overview image, CSV tables, and an optional boxed TIFF movie.

This repository contains **code only**. Supply your own recording; experimental datasets and generated results are excluded from Git.

## Quick start

**Python 3.12 is recommended.** The first launch creates a local environment and installs dependencies, so it needs internet access. A desktop session is required for the viewer.

### Linux

With Python installed and GitHub access configured:

```bash
git clone https://github.com/pourialaghayee/Pollimi-Software.git
cd Pollimi-Software/bead-counter
bash run.sh
```

On Ubuntu/Debian, install these supporting packages if needed:

```bash
sudo apt update
sudo apt install python3-venv libxcb-cursor0 libxkbcommon-x11-0
```

Use the virtual-environment package matching your Python version. These packages do not install Python 3.12 itself.

### Windows

1. **Install Python 3.12** from [python.org](https://www.python.org/downloads/windows/) using the 64-bit Windows installer. Keep **py launcher** selected; adding Python to PATH is optional.
2. **Download the code:** on GitHub, click **Code → Download ZIP**, then right-click the ZIP and choose **Extract All…**.
3. **Move it to a short folder.** Inside the extracted folder is another `Pollimi-Software-master` folder containing `bead-counter`. Move that inner folder to `C:\` and rename it `Polimi`, so the app is in `C:\Polimi\bead-counter`. Windows limits file paths to 260 characters, and a folder inside `Downloads` is usually too long for the installed Qt files.
4. **Start the app:** open `C:\Polimi\bead-counter` and double-click **`run_windows.bat`**. If Windows shows *Windows protected your PC*, click **More info → Run anyway**.

The first start takes a few minutes and needs internet access to install the packages. Later starts take seconds. The black Command Prompt window stays open while the app runs; closing it also closes the app.

To update, download the new ZIP, copy your `results` folder somewhere safe, and replace the old `C:\Polimi` folder. With [Git for Windows](https://git-scm.com/download/win) installed, you can instead clone the repository into `C:\Polimi` and update with `git pull`. See the [Windows guide](bead-counter/README.md#windows-setup) for Command Prompt use and troubleshooting.

### macOS

Install Python 3.12, open Terminal in `bead-counter`, and run:

```bash
bash run.sh
```

The software has been verified on Linux. Windows and macOS instructions are provided but have not been tested. Because the repository is private, your GitHub account needs access to download or clone it.

## Using the app

1. Click **Load .h5 file…** and select a recording.
2. Click **Count beads in all frames**.
3. Inspect the movie with the frame number, slider, or **Play**. Increase **Delay** to slow playback.
4. Check the boxes and detection table. **Green** indicates a new event; **orange** indicates a fading continuation with the same ID.
5. Open **All counted beads** for the combined image, or **Open results folder** to inspect saved files.
6. Use **Save boxed TIFF movie…** to export the annotated frame stack for Fiji/ImageJ.

**Fit image** resets zoom and pan so the whole image is visible. It changes only the view, leaving counts and saved images unchanged.

The input must contain a numeric image array with axes **frame × height × width** and at least three frames. Box size, image contrast, and playback speed change only the display.

## How counting works

The detector estimates background and noise from the recording, highlights small spots, and assigns event IDs. A detection keeps the preceding frame's ID only when its centre is **exactly the same pixel** and its brightness **decreases**. A longer fade can keep its ID; a gap, shifted centre, brightness rise, or equal brightness starts a new event. Equal brightness is marked uncertain.

A label such as **#12 B=23** means event ID 12 and brightness 23 camera counts. B is the largest raw value in a 7 × 7 pixel patch around the detected centre. There is no bright/dim classification.

**Counts are candidates that need visual checking.** Noise can shift a stationary bead's detected centre, while a new dimmer bead at the same pixel can resemble fading. This version does not estimate concentration per volume. See the [detailed detection method and limitations](bead-counter/README.md#detection-method-and-accuracy).

## Outputs

Each run creates a new folder inside `bead-counter/results/`.

| File | Purpose |
|---|---|
| `all_beads.png` | Combined maximum projection with event IDs and total count |
| `events.csv` and `detections.csv` | Counted events and individual frame detections |
| `per_frame.csv` and `summary.json` | Frame counts, totals, metadata, and settings |
| `maximum_projection_raw.tif` | Combined projection without overlays |
| `boxed_stack.tif` | Optional movie stack with boxes, IDs, and brightness |

Share **all_beads.png** for the overview, IDs and count; include **boxed_stack.tif** for frame-by-frame inspection.

Counting uses the individual frames; the combined image is a visual summary. Original HDF5 recordings are opened read-only.

## Command-line processing

From `bead-counter`, process a recording without opening the viewer:

```bash
bash run.sh --headless --input /path/to/my_stack.h5 --save-stack
```

Use `bash run.sh --help` for more options. On Windows, use `run_windows.bat` in place of `bash run.sh`.

## Tests

After setup, run these commands from `bead-counter` on Linux/macOS:

```bash
.venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/gui_smoke.py
```

Tests use temporary synthetic recordings; experimental data is not required.

## More information

The [detailed software guide](bead-counter/README.md) covers installation, troubleshooting, input formats, counting examples, and all saved outputs. The project uses the [MIT license](LICENSE).
