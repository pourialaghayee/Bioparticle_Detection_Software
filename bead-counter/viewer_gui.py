"""Native desktop viewer for Polimi bead counting."""
from __future__ import annotations

from pathlib import Path
import threading

import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSignalBlocker, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QPixmap, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QMessageBox, QInputDialog, QSpinBox, QDoubleSpinBox,
    QCheckBox, QGroupBox, QFormLayout, QSplitter, QTabWidget, QGraphicsView,
    QGraphicsScene, QSlider, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QScrollArea,
    QSizePolicy, QLayout,
)

from counter_core import (Analysis, Cancelled, DetectorSettings, analyse,
                          discover_datasets, inspect_stack, read_frame, verify_source)
from rendering import (export_results, export_boxed_stack, load_result,
                       render_frame, render_overview, brightness_text)

APP_DIR = Path(__file__).resolve().parent
STYLE = """
QMainWindow, QWidget { background: #f4f7fb; color: #172c44; font-family: 'DejaVu Sans'; font-size: 13px; }
QLabel#heading { font-size: 23px; font-weight: 700; }
QLabel#muted { color: #52677c; }
QLabel, QCheckBox { background: transparent; }
QLabel#count { font-size: 34px; font-weight: 700; color: #086c53; }
QGroupBox { background: white; border: 1px solid #d7e1ea; border-radius: 8px;
    margin-top: 14px; padding: 15px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QPushButton { background: #ffffff; border: 1px solid #c8d5e2; border-radius: 5px;
    padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #e8f1fa; }
QPushButton:disabled { color: #8c9bab; background: #edf1f5; }
QPushButton#primary { background: #176a91; color: white; border: 1px solid #176a91; }
QPushButton#primary:hover { background: #125779; }
QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #c8d5e2; padding: 5px; border-radius: 4px; }
QTableWidget { background: white; alternate-background-color: #eff5fa; border: 1px solid #d7e1ea; }
QHeaderView::section { background: #e8eff5; padding: 6px; border: none; font-weight: 600; }
QTabWidget::pane { border: 1px solid #d7e1ea; background: #101820; }
QTabBar::tab { padding: 10px 18px; background: #e5edf5; }
QTabBar::tab:selected { background: #ffffff; font-weight: 600; }
QProgressBar { border: 1px solid #d7e1ea; border-radius: 4px; background: #e6edf4; text-align: center; }
QProgressBar::chunk { background: #168066; }
QCheckBox { spacing: 6px; }
"""


def pil_pixmap(image):
    image = image.convert("RGB")
    data = image.tobytes("raw", "RGB")
    qimage = QImage(data, image.width, image.height, image.width*3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


class ImageView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.pixmap_item = self.scene().addPixmap(QPixmap())
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit = True
        self.setMinimumSize(500, 330)

    def set_image(self, image):
        self.pixmap_item.setPixmap(pil_pixmap(image))
        self.scene().setSceneRect(self.pixmap_item.boundingRect())
        if self._fit:
            self.fit_image()

    def fit_image(self):
        self._fit = True
        if not self.pixmap_item.pixmap().isNull():
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        self._fit = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        scale = self.transform().m11()*factor
        if 0.05 < scale < 20:
            self.scale(factor, factor)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.fit_image()


class ProcessingWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(object, str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, source, key, settings, root, box_size, low, high):
        super().__init__()
        self.source, self.key, self.settings = source, key, settings
        self.root, self.box_size, self.low, self.high = root, box_size, low, high
        self.stop_requested = threading.Event()

    def run(self):
        try:
            result = analyse(self.source, self.key, self.settings,
                             self.progress.emit, self.stop_requested.is_set)
            folder = export_results(result, self.root, self.box_size, self.low, self.high,
                                    self.stop_requested.is_set)
            self.completed.emit(result, str(folder))
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class StackExportWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, result, path, box_size, low, high):
        super().__init__()
        self.result, self.path = result, path
        self.box_size, self.low, self.high = box_size, low, high
        self.stop_requested = threading.Event()

    def run(self):
        try:
            export_boxed_stack(self.result, self.path, self.box_size, self.low, self.high,
                               self.progress.emit, self.stop_requested.is_set)
            self.completed.emit(self.path)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Polimi · Bead Counter")
        self.resize(1460, 920)
        self.setStyleSheet(STYLE)
        self.source = None
        self.key = None
        self.shape = None
        self.result: Analysis | None = None
        self.result_folder: Path | None = None
        self.worker = None
        self.close_pending = False
        self.raw_cache = None
        self.cached_frame = -1
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_frame)
        self._build_ui()
        self._build_menu()
        self.set_controls()

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("File")
        for title, callback in (("Load HDF5…", self.choose_source),
                                ("Open saved result…", self.choose_result),
                                ("Open results folder", self.open_results),
                                ("Quit", self.close)):
            action = QAction(title, self)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        help_menu = self.menuBar().addMenu("Help")
        instructions = QAction("Open instructions", self)
        instructions.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR/"README.md"))))
        help_menu.addAction(instructions)

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 12, 20, 14)
        header = QHBoxLayout()
        title = QLabel("Polimi  /  Bead Counter")
        title.setObjectName("heading")
        header.addWidget(title)
        subtitle = QLabel("Load a stack · inspect every frame · count fading continuations once")
        subtitle.setObjectName("muted")
        header.addStretch()
        header.addWidget(subtitle)
        outer.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setMinimumWidth(320)
        side_scroll.setMaximumWidth(410)
        side = QWidget()
        left = QVBoxLayout(side)
        left.setContentsMargins(0, 0, 10, 0)
        left.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        source_group = QGroupBox("1  Load a microscope stack")
        source_layout = QVBoxLayout(source_group)
        self.load_button = QPushButton("Load .h5 file…")
        self.load_button.clicked.connect(self.choose_source)
        source_layout.addWidget(self.load_button)
        self.file_label = QLabel("No dataset loaded")
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_layout.addWidget(self.file_label)
        self.dataset_label = QLabel("Axes: frame × row × column")
        self.dataset_label.setObjectName("muted")
        self.dataset_label.setWordWrap(True)
        source_layout.addWidget(self.dataset_label)
        self.run_button = QPushButton("Count beads in all frames")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start_analysis)
        source_layout.addWidget(self.run_button)
        left.addWidget(source_group)

        count_group = QGroupBox("2  Counted events")
        count_layout = QVBoxLayout(count_group)
        self.count_label = QLabel("—")
        self.count_label.setObjectName("count")
        count_layout.addWidget(self.count_label)
        self.total_label = QLabel("Run counting to see the total.")
        self.total_label.setWordWrap(True)
        count_layout.addWidget(self.total_label)
        rule = QLabel("Same pixel + next frame + lower brightness → same ID.\n"
                      "A rare longer fade can keep the ID.\n"
                      "Gap, rise, or equal brightness → new event.")
        rule.setWordWrap(True)
        rule.setObjectName("muted")
        count_layout.addWidget(rule)
        left.addWidget(count_group)

        visual_group = QGroupBox("Display controls")
        visual_form = QFormLayout(visual_group)
        self.box_size = QSpinBox()
        self.box_size.setRange(16, 120)
        self.box_size.setSingleStep(4)
        self.box_size.setValue(40)
        self.box_size.setSuffix(" px")
        visual_form.addRow("Box width", self.box_size)
        self.display_low = QDoubleSpinBox()
        self.display_low.setRange(-1e9, 1e9)
        self.display_low.setDecimals(1)
        self.display_low.setValue(0)
        self.display_high = QDoubleSpinBox()
        self.display_high.setRange(-1e9, 1e9)
        self.display_high.setDecimals(1)
        self.display_high.setValue(30)
        visual_form.addRow("Black level", self.display_low)
        visual_form.addRow("White level", self.display_high)
        self.labels_check = QCheckBox("Show ID and brightness (B)")
        self.labels_check.setChecked(True)
        visual_form.addRow(self.labels_check)
        note = QLabel("These controls do not change the count.\n"
                      "B = raw peak camera value in a 7 × 7 pixel patch.\n"
                      "Green: new event. Orange: fading continuation.\n"
                      "Mouse wheel: zoom. Drag: pan.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        visual_form.addRow(note)
        self.fit_button = QPushButton("Fit image")
        self.fit_button.setToolTip("Show the whole image again after zooming or panning. "
                                   "Counts and saved images are unchanged.")
        self.fit_button.clicked.connect(self.fit_images)
        visual_form.addRow(self.fit_button)
        left.addWidget(visual_group)

        self.advanced = QGroupBox("Detection settings")
        advanced_form = QFormLayout(self.advanced)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(1, 30)
        self.threshold.setSingleStep(0.5)
        self.threshold.setValue(6)
        self.threshold.valueChanged.connect(self.settings_changed)
        advanced_form.addRow("Threshold (noise σ)", self.threshold)
        self.merge = QSpinBox()
        self.merge.setRange(0, 60)
        self.merge.setValue(20)
        self.merge.valueChanged.connect(self.settings_changed)
        advanced_form.addRow("Mask dilation steps", self.merge)
        detector_note = QLabel("The defaults are shared across files. Background and noise are estimated from the file. "
                              "Changing these settings requires counting again.")
        detector_note.setObjectName("muted")
        detector_note.setWordWrap(True)
        advanced_form.addRow(detector_note)
        left.addWidget(self.advanced)

        output_group = QGroupBox("3  Saved outputs")
        output_layout = QVBoxLayout(output_group)
        self.output_label = QLabel("The combined image and count tables are saved automatically under software/results/.")
        self.output_label.setWordWrap(True)
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_layout.addWidget(self.output_label)
        self.open_button = QPushButton("Open results folder")
        self.open_button.clicked.connect(self.open_results)
        output_layout.addWidget(self.open_button)
        self.save_image_button = QPushButton("Save combined image…")
        self.save_image_button.clicked.connect(self.save_overview)
        output_layout.addWidget(self.save_image_button)
        self.save_stack_button = QPushButton("Save boxed TIFF movie…")
        self.save_stack_button.clicked.connect(self.save_stack)
        output_layout.addWidget(self.save_stack_button)
        left.addWidget(output_group)
        left.addStretch()
        # Let wrapped labels use the available width and reserve their full
        # height. A fixed width cap makes Qt underestimate their wrapped height
        # in a wider sidebar; shrinking vertically then clips the first/last lines.
        for text_label in side.findChildren(QLabel):
            text_label.setMinimumWidth(0)
            policy = QSizePolicy(
                QSizePolicy.Policy.Ignored if text_label.wordWrap() else QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Minimum)
            policy.setHeightForWidth(text_label.wordWrap())
            text_label.setSizePolicy(policy)
            if text_label.wordWrap():
                text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setWidget(side)
        splitter.addWidget(side_scroll)

        content = QWidget()
        right = QVBoxLayout(content)
        right.setContentsMargins(6, 0, 0, 0)
        self.tabs = QTabWidget()
        self.frame_view = ImageView()
        self.overview_view = ImageView()
        self.tabs.addTab(self.frame_view, "Frame viewer")
        self.tabs.addTab(self.overview_view, "All counted beads")
        self.tabs.currentChanged.connect(self.refresh_overview)
        right.addWidget(self.tabs, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        controls.addWidget(QLabel("Frame"))
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(1, 1)
        controls.addWidget(self.frame_spin)
        self.frame_total = QLabel("/ —")
        controls.addWidget(self.frame_total)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 1)
        controls.addWidget(self.slider, 1)
        controls.addWidget(QLabel("Delay"))
        self.delay = QSpinBox()
        self.delay.setRange(30, 5000)
        self.delay.setSingleStep(50)
        self.delay.setValue(350)
        self.delay.setSuffix(" ms")
        controls.addWidget(self.delay)
        right.addLayout(controls)
        self.frame_note = QLabel("Load an HDF5 stack to view the frames.")
        self.frame_note.setWordWrap(True)
        right.addWidget(self.frame_note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Position (x, y)", "Brightness B", "Status", "Counted first at"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(150)
        self.table.verticalHeader().setVisible(False)
        right.addWidget(self.table)
        splitter.addWidget(content)
        splitter.setSizes([360, 1060])
        progress_layout = QHBoxLayout()
        self.progress_label = QLabel("Ready · Load a .h5 file to begin.")
        self.progress_label.setMinimumWidth(360)
        progress_layout.addWidget(self.progress_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumWidth(330)
        progress_layout.addWidget(self.progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_job)
        progress_layout.addWidget(self.cancel_button)
        outer.addLayout(progress_layout)
        self.setCentralWidget(root)

        self.slider.valueChanged.connect(self.frame_spin.setValue)
        self.frame_spin.valueChanged.connect(self.change_frame)
        self.delay.valueChanged.connect(lambda value: self.timer.setInterval(value))
        for spin in (self.box_size, self.display_low, self.display_high):
            spin.valueChanged.connect(self.refresh_display)
        self.labels_check.toggled.connect(self.refresh_display)

    def set_controls(self):
        busy = self.worker is not None
        loaded = self.source is not None
        analysed = self.result is not None
        self.load_button.setEnabled(not busy)
        self.run_button.setEnabled(loaded and not busy)
        self.advanced.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.play_button.setEnabled(loaded and not busy)
        self.frame_spin.setEnabled(loaded and not busy)
        self.slider.setEnabled(loaded and not busy)
        self.open_button.setEnabled(self.result_folder is not None and not busy)
        self.save_image_button.setEnabled(analysed and not busy)
        self.save_stack_button.setEnabled(analysed and not busy)

    def choose_source(self):
        if self.worker is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load microscope HDF5 stack", str(APP_DIR.parent),
                                             "HDF5 files (*.h5 *.hdf5);;All files (*)")
        if not path:
            return
        try:
            choices = discover_datasets(path)
            if not choices:
                raise ValueError("No numeric 3-D image dataset was found in this file.")
            key = choices[0]["key"]
            if len(choices) > 1:
                names = [f"{d['key']}    {d['shape']}    {d['dtype']}" for d in choices]
                selection, accepted = QInputDialog.getItem(self, "Select image data",
                    "Choose axes (frame, row, column):", names, 0, False)
                if not accepted:
                    return
                key = choices[names.index(selection)]["key"]
            self.load_source(path, key)
        except Exception as exc:
            self.show_error(str(exc))

    def load_source(self, path, key):
        shape, dtype, metadata = inspect_stack(path, key)
        self.stop_play()
        self.source = str(Path(path).resolve())
        self.key, self.shape = key, shape
        self.result, self.result_folder = None, None
        self.raw_cache, self.cached_frame = None, -1
        self.file_label.setText(QFontMetrics(self.file_label.font()).elidedText(
            Path(path).name, Qt.TextElideMode.ElideMiddle, 290))
        self.file_label.setToolTip(self.source)
        self.dataset_label.setText(f"{shape[0]} frames · {shape[2]} × {shape[1]} pixels · {dtype}")
        self.dataset_label.setToolTip(key)
        self.frame_spin.setRange(1, shape[0])
        self.slider.setRange(1, shape[0])
        self.frame_total.setText(f"/ {shape[0]}")
        self.frame_spin.setValue(1)
        self.count_label.setText("—")
        self.total_label.setText("Run counting to see the total.")
        self.output_label.setText("Outputs will be saved automatically under software/results/.")
        self.overview_view.pixmap_item.setPixmap(QPixmap())
        self.tabs.setCurrentIndex(0)
        self.progress.setValue(0)
        self.progress_label.setText("Stack loaded · raw frames are ready to view.")
        self.set_controls()
        self.change_frame(1)

    def valid_levels(self):
        low, high = self.display_low.value(), self.display_high.value()
        if high <= low:
            self.progress_label.setText("Display white level must be above black level.")
            return None
        return low, high

    def settings_changed(self, *_):
        if self.result and (self.threshold.value() != self.result.settings.threshold_sigma
                            or self.merge.value() != self.result.settings.merge_iterations):
            self.progress_label.setText("Detection settings changed · count again to apply them.")

    def start_analysis(self):
        if self.source is None or self.worker is not None:
            return
        levels = self.valid_levels()
        if levels is None:
            return
        self.stop_play()
        settings = DetectorSettings(threshold_sigma=self.threshold.value(),
                                    merge_iterations=self.merge.value())
        self.worker = ProcessingWorker(self.source, self.key, settings, APP_DIR/"results",
                                       self.box_size.value(), *levels)
        self.worker.progress.connect(self.update_progress)
        self.worker.completed.connect(self.analysis_completed)
        self.worker.failed.connect(self.job_failed)
        self.worker.cancelled.connect(self.job_cancelled)
        self.worker.finished.connect(self.job_finished)
        self.progress.setValue(0)
        self.progress_label.setText("Counting all frames…")
        self.set_controls()
        self.worker.start()

    def update_progress(self, value, message):
        self.progress.setValue(value)
        self.progress_label.setText(message)

    def analysis_completed(self, result, folder):
        self.install_result(result, Path(folder))
        self.progress.setValue(100)
        self.progress_label.setText("Complete · combined image and count tables saved.")

    def install_result(self, result, folder):
        self.result, self.result_folder = result, Path(folder)
        self.source, self.key, self.shape = result.source, result.dataset_key, result.shape
        self.threshold.setValue(result.settings.threshold_sigma)
        self.merge.setValue(result.settings.merge_iterations)
        self.count_label.setText(str(len(result.events)))
        repeats = len(result.detections)-len(result.events)
        self.total_label.setText(f"{len(result.detections)} frame detections · "
                                f"{repeats} fading continuations counted once.\n"
                                "Candidate count — inspect the boxes to check accuracy.")
        self.output_label.setText(str(folder))
        self.progress.setValue(100)
        self.progress_label.setText("Result ready · combined image and count tables saved.")
        self.change_frame(self.frame_spin.value())
        self.refresh_overview(force=True)
        self.set_controls()

    def choose_result(self):
        if self.worker is not None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Select a saved result folder", str(APP_DIR/"results"))
        if not folder:
            return
        try:
            result = load_result(folder)
            if not Path(result.source).is_file():
                source, _ = QFileDialog.getOpenFileName(self, "Locate the original HDF5 file", str(APP_DIR.parent),
                    "HDF5 files (*.h5 *.hdf5)")
                if not source:
                    return
                verify_source(result, source)
            else:
                verify_source(result)
            self.load_source(result.source, result.dataset_key)
            self.install_result(result, folder)
            self.progress.setValue(100)
            self.progress_label.setText("Saved result opened · no detection rerun needed.")
        except Exception as exc:
            self.show_error(str(exc))

    def change_frame(self, number):
        if self.source is None:
            return
        with QSignalBlocker(self.slider):
            self.slider.setValue(number)
        frame = number-1
        try:
            if self.cached_frame != frame:
                self.raw_cache = read_frame(self.source, self.key, frame)
                self.cached_frame = frame
            found = self.result.for_frame(frame) if self.result else []
            levels = self.valid_levels()
            if levels is None:
                return
            image = render_frame(self.raw_cache, found, self.box_size.value(), *levels,
                                 self.labels_check.isChecked())
            self.frame_view.set_image(image)
            if self.result:
                new = sum(d.association != "stationary_fade" for d in found)
                self.frame_note.setText(f"Frame {number}/{self.shape[0]}  ·  {len(found)} detections  ·  "
                                       f"{new} new events  ·  {len(found)-new} fading continuations")
            else:
                self.frame_note.setText(f"Frame {number}/{self.shape[0]} · raw view; counting has not run yet.")
            self.fill_table(found)
        except Exception as exc:
            self.stop_play()
            self.show_error(str(exc))

    def fill_table(self, found):
        self.table.setRowCount(len(found))
        for row, detection in enumerate(found):
            status = {"stationary_fade": "Fading · same ID", "new_position": "New",
                      "brightness_increase": "Rise · new event",
                      "equal_brightness_unresolved": "Equal B · uncertain"}[detection.association]
            first = self.result.events[detection.event_id-1].first_frame+1
            values = [str(detection.event_id), f"{detection.x}, {detection.y}",
                      brightness_text(detection.brightness), status, str(first)]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def refresh_display(self, *_):
        if self.source:
            self.change_frame(self.frame_spin.value())
            self.refresh_overview(force=True)

    def refresh_overview(self, *_, force=False):
        if self.result is None or (not force and self.tabs.currentIndex() != 1):
            return
        levels = self.valid_levels()
        if levels:
            self.overview_view.set_image(render_overview(self.result, self.box_size.value(), *levels,
                                                        self.labels_check.isChecked()))

    def fit_images(self):
        self.frame_view.fit_image()
        self.overview_view.fit_image()

    def toggle_play(self):
        if self.timer.isActive():
            self.stop_play()
        else:
            if self.frame_spin.value() == self.frame_spin.maximum():
                self.frame_spin.setValue(1)
            self.tabs.setCurrentIndex(0)
            self.timer.start(self.delay.value())
            self.play_button.setText("Ⅱ Pause")

    def stop_play(self):
        self.timer.stop()
        self.play_button.setText("▶ Play")

    def advance_frame(self):
        number = self.frame_spin.value()
        if number >= self.frame_spin.maximum():
            self.stop_play()
        else:
            self.frame_spin.setValue(number+1)

    def cancel_job(self):
        if self.worker:
            self.worker.stop_requested.set()
            self.progress_label.setText("Cancelling after the current processing step…")
            self.cancel_button.setEnabled(False)

    def job_cancelled(self):
        self.progress_label.setText("Cancelled · the input file was not changed.")
        self.progress.setValue(0)

    def job_failed(self, message):
        self.progress_label.setText("Processing failed. See the error message.")
        self.show_error(message)

    def job_finished(self):
        old = self.worker
        self.worker = None
        if old:
            old.deleteLater()
        self.set_controls()
        if self.close_pending:
            self.close()

    def open_results(self):
        folder = self.result_folder or APP_DIR/"results"
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def save_overview(self):
        if not self.result:
            return
        levels = self.valid_levels()
        if levels is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save combined bead image",
            str(self.result_folder/"all_beads_current_view.png"), "PNG image (*.png)")
        if not path:
            return
        try:
            render_overview(self.result, self.box_size.value(), *levels, self.labels_check.isChecked()).save(path)
            self.progress_label.setText(f"Image saved: {Path(path).name}")
        except Exception as exc:
            self.show_error(str(exc))

    def save_stack(self):
        if not self.result or self.worker:
            return
        levels = self.valid_levels()
        if levels is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save boxed TIFF movie",
            str(self.result_folder/"boxed_stack.tif"), "TIFF stack (*.tif *.tiff)")
        if not path:
            return
        self.stop_play()
        self.worker = StackExportWorker(self.result, path, self.box_size.value(), *levels)
        self.worker.progress.connect(self.update_progress)
        self.worker.completed.connect(lambda saved: self.progress_label.setText(f"Boxed movie saved: {Path(saved).name}"))
        self.worker.failed.connect(self.job_failed)
        self.worker.cancelled.connect(self.job_cancelled)
        self.worker.finished.connect(self.job_finished)
        self.set_controls()
        self.worker.start()

    def show_error(self, message):
        QMessageBox.critical(self, "Bead Counter", message)

    def closeEvent(self, event):
        self.stop_play()
        if self.worker and self.worker.isRunning():
            self.close_pending = True
            self.cancel_job()
            event.ignore()
        else:
            event.accept()


def run_gui(source=None, key=None, saved_result=None):
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Polimi Bead Counter")
    window = MainWindow()
    if saved_result:
        result = load_result(saved_result)
        verify_source(result)
        window.load_source(result.source, result.dataset_key)
        window.install_result(result, saved_result)
    elif source:
        choices = discover_datasets(source)
        if not choices:
            raise ValueError("No numeric 3-D image dataset was found.")
        window.load_source(source, key or choices[0]["key"])
    window.show()
    return app.exec()
