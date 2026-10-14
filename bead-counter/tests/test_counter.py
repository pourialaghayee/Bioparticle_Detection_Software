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

from counter_core import (DEFAULT_KEY, Cancelled, Detection, DetectorSettings,
                          analyse, assign_events, discover_datasets, verify_source)
from rendering import export_results, export_boxed_stack, load_result, render_frame


def detection(frame, brightness, x=50, y=40):
    return Detection(frame, y, x, brightness, 12.0)


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
    def test_two_adjacent_frames_fading_count_once(self):
        found = [detection(0, 100), detection(1, 50)]
        events = assign_events(found, 3)
        self.assertEqual(len(events), 1)
        self.assertEqual([d.event_id for d in found], [1, 1])
        self.assertEqual(events[0].observations, 2)

    def test_rare_longer_fade_is_not_forced_into_pairs(self):
        found = [detection(i, b) for i, b in enumerate([100, 70, 40, 20, 10])]
        events = assign_events(found, 5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].last_frame, 4)

    def test_brightness_reset_starts_new_event(self):
        found = [detection(i, b) for i, b in enumerate([100, 50, 120, 60])]
        events = assign_events(found, 4)
        self.assertEqual(len(events), 2)
        self.assertEqual([d.event_id for d in found], [1, 1, 2, 2])
        self.assertEqual(found[2].association, "brightness_increase")

    def test_gap_is_never_bridged_even_if_it_is_dimmer(self):
        found = [detection(0, 100), detection(2, 50)]
        self.assertEqual(len(assign_events(found, 4)), 2)

    def test_one_pixel_displacement_is_never_linked(self):
        found = [detection(0, 100), detection(1, 50, x=51)]
        self.assertEqual(len(assign_events(found, 2)), 2)

    def test_equal_brightness_is_recorded_as_uncertain_new_event(self):
        found = [detection(0, 50), detection(1, 50)]
        self.assertEqual(len(assign_events(found, 2)), 2)
        self.assertEqual(found[1].association, "equal_brightness_unresolved")

    def test_parallel_positions_are_independent(self):
        found = [detection(0, 100), detection(0, 150, x=80),
                 detection(1, 50, x=80), detection(1, 60)]
        self.assertEqual(len(assign_events(found, 2)), 2)
        self.assertEqual([d.event_id for d in found], [1, 2, 2, 1])

    def test_empty_stack_and_invalid_duplicates(self):
        self.assertEqual(assign_events([], 3), [])
        with self.assertRaises(ValueError):
            assign_events([detection(0, 4), detection(0, 2)], 2)


class ProcessingAndExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/"test.h5"
        self.stack = make_stack(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def analyse(self):
        return analyse(self.path, DEFAULT_KEY, DetectorSettings(merge_iterations=0))

    def test_detection_and_metadata_and_input_preservation(self):
        before = self.path.read_bytes()
        result = self.analyse()
        self.assertEqual(result.shape, (11, 90, 110))
        self.assertEqual(result.metadata["pixel_width_um"], .0586)
        self.assertEqual(len(result.events), 2)
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
        with (folder/"events.csv").open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), len(result.events))
        loaded = load_result(folder)
        self.assertEqual(loaded.detections, result.detections)
        self.assertEqual(loaded.events, result.events)
        with Image.open(folder/"all_beads.png") as image:
            self.assertEqual(image.height, 90+108)
        export_boxed_stack(result, folder/"boxed_stack.tif")
        with tifffile.TiffFile(folder/"boxed_stack.tif") as movie:
            self.assertFalse(movie.is_bigtiff)
            self.assertEqual(len(movie.pages), 11)
            expected = np.asarray(render_frame(self.stack[3], result.for_frame(3)))
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

    def test_export_cannot_overwrite_input(self):
        result = self.analyse()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            export_boxed_stack(result, self.path)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
