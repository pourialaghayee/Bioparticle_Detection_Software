"""Read microscope HDF5 stacks, detect spots, and count each bead once.

A bead keeps its ID while it is seen within a radius of its last position during
its first N frames. No GUI dependency. Input files are always opened read-only.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable
import hashlib
import math
import time

import h5py
import numpy as np
from scipy import ndimage as ndi

VERSION = "2.0.0"
DEFAULT_KEY = "measurement/IDSmeasurement/t0/c0/image"
NEW_BEAD = "new_bead"
SAME_BEAD = "same_bead"
# Labels written by version 1 results, still readable for viewing.
LEGACY_SAME = {"stationary_fade"}


class Cancelled(Exception):
    """The user cancelled processing before an output was committed."""


@dataclass(frozen=True)
class DetectorSettings:
    threshold_sigma: float = 6.0
    radius_px: float = 20.0
    max_frames: int = 7
    flow_rate_ul_min: float | None = None    # recorded only; never used for counting
    small_sigma: float = 1.5
    background_sigma: float = 12.0
    # Joins the faint glow around a bright bead (up to ~40 px) into one spot.
    # Fixed internally; not shown in the window.
    merge_iterations: int = 20
    brightness_radius: int = 3

    @classmethod
    def from_saved(cls, values: dict) -> "DetectorSettings":
        """Ignore settings that older versions saved, such as merge_iterations."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in known})

    def validate(self):
        if not np.isfinite(self.threshold_sigma) or self.threshold_sigma <= 0:
            raise ValueError("Detection threshold must be positive.")
        if not np.isfinite(self.radius_px) or self.radius_px <= 0:
            raise ValueError("Radius must be positive.")
        if int(self.max_frames) != self.max_frames or self.max_frames < 1:
            raise ValueError("Max frames must be a whole number of at least 1.")
        if self.flow_rate_ul_min is not None and (
                not np.isfinite(self.flow_rate_ul_min) or self.flow_rate_ul_min <= 0):
            raise ValueError("Flow rate must be positive, or left empty.")
        if not 0 < self.small_sigma < self.background_sigma:
            raise ValueError("The small filter width must be less than the background width.")
        if self.merge_iterations < 0 or self.brightness_radius < 0:
            raise ValueError("Pixel sizes cannot be negative.")


@dataclass
class Detection:
    frame: int                 # internal and exported frame_index are zero based
    y: int
    x: int
    brightness: float          # raw maximum in a 7 x 7 patch by default
    peak_snr: float
    event_id: int = 0           # displayed IDs start at 1
    association: str = NEW_BEAD
    distance_px: float = 0.0    # distance to the bead's previous position; 0 for a new bead


def is_new(detection: Detection) -> bool:
    return detection.association != SAME_BEAD and detection.association not in LEGACY_SAME


@dataclass
class Event:
    """One counted bead."""
    event_id: int
    y: int                      # first position
    x: int
    first_frame: int
    last_frame: int
    observations: int
    first_brightness: float
    last_brightness: float
    last_y: int = -1            # last position; -1 when read from an older result
    last_x: int = -1

    @property
    def displacement_px(self) -> float:
        if self.last_y < 0:
            return 0.0
        return math.hypot(self.last_y - self.y, self.last_x - self.x)


@dataclass
class Analysis:
    source: str
    dataset_key: str
    shape: tuple[int, int, int]
    dtype: str
    metadata: dict
    settings: DetectorSettings
    detections: list[Detection]
    events: list[Event]
    noise: list[float]
    projection: np.ndarray
    seconds: float
    source_sha256: str
    original_levels: tuple[float, float] | None = None   # darkest, brightest raw value

    def for_frame(self, frame: int) -> list[Detection]:
        return [d for d in self.detections if d.frame == frame]

    def summary(self) -> dict:
        counts = np.bincount([d.frame for d in self.detections], minlength=self.shape[0])
        frames_seen = Counter(e.observations for e in self.events)
        size = 2*self.settings.brightness_radius+1
        return {
            "software_version": VERSION,
            "counting_rule_version": 2,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "dataset_key": self.dataset_key,
            "shape_frames_y_x": list(self.shape),
            "dtype": self.dtype,
            "metadata": self.metadata,
            "flow_rate_ul_min": self.settings.flow_rate_ul_min,
            "settings": asdict(self.settings),
            "counted_events": len(self.events),
            "frame_detections": len(self.detections),
            "same_bead_detections_not_counted_again": len(self.detections) - len(self.events),
            "beads_by_frames_seen": {str(k): frames_seen[k] for k in sorted(frames_seen)},
            "original_display_levels": list(self.original_levels) if self.original_levels else None,
            "per_frame_detections": counts.tolist(),
            "per_frame_filtered_noise_sigma": self.noise,
            "frames_with_zero_noise_skipped": [i+1 for i, sigma in enumerate(self.noise) if sigma == 0],
            "analysis_seconds": self.seconds,
            "association_rule": (
                f"A newly seen spot is a new bead. During that bead's first {self.settings.max_frames} "
                f"frames, any spot within {self.settings.radius_px:g} px of its last seen position is "
                "the same bead and is not counted again, even after frames where it was not seen. "
                "If several spots qualify, the nearest one joins. Within one frame, a bright "
                "bead's surrounding glow is joined into one spot by mask dilation, and spots "
                "closer than the radius are merged, keeping the brightest. Brightness is not "
                "used for counting. Flow rate is recorded only."
            ),
            "brightness_definition": (
                f"Maximum raw camera value in a {size} x {size} pixel patch around the detected "
                "centre; camera counts, not photons. Shown for review only."
            ),
            "interpretation": (
                "Counts are algorithmic bead candidates, not a validated physical bead total. "
                "A new bead arriving within the radius of a recent bead is merged with it. "
                "Manual review is still required. Maximum projection is a visual summary, "
                "not the counter."
            ),
        }


def check_cancel(cancel: Callable[[], bool] | None):
    if cancel and cancel():
        raise Cancelled("Processing cancelled.")


def discover_datasets(path: str | Path) -> list[dict]:
    """List numeric 3-D arrays. The user chooses if there is more than one."""
    choices = []
    with h5py.File(path, "r") as handle:
        def visit(name, obj):
            if (isinstance(obj, h5py.Dataset) and obj.ndim == 3
                    and obj.dtype.kind in "uif" and all(v > 0 for v in obj.shape)):
                choices.append({"key": name, "shape": tuple(obj.shape), "dtype": str(obj.dtype)})
        handle.visititems(visit)
    choices.sort(key=lambda d: (d["key"] != DEFAULT_KEY, d["key"]))
    return choices


def inspect_stack(path: str | Path, key: str) -> tuple[tuple, str, dict]:
    with h5py.File(path, "r") as handle:
        dataset = handle[key]
        if (not isinstance(dataset, h5py.Dataset) or dataset.ndim != 3
                or dataset.dtype.kind not in "uif" or not all(dataset.shape)):
            raise ValueError("Choose a numeric 3-D image array with axes (frame, row, column).")
        metadata = {}
        elements = np.asarray(dataset.attrs.get("element_size_um", []), dtype=float).ravel()
        if len(elements) >= 3:
            metadata["pixel_height_um"] = float(elements[-2])
            metadata["pixel_width_um"] = float(elements[-1])
        if "hardware/IDS/settings" in handle:
            attrs = handle["hardware/IDS/settings"].attrs
            for name in ("frame_rate", "exposure_time", "gain"):
                if name in attrs:
                    try:
                        metadata[name] = float(attrs[name])
                    except (TypeError, ValueError):
                        pass
        return tuple(dataset.shape), str(dataset.dtype), metadata


def read_frame(path: str | Path, key: str, frame: int) -> np.ndarray:
    with h5py.File(path, "r") as handle:
        dataset = handle[key]
        if not 0 <= frame < dataset.shape[0]:
            raise IndexError("Frame is outside this stack.")
        return dataset[frame]


def verify_source(result: Analysis, path: str | Path | None = None):
    """Prevent a saved overlay from being shown on a different recording."""
    source = Path(path or result.source).resolve()
    shape, dtype, _ = inspect_stack(source, result.dataset_key)
    if shape != result.shape or dtype != result.dtype:
        raise ValueError("The selected file does not match the saved stack dimensions and data type.")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024**2), b""):
            digest.update(block)
    if digest.hexdigest() != result.source_sha256:
        raise ValueError("This HDF5 file differs from the recording used for these results. "
                         "Load the correct source or count the changed file again.")
    result.source = str(source)


def temporal_background(dataset, progress=None, cancel=None):
    """Compute an exact per-pixel median in strips, without loading the movie."""
    frames, height, width = dataset.shape
    background = np.empty((height, width), dtype=np.float32)
    # Keep the median's working block around 24 MiB, even for longer stacks.
    rows = max(1, min(64, (24 * 1024**2) // max(1, frames * width * 4)))
    for start in range(0, height, rows):
        check_cancel(cancel)
        stop = min(height, start + rows)
        block = dataset[:, start:stop, :].astype(np.float32)
        if not np.isfinite(block).all():
            raise ValueError("The selected image dataset contains NaN or infinite values.")
        background[start:stop] = np.median(block, axis=0)
        if progress:
            progress(int(18 * stop / height), "Estimating the static background…")
    return background


def intensity_range(path: str | Path, key: str, cancel=None) -> tuple[float, float]:
    """Darkest and brightest raw value in the whole recording, read in blocks."""
    with h5py.File(path, "r") as handle:
        dataset = handle[key]
        low, high = np.inf, -np.inf
        step = max(1, (64 * 1024**2) // max(1, dataset.shape[1] * dataset.shape[2] * dataset.dtype.itemsize))
        for start in range(0, dataset.shape[0], step):
            check_cancel(cancel)
            block = dataset[start:start+step]
            low, high = min(low, float(block.min())), max(high, float(block.max()))
    return display_levels(low, high)


def display_levels(low: float, high: float) -> tuple[float, float]:
    """A flat recording still needs white above black to be displayed."""
    return (low, high) if high > low else (low, low + 1.0)


def merge_close_spots(detections: list[Detection], radius: float) -> list[Detection]:
    """Within one frame, keep the brightest spot of any group closer than the radius."""
    kept: list[Detection] = []
    for candidate in sorted(detections, key=lambda d: (-d.brightness, -d.peak_snr, d.y, d.x)):
        if all(math.hypot(candidate.y - k.y, candidate.x - k.x) >= radius for k in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda d: (d.y, d.x))


def detect_frame(raw, background, frame, settings: DetectorSettings):
    corrected = raw.astype(np.float32) - background
    filtered = (ndi.gaussian_filter(corrected, settings.small_sigma)
                - ndi.gaussian_filter(corrected, settings.background_sigma))
    centre = float(np.median(filtered))
    sigma = float(1.4826 * np.median(np.abs(filtered - centre)))
    # Flat/noiseless synthetic frames have no meaningful robust noise estimate.
    # Do not invent an arbitrary threshold or divide by zero.
    if not np.isfinite(sigma) or sigma <= np.finfo(np.float32).eps:
        return [], 0.0
    z = filtered / sigma
    above = z > settings.threshold_sigma
    mask = above
    if settings.merge_iterations:
        mask = ndi.binary_dilation(mask, iterations=settings.merge_iterations,
                                   structure=ndi.generate_binary_structure(2, 1))
    labels, number = ndi.label(mask)
    if not number:
        return [], sigma
    ids = np.arange(1, number + 1)
    selected = np.where(above, z, 0)
    positions = ndi.maximum_position(selected, labels, ids)
    peaks = ndi.maximum(selected, labels, ids)
    radius = settings.brightness_radius
    height, width = raw.shape
    detections = []
    for (y, x), snr in zip(positions, peaks):
        y, x = int(y), int(x)
        patch = raw[max(0, y-radius):min(height, y+radius+1),
                    max(0, x-radius):min(width, x+radius+1)]
        detections.append(Detection(frame, y, x, float(np.max(patch)), float(snr)))
    return merge_close_spots(detections, settings.radius_px), sigma


def assign_events(detections: list[Detection], frames: int,
                  settings: DetectorSettings | None = None) -> list[Event]:
    """Count each bead once: same bead = within the radius during its first N frames.

    The radius is measured from the bead's last seen position, so it follows a
    flowing bead. Missed frames inside the window are allowed. Brightness is not used.
    """
    settings = settings or DetectorSettings()
    by_frame: dict[int, list[Detection]] = {}
    for detection in detections:
        if not 0 <= detection.frame < frames:
            raise ValueError("A detection has an invalid frame index.")
        by_frame.setdefault(detection.frame, []).append(detection)
    events: list[Event] = []
    active: list[Event] = []
    for frame in range(frames):
        active = [e for e in active if frame - e.first_frame < settings.max_frames]
        current = by_frame.get(frame, [])
        pairs = []
        for index, detection in enumerate(current):
            for event in active:
                distance = math.hypot(detection.y - event.last_y, detection.x - event.last_x)
                if distance <= settings.radius_px:
                    pairs.append((distance, index, event.event_id))
        joined, matched = set(), set()
        for distance, index, event_id in sorted(pairs):
            if index in joined or event_id in matched:
                continue
            joined.add(index)
            matched.add(event_id)
            detection, event = current[index], events[event_id - 1]
            detection.event_id, detection.association = event_id, SAME_BEAD
            detection.distance_px = distance
            event.last_frame, event.last_brightness = frame, detection.brightness
            event.last_y, event.last_x = detection.y, detection.x
            event.observations += 1
        for index, detection in enumerate(current):
            if index in joined:
                continue
            detection.event_id, detection.association = len(events) + 1, NEW_BEAD
            detection.distance_px = 0.0
            event = Event(detection.event_id, detection.y, detection.x, frame, frame, 1,
                          detection.brightness, detection.brightness, detection.y, detection.x)
            events.append(event)
            active.append(event)
    return events


def analyse(path: str | Path, key: str = DEFAULT_KEY,
            settings: DetectorSettings | None = None, progress=None, cancel=None) -> Analysis:
    settings = settings or DetectorSettings()
    settings.validate()
    source = Path(path).resolve()
    shape, dtype, metadata = inspect_stack(source, key)
    started = time.perf_counter()
    if shape[0] < 3:
        raise ValueError("This background method needs at least three frames; use an image stack.")
    detections, noise = [], []
    with h5py.File(source, "r") as handle:
        dataset = handle[key]
        background = temporal_background(dataset, progress, cancel)
        projection = np.full(shape[1:], -np.inf, dtype=np.float32)
        darkest = np.inf
        for frame in range(shape[0]):
            check_cancel(cancel)
            raw = dataset[frame]
            np.maximum(projection, raw, out=projection)
            darkest = min(darkest, float(raw.min()))
            found, sigma = detect_frame(raw, background, frame, settings)
            detections.extend(found)
            noise.append(sigma)
            if progress:
                progress(18 + int(77*(frame+1)/shape[0]),
                         f"Detecting beads · frame {frame+1} / {shape[0]}")
    check_cancel(cancel)
    events = assign_events(detections, shape[0], settings)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024**2), b""):
            check_cancel(cancel)
            digest.update(block)
    if progress:
        progress(98, "Preparing the combined image and count tables…")
    return Analysis(str(source), key, shape, dtype, metadata, settings, detections,
                    events, noise, projection, time.perf_counter()-started, digest.hexdigest(),
                    display_levels(darkest, float(projection.max())))
