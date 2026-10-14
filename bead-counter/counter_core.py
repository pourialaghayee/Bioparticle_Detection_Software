"""Read microscope HDF5 stacks, detect spots, and count stationary fading events.

No GUI dependency. Input files are always opened read-only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
import hashlib
import time

import h5py
import numpy as np
from scipy import ndimage as ndi

VERSION = "1.0.0"
DEFAULT_KEY = "measurement/IDSmeasurement/t0/c0/image"


class Cancelled(Exception):
    """The user cancelled processing before an output was committed."""


@dataclass(frozen=True)
class DetectorSettings:
    threshold_sigma: float = 6.0
    small_sigma: float = 1.5
    background_sigma: float = 12.0
    merge_iterations: int = 20
    brightness_radius: int = 3

    def validate(self):
        if not np.isfinite(self.threshold_sigma) or self.threshold_sigma <= 0:
            raise ValueError("Detection threshold must be positive.")
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
    association: str = "new_position"


@dataclass
class Event:
    event_id: int
    y: int
    x: int
    first_frame: int
    last_frame: int
    observations: int
    first_brightness: float
    last_brightness: float
    start_reason: str


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

    def for_frame(self, frame: int) -> list[Detection]:
        return [d for d in self.detections if d.frame == frame]

    def summary(self) -> dict:
        counts = np.bincount([d.frame for d in self.detections], minlength=self.shape[0])
        return {
            "software_version": VERSION,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "dataset_key": self.dataset_key,
            "shape_frames_y_x": list(self.shape),
            "dtype": self.dtype,
            "metadata": self.metadata,
            "settings": asdict(self.settings),
            "counted_events": len(self.events),
            "frame_detections": len(self.detections),
            "continuations_not_counted_again": len(self.detections) - len(self.events),
            "events_seen_in_multiple_frames": sum(e.observations > 1 for e in self.events),
            "events_seen_in_more_than_two_frames": sum(e.observations > 2 for e in self.events),
            "same_pixel_non_fading_new_events": sum(
                e.start_reason in {"brightness_increase", "equal_brightness_unresolved"}
                for e in self.events),
            "per_frame_detections": counts.tolist(),
            "per_frame_filtered_noise_sigma": self.noise,
            "frames_with_zero_noise_skipped": [i+1 for i, sigma in enumerate(self.noise) if sigma == 0],
            "analysis_seconds": self.seconds,
            "association_rule": (
                "Only adjacent frames, exactly the same detected integer (x,y), and a strictly "
                "lower raw local-peak brightness retain an event ID. Continued fading can "
                "extend beyond two frames. A gap, changed coordinate, rise, or equal brightness "
                "starts a new event. Equal brightness is recorded as unresolved."
            ),
            "brightness_definition": (
                f"Maximum raw camera value in a {(2*self.settings.brightness_radius+1)} x "
                f"{(2*self.settings.brightness_radius+1)} pixel patch around the detected centre; "
                "camera counts, not photons. No bright/dim classification."
            ),
            "interpretation": (
                "Counts are algorithmic bead candidates, not a validated physical bead total. "
                "Detection settings are inherited from the previous notebook; manual review "
                "is still required. Maximum projection is a visual summary, not the counter."
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
    return detections, sigma


def assign_events(detections: list[Detection], frames: int) -> list[Event]:
    """The user's exact-position, adjacent-frame, decreasing-brightness rule.

    Never bridge a missing frame. Never match to a neighbouring pixel.
    No fixed two-frame cap: a rare longer fade can keep its ID.
    """
    by_frame: dict[int, list[Detection]] = {}
    for detection in detections:
        if not 0 <= detection.frame < frames:
            raise ValueError("A detection has an invalid frame index.")
        by_frame.setdefault(detection.frame, []).append(detection)
    events: list[Event] = []
    previous: dict[tuple[int, int], Detection] = {}
    for frame in range(frames):
        current = {}
        for detection in by_frame.get(frame, []):
            position = (detection.y, detection.x)
            if position in current:
                raise ValueError("Two detections cannot have the same centre in one frame.")
            last = previous.get(position)
            if last is not None and detection.brightness < last.brightness:
                detection.event_id = last.event_id
                detection.association = "stationary_fade"
                event = events[detection.event_id - 1]
                event.last_frame = frame
                event.last_brightness = detection.brightness
                event.observations += 1
            else:
                reason = "new_position"
                if last is not None:
                    reason = ("brightness_increase" if detection.brightness > last.brightness
                              else "equal_brightness_unresolved")
                detection.event_id = len(events) + 1
                detection.association = reason
                events.append(Event(detection.event_id, detection.y, detection.x,
                                    frame, frame, 1, detection.brightness,
                                    detection.brightness, reason))
            current[position] = detection
        previous = current
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
        for frame in range(shape[0]):
            check_cancel(cancel)
            raw = dataset[frame]
            np.maximum(projection, raw, out=projection)
            found, sigma = detect_frame(raw, background, frame, settings)
            detections.extend(found)
            noise.append(sigma)
            if progress:
                progress(18 + int(77*(frame+1)/shape[0]),
                         f"Detecting beads · frame {frame+1} / {shape[0]}")
    check_cancel(cancel)
    events = assign_events(detections, shape[0])
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024**2), b""):
            check_cancel(cancel)
            digest.update(block)
    if progress:
        progress(98, "Preparing the combined image and count tables…")
    return Analysis(str(source), key, shape, dtype, metadata, settings, detections,
                    events, noise, projection, time.perf_counter()-started, digest.hexdigest())
