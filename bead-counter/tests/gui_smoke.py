"""Exercise our own Qt widgets offscreen, including the real analysis worker."""
from pathlib import Path
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from counter_core import DEFAULT_KEY, DetectorSettings
from rendering import load_result
from viewer_gui import MainWindow, ProcessingWorker, StackExportWorker
import viewer_gui
from test_counter import make_stack


def wait_until(app, predicate, seconds=15):
    start = time.monotonic()
    while not predicate() and time.monotonic()-start < seconds:
        app.processEvents()
        QTest.qWait(20)
    assert predicate(), "Qt operation timed out"


app = QApplication([])
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root/"synthetic.h5"
    make_stack(source)
    window = MainWindow()
    window.show()
    window.load_source(source, DEFAULT_KEY)
    app.processEvents()
    for caption in ("Box width", "Black level", "White level", "Threshold (noise σ)",
                    "Flow rate", "Radius", "Max frames"):
        matching = [label for label in window.findChildren(QLabel) if label.text() == caption]
        assert len(matching) == 1 and matching[0].width() > 40, f"Hidden form label: {caption}"
    assert not [label for label in window.findChildren(QLabel) if "dilation" in label.text().lower()]
    stack = make_stack(root/"levels.h5")
    original = (float(stack.min()), float(stack.max()))
    assert (window.display_low.value(), window.display_high.value()) == original
    assert window.original_check.isChecked()
    window.display_high.setValue(30)
    assert not window.original_check.isChecked()
    window.original_check.setChecked(True)
    assert (window.display_low.value(), window.display_high.value()) == original
    assert window.frame_spin.maximum() == 11
    assert window.run_button.isEnabled()
    window.frame_spin.setValue(4)
    assert window.slider.value() == 4
    assert window.cached_frame == 3

    # Run through the real Count button, with a temporary output directory.
    failures = []
    window.show_error = failures.append
    window.flow_rate.setValue(0.5)
    window.radius.setValue(15)
    window.max_frames.setValue(10)
    previous_app_dir = viewer_gui.APP_DIR
    viewer_gui.APP_DIR = root
    QTest.mouseClick(window.run_button, Qt.MouseButton.LeftButton)
    assert window.worker is not None
    assert not window.run_button.isEnabled()
    wait_until(app, lambda: window.worker is None)
    viewer_gui.APP_DIR = previous_app_dir
    assert not failures, failures
    result, folder = window.result, window.result_folder
    assert result is not None and (folder/"all_beads.png").exists()
    assert (result.settings.flow_rate_ul_min, result.settings.radius_px,
            result.settings.max_frames) == (0.5, 15, 10)
    assert window.run_button.isEnabled()
    assert window.count_label.text() == str(len(result.events))
    assert window.table.rowCount() == len(result.for_frame(3))
    assert window.table.item(0, 2).text() == f"{result.for_frame(3)[0].brightness:.0f}"
    count = window.count_label.text()
    window.box_size.setValue(60)
    window.display_high.setValue(60)
    assert window.count_label.text() == count
    window.tabs.setCurrentIndex(1)
    assert not window.overview_view.pixmap_item.pixmap().isNull()
    window.delay.setValue(30)
    window.frame_spin.setValue(1)
    QTest.mouseClick(window.play_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: window.frame_spin.value() >= 3)
    QTest.mouseClick(window.play_button, Qt.MouseButton.LeftButton)
    assert not window.timer.isActive()

    saved, export_failures = [], []
    exporter = StackExportWorker(result, str(root/"boxed.tif"), 40, *original)
    exporter.completed.connect(saved.append)
    exporter.failed.connect(export_failures.append)
    exporter.start()
    wait_until(app, lambda: saved or export_failures)
    exporter.wait(3000)
    assert not export_failures, export_failures
    assert (root/"boxed.tif").exists()

    # Cancellation also works in a background GUI job.
    was_cancelled = []
    cancellation = ProcessingWorker(source, DEFAULT_KEY, DetectorSettings(), root/"cancel", 40, *original)
    cancellation.stop_requested.set()
    cancellation.cancelled.connect(lambda: was_cancelled.append(True))
    cancellation.start()
    wait_until(app, lambda: was_cancelled)
    cancellation.wait(3000)
    assert not (root/"cancel").exists()
    window.close()

if len(sys.argv) > 1:
    folder = Path(sys.argv[1])
    result = load_result(folder)
    window = MainWindow()
    window.load_source(result.source, result.dataset_key, result.original_levels)
    window.install_result(result, folder)
    # Show the frame containing the most detections so the preview is informative.
    frame = max(range(result.shape[0]), key=lambda t: len(result.for_frame(t)))
    window.frame_spin.setValue(frame+1)
    window.show()
    app.processEvents()
    QTest.qWait(100)
    output = Path(__file__).resolve().parents[1]/"viewer_preview.png"
    window.grab().save(str(output))
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    window.grab().save(str(output.with_name("overview_preview.png")))
    window.close()
print("GUI smoke checks passed: loading, original levels, detection inputs, counting worker, "
      "frame navigation, brightness table, display controls, playback, overview, TIFF worker, "
      "cancellation.")
