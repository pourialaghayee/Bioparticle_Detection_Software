"""Tests of scientific counting rules, HDF5 processing, and saved outputs."""
from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import h5py
import numpy as np
from PIL import Image
import tifffile

from counter_core import (DEFAULT_KEY, Cancelled, Detection, DetectorSettings, analyse,
                          assign_events, discover_datasets, intensity_range,
                          merge_close_spots, verify_source)
from rendering import export_results, export_boxed_stack, load_result, render_frame


def detection(frame, brightness=50, x=50, y=40):
    return Detection(frame, y, x, brightness, 12.0)


def count(found, frames, radius=20, max_frames=7):
    return assign_events(found, frames, DetectorSettings(radius_px=radius, max_frames=max_frames))


def make_stack(path):
    rng = np.random.default_rng(102)
    stack = rng.poisson(2, (11, 90, 110)).astype(np.uint16)
    yy, xx = np.mgrid[:90, :110]
    spot = np.exp(-((yy-40)**2+(xx-50)**2)/(2*1.5**2))
    for frame, amplitude in ((3, 100), (4, 65), (7, 80)):
        stack[frame] += np.rint(amplitude*spot).astype(np.uint16)
    stack[:, 5, 5] = 500  # static hot pixel must be removed by temporal background
    with h5py.File(path, "w") as handle:
        dataset = handle.create_dataset(DEFAULT_KEY, data=stack)
        dataset.attrs["element_size_um"] = [1, .0586, .0586]
    return stack


class CountingRules(unittest.TestCase):
    def test_single_frame_bead_counts_once(self):
        events = count([detection(3)], 10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].observations, 1)

    def test_moving_bead_within_radius_is_one_bead(self):
        found = [detection(i, x=50+5*i) for i in range(4)]
        events = count(found, 10)
        self.assertEqual(len(events), 1)
        self.assertEqual([d.association for d in found],
                         ["new_bead", "same_bead", "same_bead", "same_bead"])
        self.assertEqual(found[1].distance_px, 5)
        self.assertEqual(events[0].displacement_px, 15)

    def test_radius_follows_last_position(self):
        # 30 px in total from the first position, but 15 px per frame.
        found = [detection(0, x=50), detection(1, x=65), detection(2, x=80)]
        self.assertEqual(len(count(found, 5)), 1)

    def test_bead_fading_below_threshold_and_returning_is_one_bead(self):
        found = [detection(0), detection(1), detection(4, x=53)]
        events = count(found, 10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].last_frame, 4)

    def test_brightness_change_does_not_matter(self):
        found = [detection(0, 100), detection(1, 150), detection(2, 20)]
        self.assertEqual(len(count(found, 3)), 1)

    def test_outside_radius_is_a_new_bead(self):
        found = [detection(0), detection(1, x=75)]
        self.assertEqual(len(count(found, 2)), 2)

    def test_window_counts_from_first_frame(self):
        found = [detection(i) for i in range(9)]
        events = count(found, 9, max_frames=7)
        self.assertEqual(len(events), 2)
        self.assertEqual((events[0].first_frame, events[0].last_frame, events[0].observations), (0, 6, 7))
        self.assertEqual(events[1].first_frame, 7)
        self.assertEqual(len(count([detection(0), detection(7)], 9, max_frames=7)), 2)

    def test_max_frames_one_counts_every_detection(self):
        self.assertEqual(len(count([detection(i) for i in range(4)], 4, max_frames=1)), 4)

    def test_nearest_spot_joins_and_the_other_is_new(self):
        found = [detection(0, x=50), detection(1, x=65), detection(1, x=55)]
        events = count(found, 2)
        self.assertEqual(len(events), 2)
        self.assertEqual(found[2].event_id, 1)
        self.assertEqual(found[1].association, "new_bead")

    def test_parallel_beads_are_independent(self):
        found = [detection(0, x=50), detection(0, x=300),
                 detection(1, x=305), detection(1, x=54)]
        self.assertEqual(len(count(found, 2)), 2)
        self.assertEqual([d.event_id for d in found], [1, 2, 2, 1])

    def test_close_spots_in_one_frame_merge_keeping_brightest(self):
        close = [detection(0, 40, x=50), detection(0, 90, x=55), detection(0, 60, x=80)]
        kept = merge_close_spots(close, 20)
        self.assertEqual([(d.x, d.brightness) for d in kept], [(55, 90), (80, 60)])

    def test_empty_stack_and_invalid_frames(self):
        self.assertEqual(count([], 3), [])
        with self.assertRaises(ValueError):
            count([detection(5)], 3)

    def test_settings_validation_and_old_saved_settings(self):
        for bad in (dict(radius_px=0), dict(max_frames=0), dict(flow_rate_ul_min=-1)):
            with self.assertRaises(ValueError):
                DetectorSettings(**bad).validate()
        DetectorSettings(flow_rate_ul_min=0.5).validate()
        old = DetectorSettings.from_saved({"threshold_sigma": 5, "merge_iterations": 20, "removed": 1})
        self.assertEqual((old.threshold_sigma, old.radius_px, old.max_frames), (5, 20, 7))


class ProcessingAndExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/"test.h5"
        self.stack = make_stack(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def analyse(self):
        return analyse(self.path, DEFAULT_KEY, DetectorSettings(flow_rate_ul_min=5))

    def test_detection_and_metadata_and_input_preservation(self):
        before = self.path.read_bytes()
        result = self.analyse()
        self.assertEqual(result.shape, (11, 90, 110))
        self.assertEqual(result.metadata["pixel_width_um"], .0586)
        # Frames 3, 4 and 7 at one position fall inside one bead's 7-frame window.
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].observations, 3)
        self.assertEqual(result.original_levels, (float(self.stack.min()), float(self.stack.max())))
        self.assertEqual(intensity_range(self.path, DEFAULT_KEY), result.original_levels)
        self.assertTrue(np.array_equal(result.projection, self.stack.max(axis=0)))
        centres = {(d.frame, d.y, d.x) for d in result.detections}
        for frame in (3, 4, 7):
            self.assertIn((frame, 40, 50), centres)
        self.assertFalse(any(d.y == 5 and d.x == 5 for d in result.detections))
        self.assertEqual(self.path.read_bytes(), before)

    def test_csv_image_reload_and_boxed_movie_are_consistent(self):
        result = self.analyse()
        folder = export_results(result, self.root/"results")
        summary = json.loads((folder/"summary.json").read_text())
        self.assertEqual(summary["counted_events"], len(result.events))
        self.assertEqual(summary["flow_rate_ul_min"], 5)
        self.assertEqual(summary["settings"]["radius_px"], 20)
        self.assertEqual(summary["display"]["minimum"], float(self.stack.min()))
        with (folder/"events.csv").open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), len(result.events))
        loaded = load_result(folder)
        self.assertEqual(loaded.detections, result.detections)
        self.assertEqual(loaded.events, result.events)
        self.assertEqual(loaded.settings, result.settings)
        self.assertEqual(loaded.original_levels, result.original_levels)
        with Image.open(folder/"all_beads.png") as image:
            self.assertEqual(image.height, 90+108)
        export_boxed_stack(result, folder/"boxed_stack.tif")
        with tifffile.TiffFile(folder/"boxed_stack.tif") as movie:
            self.assertFalse(movie.is_bigtiff)
            self.assertEqual(len(movie.pages), 11)
            expected = np.asarray(render_frame(self.stack[3], result.for_frame(3),
                                               40, *result.original_levels))
            np.testing.assert_array_equal(movie.pages[3].asarray(), expected)
        # Each rerun creates a separate directory, preserving previous runs.
        self.assertNotEqual(export_results(result, self.root/"results"), folder)

    def test_cancel_does_not_leave_partial_outputs(self):
        with self.assertRaises(Cancelled):
            analyse(self.path, cancel=lambda: True)
        result = self.analyse()
        with self.assertRaises(Cancelled):
            export_results(result, self.root/"cancelled", cancel=lambda: True)
        self.assertEqual(list((self.root/"cancelled").iterdir()), [])
        with self.assertRaises(Cancelled):
            export_boxed_stack(result, self.root/"cancelled.tif", cancel=lambda: True)
        self.assertFalse((self.root/"cancelled.tif").exists())
        self.assertFalse((self.root/"cancelled.tif.partial").exists())

    def test_flat_frames_produce_zero_candidates(self):
        with h5py.File(self.root/"flat.h5", "w") as handle:
            handle.create_dataset("image", data=np.ones((5, 30, 30), np.uint16))
        result = analyse(self.root/"flat.h5", "image")
        self.assertEqual(result.events, [])
        self.assertEqual(result.detections, [])

    def test_discovery_excludes_non_image_metadata(self):
        with h5py.File(self.path, "a") as handle:
            handle.create_dataset("settings", data=np.arange(5))
            handle.create_dataset("other_3d", data=np.zeros((3, 10, 10)))
        choices = discover_datasets(self.path)
        self.assertEqual([c["key"] for c in choices], [DEFAULT_KEY, "other_3d"])

    def test_saved_overlays_reject_different_source_with_same_shape(self):
        result = self.analyse()
        verify_source(result)
        with h5py.File(self.path, "a") as handle:
            handle[DEFAULT_KEY][0, 0, 0] = 999
        with self.assertRaises(ValueError):
            verify_source(result)

    def test_results_from_version_1_still_open(self):
        folder = export_results(self.analyse(), self.root/"results")
        summary = json.loads((folder/"summary.json").read_text())
        summary["settings"]["merge_iterations"] = 20
        del summary["settings"]["radius_px"], summary["original_display_levels"]
        (folder/"summary.json").write_text(json.dumps(summary))
        loaded = load_result(folder)
        self.assertEqual(loaded.settings.radius_px, 20)
        self.assertIsNone(loaded.original_levels)

    def test_export_cannot_overwrite_input(self):
        result = self.analyse()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            export_boxed_stack(result, self.path)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
