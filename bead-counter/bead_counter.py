"""Entry point: desktop GUI by default; optional reproducible command-line run."""
from pathlib import Path
import argparse
import sys

from counter_core import DEFAULT_KEY, DetectorSettings, analyse, discover_datasets
from rendering import export_results, export_boxed_stack


def main():
    parser = argparse.ArgumentParser(description="Polimi bead counter · HDF5 microscope stacks")
    parser.add_argument("--input", type=Path, help="Optional HDF5 file to open")
    parser.add_argument("--key", help="HDF5 image dataset path; axes must be (frame, row, column)")
    parser.add_argument("--result", type=Path, help="Open an existing results folder in the GUI")
    parser.add_argument("--headless", action="store_true", help="Count and save without opening the GUI")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent/"results")
    parser.add_argument("--threshold", type=float, default=6.0)
    parser.add_argument("--merge", type=int, default=20)
    parser.add_argument("--box-size", type=int, default=40)
    parser.add_argument("--display-max", type=float, default=30.0)
    parser.add_argument("--save-stack", action="store_true", help="Also export a boxed RGB TIFF movie")
    args = parser.parse_args()
    if args.headless:
        if args.input is None:
            parser.error("--headless requires --input")
        choices = discover_datasets(args.input)
        if not choices:
            parser.error("No numeric 3-D image stack found.")
        if args.key is None and len(choices) > 1:
            parser.error("This file has multiple 3-D datasets. Choose one with --key.")
        key = args.key or choices[0]["key"]
        last_percent = -10
        def progress(percent, message):
            nonlocal last_percent
            if percent >= last_percent+10:
                print(f"{percent:3d}%  {message}", flush=True)
                last_percent = percent
        result = analyse(args.input, key,
            DetectorSettings(threshold_sigma=args.threshold, merge_iterations=args.merge), progress)
        folder = export_results(result, args.output, args.box_size, high=args.display_max)
        if args.save_stack:
            export_boxed_stack(result, folder/"boxed_stack.tif", args.box_size,
                               high=args.display_max, progress=progress)
        print(f"Counted events: {len(result.events)}; frame detections: {len(result.detections)}")
        print(f"Saved: {folder}")
        return 0
    from viewer_gui import run_gui
    return run_gui(args.input, args.key, args.result)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"Bead Counter: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
