"""Regression checks for readable sidebar text and resetting the image view."""
from pathlib import Path
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QSplitter
from shiboken6 import delete
from viewer_gui import MainWindow


class SidebarAndView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.settle()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        # Dispose native widgets while QApplication still exists. Waiting for
        # Python's shutdown order can destroy the graphics scene after Qt exits.
        delete(self.window)
        self.window = None
        self.app.processEvents()

    def settle(self):
        self.app.processEvents()
        QTest.qWait(10)
        self.app.processEvents()

    def test_sidebar_text_fits_after_count_updates_and_resizing(self):
        window = self.window
        scroll = window.findChild(QScrollArea)
        side = scroll.widget()
        window.output_label.setText('/example/results/' + 'long_recording_name_'*8)
        for height in (650, 920):
            window.resize(1460, height)
            for width in (320, 360, 410):
                window.findChild(QSplitter).setSizes([width, 1060])
                for detections, repeats in ((213, 0), (123456, 12345)):
                    with self.subTest(height=height, width=width, detections=detections):
                        window.count_label.setText(str(detections-repeats))
                        window.total_label.setText(
                            f'{detections} frame detections · {repeats} fading continuations counted once.\n'
                            'Candidate count — inspect the boxes to check accuracy.')
                        self.settle()
                        for label in side.findChildren(QLabel):
                            if label.wordWrap():
                                self.assertGreaterEqual(
                                    label.height(), label.heightForWidth(label.width()),
                                    f'Clipped sidebar text: {label.text()!r}')
                                self.assertTrue(label.parentWidget().rect().contains(label.geometry()))
                        self.assertGreaterEqual(window.count_label.height(), window.count_label.fontMetrics().height())
                        self.assertGreater(window.total_label.y(), window.count_label.geometry().bottom())
                        self.assertLessEqual(side.width(), scroll.viewport().width()+1)

    def test_fit_image_restores_whole_view_without_changing_count(self):
        window = self.window
        window.count_label.setText('213')
        view = window.frame_view
        view.set_image(Image.new('RGB', (1600, 900)))
        self.settle()
        view._fit = False
        view.scale(4, 4)
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        before = view.mapToScene(view.viewport().rect()).boundingRect()
        self.assertFalse(before.contains(view.pixmap_item.boundingRect()))
        window.findChild(QScrollArea).ensureWidgetVisible(window.fit_button)
        QTest.mouseClick(window.fit_button, Qt.MouseButton.LeftButton)
        self.settle()
        visible = view.mapToScene(view.viewport().rect()).boundingRect().adjusted(-1, -1, 1, 1)
        self.assertTrue(visible.contains(view.pixmap_item.boundingRect()))
        self.assertEqual(window.count_label.text(), '213')


if __name__ == '__main__':
    unittest.main(verbosity=2)
