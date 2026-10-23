"""Render boxed frames and write inspectable results without modifying raw images."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import csv
import json
import re
import shutil
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import tifffile

from counter_core import Analysis, check_cancel, is_new, read_frame

NEW_COLOUR = "#67f59b"
FADE_COLOUR = "#ffc565"
TEXT_COLOUR = "#f1f5f9"


def font(size=17):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def grayscale(raw, low=0.0, high=30.0):
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        raise ValueError("Display maximum must be greater than display minimum.")
    array = np.clip((raw.astype(np.float32)-low) * (255/(high-low)), 0, 255).astype(np.uint8)
    return Image.fromarray(array).convert("RGB")


def brightness_text(value):
    return f"{value:.0f}" if value == int(value) else f"{value:.1f}"


def original_levels(result: Analysis, low=None, high=None):
    """Use the recording's darkest-to-brightest range unless levels are given."""
    if low is not None and high is not None:
        return low, high
    if result.original_levels:
        return result.original_levels
    return float(result.projection.min()), float(max(result.projection.max(), result.projection.min()+1))


def label(draw, position, text, colour, size, width, height):
    face = font(size)
    text_width = draw.textbbox((0, 0), text, font=face)[2]
    x = max(0, min(int(position[0]), max(0, width-text_width-8)))
    y = max(0, min(int(position[1]), max(0, height-size-10)))
    draw.rectangle((x, y, x+text_width+7, y+size+7), fill="#07110d")
    draw.text((x+3, y+1), text, font=face, fill=colour)


def render_frame(raw, detections, box_size=40, low=0.0, high=30.0, show_labels=True):
    image = grayscale(raw, low, high)
    draw = ImageDraw.Draw(image)
    half = max(2, int(box_size)//2)
    for detection in detections:
        colour = NEW_COLOUR if is_new(detection) else FADE_COLOUR
        x, y = detection.x, detection.y
        draw.rectangle((max(0, x-half), max(0, y-half),
                        min(image.width-1, x+half), min(image.height-1, y+half)),
                       outline=colour, width=2)
        if show_labels:
            label(draw, (x-half, y-half-30),
                  f"#{detection.event_id}  B={brightness_text(detection.brightness)}",
                  colour, 20, image.width, image.height)
    return image


def render_overview(result: Analysis, box_size=40, low=None, high=None,
                    show_labels=True, banner=True):
    """Every event is represented; repeated positions list every ID in one label."""
    low, high = original_levels(result, low, high)
    image = grayscale(result.projection, low, high)
    draw = ImageDraw.Draw(image)
    groups = defaultdict(list)
    for event in result.events:
        groups[(event.y, event.x)].append(event.event_id)
    half = max(2, int(box_size)//2)
    for (y, x), ids in groups.items():
        draw.rectangle((max(0, x-half), max(0, y-half),
                        min(image.width-1, x+half), min(image.height-1, y+half)),
                       outline=NEW_COLOUR, width=2)
        if show_labels:
            # Small datasets fit individual IDs; longer lists wrap, never disappear.
            lines = [ids[start:start+8] for start in range(0, len(ids), 8)]
            for line_index, group in enumerate(lines):
                label(draw, (x-half, y-half-25*(len(lines)-line_index)),
                      "#" + ",".join(str(i) for i in group),
                      NEW_COLOUR, 16, image.width, image.height)
    if banner:
        out = Image.new("RGB", (max(image.width, 900), image.height+108), "#101c2b")
        out.paste(image, (0, 108))
        draw = ImageDraw.Draw(out)
        draw.text((18, 10), f"All counted beads: {len(result.events)}  |  "
                  f"{result.shape[0]} frames  |  {len(result.detections)} frame detections",
                  font=font(22), fill=TEXT_COLOUR)
        draw.text((18, 43), f"Maximum projection + bead IDs at first position. Same bead = within "
                  f"{result.settings.radius_px:g} px during its first {result.settings.max_frames} frames.",
                  font=font(16), fill="#bad0df")
        draw.text((18, 73), "Count comes from individual frames. Review boxes to check "
                  "candidate accuracy; nearby labels may overlap.", font=font(16), fill="#bad0df")
        return out
    return image


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_results(result: Analysis, output_root: str | Path, box_size=40,
                   low=None, high=None, cancel=None) -> Path:
    """Commit a new run folder only after all required outputs are complete."""
    low, high = original_levels(result, low, high)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", Path(result.source).stem)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = root / f"{stem}_{stamp}"
    temporary = Path(tempfile.mkdtemp(prefix=".in_progress_", dir=root))
    try:
        check_cancel(cancel)
        render_overview(result, box_size, low, high).save(temporary/"all_beads.png")
        projection = result.projection.astype(result.dtype)
        tifffile.imwrite(temporary/"maximum_projection_raw.tif", projection,
                         photometric="minisblack", metadata={"axes": "YX"})
        detections = []
        for detection in result.detections:
            row = asdict(detection)
            row["frame_index"] = row.pop("frame")
            row["frame_number"] = row["frame_index"]+1
            detections.append(row)
        write_csv(temporary/"detections.csv", detections,
                  ["frame_index", "frame_number", "event_id", "x", "y", "brightness",
                   "peak_snr", "association", "distance_px"])
        events = []
        for event in result.events:
            row = asdict(event)
            row["first_frame_number"] = row["first_frame"]+1
            row["last_frame_number"] = row["last_frame"]+1
            row["frames_seen"] = row.pop("observations")
            row["displacement_px"] = round(event.displacement_px, 2)
            events.append(row)
        write_csv(temporary/"events.csv", events,
                  ["event_id", "x", "y", "last_x", "last_y", "first_frame", "last_frame",
                   "first_frame_number", "last_frame_number", "frames_seen", "displacement_px",
                   "first_brightness", "last_brightness"])
        cumulative = 0
        rows = []
        for frame in range(result.shape[0]):
            found = result.for_frame(frame)
            new = sum(is_new(d) for d in found)
            cumulative += new
            rows.append(dict(frame_index=frame, frame_number=frame+1, detections=len(found),
                             new_beads=new, same_bead_again=len(found)-new,
                             cumulative_beads=cumulative))
        write_csv(temporary/"per_frame.csv", rows,
                  ["frame_index", "frame_number", "detections", "new_beads", "same_bead_again",
                   "cumulative_beads"])
        summary = result.summary()
        summary["display"] = dict(box_size_px=box_size, minimum=low, maximum=high,
                                  note="Display contrast and box size do not change detections.")
        (temporary/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False),
                                             encoding="utf-8")
        (temporary/"READ_ME.txt").write_text(
            "all_beads.png: maximum projection with every counted bead ID at its first position. "
            "Several beads at exactly one position share a box; their IDs are listed together.\n"
            "maximum_projection_raw.tif: unmodified maximum pixel values, without boxes.\n"
            "events.csv: one row per counted bead. detections.csv: one row per frame detection; "
            "distance_px is the distance to that bead's previous position.\n"
            "per_frame.csv: frame counts and cumulative count. summary.json: source, settings, "
            "association rule and totals.\n"
            "Frame numbers displayed in the GUI start at 1; *_index and first/last_frame "
            "columns start at 0. Coordinates (x,y) start at 0.\n"
            f"Same bead: within {result.settings.radius_px:g} px of its last position during its "
            f"first {result.settings.max_frames} frames, even after missed frames. "
            "B is the local raw peak camera count, shown for review only.\n"
            "A new bead arriving within the radius of a recent bead is merged with it. "
            "Counts require visual review.\n",
            encoding="utf-8")
        check_cancel(cancel)
        temporary.rename(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def export_boxed_stack(result: Analysis, destination: str | Path, box_size=40,
                       low=None, high=None, progress=None, cancel=None):
    """Write an RGB TIFF movie page by page; preserve the source's raw values separately."""
    low, high = original_levels(result, low, high)
    import h5py
    destination = Path(destination).resolve()
    if destination == Path(result.source).resolve():
        raise ValueError("The boxed movie cannot overwrite the original HDF5 recording.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name+".partial")
    try:
        # Prefer classic TIFF for smaller movies; switch before approaching its
        # 4 GiB offset limit, using an uncompressed-size estimate for safety.
        bigtiff = int(np.prod(result.shape)) * 3 > 3500*1024**2
        with h5py.File(result.source, "r") as handle, tifffile.TiffWriter(temporary, bigtiff=bigtiff) as writer:
            dataset = handle[result.dataset_key]
            for frame in range(result.shape[0]):
                check_cancel(cancel)
                image = render_frame(dataset[frame], result.for_frame(frame), box_size, low, high)
                writer.write(np.asarray(image), photometric="rgb", compression="deflate",
                             metadata=None, description=f"Frame {frame+1}; ID and B=raw local peak")
                if progress:
                    progress(int(100*(frame+1)/result.shape[0]),
                             f"Saving boxed TIFF · frame {frame+1} / {result.shape[0]}")
        check_cancel(cancel)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_result(folder: str | Path) -> Analysis:
    """Reload a saved result for viewing without repeating detection."""
    from counter_core import Detection, DetectorSettings, Event, display_levels
    folder = Path(folder)
    summary = json.loads((folder/"summary.json").read_text(encoding="utf-8"))
    detections, events = [], []
    with (folder/"detections.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            detections.append(Detection(int(row["frame_index"]), int(row["y"]), int(row["x"]),
                float(row["brightness"]), float(row["peak_snr"]), int(row["event_id"]), row["association"],
                float(row.get("distance_px") or 0)))
    with (folder/"events.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            events.append(Event(int(row["event_id"]), int(row["y"]), int(row["x"]),
                int(row["first_frame"]), int(row["last_frame"]),
                int(row.get("frames_seen") or row["observations"]),
                float(row["first_brightness"]), float(row["last_brightness"]),
                int(row.get("last_y") or -1), int(row.get("last_x") or -1)))
    levels = summary.get("original_display_levels")
    return Analysis(summary["source"], summary["dataset_key"], tuple(summary["shape_frames_y_x"]),
        summary["dtype"], summary["metadata"], DetectorSettings.from_saved(summary["settings"]),
        detections, events, summary["per_frame_filtered_noise_sigma"],
        tifffile.imread(folder/"maximum_projection_raw.tif").astype(np.float32),
        summary["analysis_seconds"], summary["source_sha256"],
        display_levels(*levels) if levels else None)
