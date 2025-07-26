#!/usr/bin/python3
import sys

# Prevent PyAutoGUI and pywinctl from setting Process DPI Awareness,
# which Qt tries to do then throws warnings about it.
# The unittest workaround significantly increases
# build time, boot time and build size with PyInstaller.
# https://github.com/asweigart/pyautogui/issues/663#issuecomment-1296719464
# QT doesn't call those from Python/ctypes, meaning we can stop other programs from setting it.
if sys.platform == "win32":
    import ctypes

    def do_nothing(*_):
        ...

    # pyautogui._pyautogui_win.py
    ctypes.windll.user32.SetProcessDPIAware = do_nothing  # pyright: ignore[reportAttributeAccessIssue]
    # pymonctl._pymonctl_win.py
    # pywinbox._pywinbox_win.py
    ctypes.windll.shcore.SetProcessDpiAwareness = do_nothing  # pyright: ignore[reportAttributeAccessIssue]

import signal
from collections.abc import Callable
from copy import deepcopy
from types import FunctionType
from typing import NoReturn, override

import cv2
from cv2.typing import MatLike
from gen import design
from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

import error_messages
from capture_method import CaptureMethodBase, CaptureMethodEnum, change_capture_method
from region_selection import select_window
from user_profile import DEFAULT_PROFILE
from utils import (
    BGRA_CHANNEL_COUNT,
    FROZEN,
    ONE_SECOND,
    ZDCURTAIN_VERSION,
    is_valid_image,
    list_processes,
)


class ZDCurtain(QMainWindow, design.Ui_MainWindow):
    show_error_signal = QtCore.Signal(FunctionType)

    # Timers
    timer_live_image = QtCore.QTimer()
    timer_live_image.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer_start_image = QtCore.QTimer()
    timer_start_image.setTimerType(QtCore.Qt.TimerType.PreciseTimer)

    def __init__(self):
        super().__init__()

        self.hwnd = 0
        self.last_saved_settings = deepcopy(DEFAULT_PROFILE)
        self.capture_method = CaptureMethodBase(self)
        self.is_running = False

        # Setup global error handling
        def _show_error_signal_slot(error_message_box: Callable[..., object]):
            return error_message_box()

        self.show_error_signal.connect(_show_error_signal_slot)
        sys.excepthook = error_messages.make_excepthook(self)

        self.setupUi(self)
        self.setWindowTitle(
            f"ZDCurtain v.{ZDCURTAIN_VERSION}"
        )

        self.settings_dict = deepcopy(DEFAULT_PROFILE)

        change_capture_method(CaptureMethodEnum.WINDOWS_GRAPHICS_CAPTURE, self)

        # connecting button clicks to functions
        self.select_window_button.clicked.connect(lambda: select_window(self))

        # live image preview
        self.timer_live_image.timeout.connect(
            lambda: self.__update_live_image_details(None, called_from_timer=True)
        )
        self.timer_live_image.start(int(ONE_SECOND / self.settings_dict["fps_limit"]))

        self.show()

    def __get_capture_for_comparison(self):
        """Grab capture region and resize for comparison."""
        capture = self.capture_method.get_frame()

        # This most likely means we lost capture
        # (ie the captured window was closed, crashed, lost capture device, etc.)
        if not is_valid_image(capture):
            # Try to recover by using the window name
            if self.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE:
                self.live_image.setText("Waiting for capture device...")
            else:
                message = "Trying to recover window..."
                if self.settings_dict["capture_method"] == CaptureMethodEnum.BITBLT:
                    message += "\n(captured window may be incompatible with BitBlt)"
                self.live_image.setText(message)
                recovered = self.capture_method.recover_window(
                    self.settings_dict["captured_window_title"]
                )
                if recovered:
                    capture = self.capture_method.get_frame()

        self.__update_live_image_details(capture)
        return capture

    def __update_live_image_details(
        self,
        capture: MatLike | None,
        *,
        called_from_timer: bool = False,
    ):
        if called_from_timer:
            if self.is_running:
                return
            capture = self.capture_method.get_frame()

        # Update title from target window or Capture Device name
        capture_region_window_label = (
            self.settings_dict["capture_device_name"]
            if self.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
            else self.settings_dict["captured_window_title"]
        )
        self.capture_region_window_label.setText(capture_region_window_label)

        # Simply clear if "live capture region" setting is off
        if not (self.settings_dict["live_capture_region"] and capture_region_window_label):
            self.live_image.clear()
        # Set live image in UI
        else:
            set_preview_image(self.live_image, capture)

    @override
    def closeEvent(self, event: QtGui.QCloseEvent | None = None):  # noqa: N802
        """Exit safely when closing the window."""

        def exit_program() -> NoReturn:
            self.capture_method.close()
            if event is not None:
                event.accept()
            sys.exit()


def set_preview_image(qlabel: QLabel, image: MatLike | None):
    if not is_valid_image(image):
        # Clear current pixmap if no image. But don't clear text
        if not qlabel.text():
            qlabel.clear()
    else:
        height, width, channels = image.shape

        if channels == BGRA_CHANNEL_COUNT:
            image_format = QtGui.QImage.Format.Format_RGBA8888
            capture = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        else:
            image_format = QtGui.QImage.Format.Format_BGR888
            capture = image

        qimage = QtGui.QImage(capture.data, width, height, width * channels, image_format)
        qlabel.setPixmap(
            QtGui.QPixmap(qimage).scaled(
                qlabel.size(),
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )


def is_already_open():
    # When running directly in Python, any ZDCurtain process means it's already open
    # When bundled, we must ignore itself and the splash screen
    max_processes = 3 if FROZEN else 1
    process_name = "ZDCurtain.exe" if sys.platform == "win32" else "ZDCurtain.elf"
    return list_processes().count(process_name) >= max_processes


def main():
    # Best to call setStyle before the QApplication constructor
    # https://doc.qt.io/qt-6/qapplication.html#setStyle-1
    QApplication.setStyle("fusion")
    # Call to QApplication outside the try-except so we can show error messages
    app = QApplication(sys.argv)
    try:
        if is_already_open():
            error_messages.already_open()

        ZDCurtain()

        if not FROZEN:
            # Kickoff the event loop every so often so we can handle KeyboardInterrupt (^C)
            timer = QtCore.QTimer()
            timer.timeout.connect(lambda: None)
            timer.start(500)

        exit_code = app.exec()
    except Exception as exception:  # noqa: BLE001 # We really want to catch everything here
        error_messages.handle_top_level_exceptions(exception)

    # Catch Keyboard Interrupts for a clean close
    signal.signal(signal.SIGINT, lambda code, _: sys.exit(code))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
