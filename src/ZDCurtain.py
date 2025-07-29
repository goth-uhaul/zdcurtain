#!/usr/bin/python3
import sys
from time import perf_counter_ns

# Prevent PyAutoGUI and pywinctl from setting Process DPI Awareness,
# which Qt tries to do then throws warnings about it.
# The unittest workaround significantly increases
# build time, boot time and build size with PyInstaller.
# https://github.com/asweigart/pyautogui/issues/663#issuecomment-1296719464
# QT doesn't call those from Python/ctypes, meaning we can stop other programs from setting it.
if sys.platform == "win32":
    import ctypes

    def do_nothing(*_): ...

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
from gen import design, settings
from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

import error_messages
from capture_method import CaptureMethodBase, CaptureMethodEnum, change_capture_method
from frame_analysis import get_comparison_method_by_name, get_top_third_of_capture, is_black
from region_selection import select_window
from settings import open_settings
from user_profile import DEFAULT_PROFILE
from utils import (
    BGR_CHANNEL_COUNT,
    BGRA_CHANNEL_COUNT,
    FROZEN,
    ONE_SECOND,
    ZDCURTAIN_VERSION,
    ImageShape,
    is_valid_image,
    list_processes,
)


class ZDCurtain(QMainWindow, design.Ui_MainWindow):
    # Signals
    after_setting_hotkey_signal = QtCore.Signal()
    # Use this signal when trying to show an error from outside the main thread
    show_error_signal = QtCore.Signal(FunctionType)

    # Timers
    timer_live_image = QtCore.QTimer()
    timer_live_image.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer_frame_analysis = QtCore.QTimer()
    timer_frame_analysis.setTimerType(QtCore.Qt.TimerType.PreciseTimer)

    SettingsWidget: settings.Ui_SettingsWidget | None = None

    def __init__(self):
        super().__init__()

        self.hwnd = 0
        self.last_saved_settings = deepcopy(DEFAULT_PROFILE)
        self.capture_method = CaptureMethodBase(self)
        self.is_running = False
        self.last_frame_time = 1

        # Heuristics
        self.black_level = 1.0
        self.is_frame_black = False
        self.similarity_to_tram = 0.0
        self.similarity_to_tram_max = 0.0
        self.similarity_to_teleportal = 0.0
        self.similarity_to_teleportal_max = 0.0
        self.similarity_to_elevator = 0.0
        self.similarity_to_elevator_max = 0.0
        self.similarity_to_egg = 0.0
        self.similarity_to_egg_max = 0.0
        self.ever_crossed_threshold_tram = False
        self.ever_crossed_threshold_elevator = False
        self.ever_crossed_threshold_teleportal = False
        self.ever_crossed_threshold_egg = False

        # comparison images
        self.comparison_capsule_gravity = None
        self.comparison_capsule_power = None
        self.comparison_capsule_varia = None
        self.comparison_elevator_down_gravity = None
        self.comparison_elevator_down_power = None
        self.comparison_elevator_down_varia = None
        self.comparison_elevator_up_gravity = None
        self.comparison_elevator_up_power = None
        self.comparison_elevator_up_varia = None
        self.comparison_teleport_gravity = None
        self.comparison_teleport_power = None
        self.comparison_teleport_varia = None
        self.comparison_train_left_gravity = None
        self.comparison_train_left_power = None
        self.comparison_train_left_varia = None
        self.comparison_train_right_gravity = None
        self.comparison_train_right_power = None
        self.comparison_train_right_varia = None

        load_comparison_images(self)

        # Setup global error handling
        def _show_error_signal_slot(error_message_box: Callable[..., object]):
            return error_message_box()

        self.show_error_signal.connect(_show_error_signal_slot)
        sys.excepthook = error_messages.make_excepthook(self)

        self.setupUi(self)
        self.setWindowTitle(f"ZDCurtain v.{ZDCURTAIN_VERSION}")

        self.settings_dict = deepcopy(DEFAULT_PROFILE)

        change_capture_method(CaptureMethodEnum.WINDOWS_GRAPHICS_CAPTURE, self)

        # connecting menu actions
        self.action_settings.triggered.connect(lambda: open_settings(self))
        self.action_exit.triggered.connect(lambda: self.closeEvent())  # noqa: PLW0108

        # connecting button clicks to functions
        self.select_window_button.clicked.connect(lambda: select_window(self))
        self.reset_statistics_button.clicked.connect(lambda: reset_statistics(self))

        # live image preview
        self.timer_live_image.timeout.connect(
            lambda: self.__update_live_image_details(None, called_from_timer=True)
        )
        self.timer_live_image.start(int(ONE_SECOND / self.settings_dict["fps_limit"]))

        self.show()

    def __update_live_image_details(
        self,
        capture: MatLike | None,
        *,
        called_from_timer: bool = False,
    ):
        cropped_capture = None

        if called_from_timer:
            if self.is_running:
                return
            capture = self.capture_method.get_frame()

            if not is_valid_image(capture):
                return

            dim = (640, 360)

            resized_capture = cv2.resize(capture, dim)
            cropped_capture = get_top_third_of_capture(resized_capture)

            perform_black_level_analysis(self, cropped_capture)
            perform_similarity_analysis(self, resized_capture)

        # Update title from target window or Capture Device name
        capture_region_window_label = (
            self.settings_dict["capture_device_name"]
            if self.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
            else self.settings_dict["captured_window_title"]
        )
        self.capture_region_window_label.setText(capture_region_window_label)

        self.image_black_label.setText(
            f"Is screen black: {self.is_frame_black},"
            + f"current black level {self.black_level:.4f}%"
        )

        self.similarity_to_elevator_label.setText(
            f"Similarity to elevator loading image: ({self.similarity_to_elevator:.4f}%, max {self.similarity_to_elevator_max:.4f}%)"
        )

        self.similarity_to_tram_label.setText(
            f"Similarity to tram loading image: ({self.similarity_to_tram:.4f}%, max {self.similarity_to_tram_max:.4f}%)"
        )

        self.similarity_to_teleportal_label.setText(
            f"Similarity to teleportal loading image: ({self.similarity_to_teleportal:.4f}%, max {self.similarity_to_teleportal_max:.4f}%)"
        )

        self.similarity_to_egg_label.setText(
            f"Similarity to Itorash elevator image: ({self.similarity_to_egg:.4f}%, max {self.similarity_to_egg_max:.4f}%)"
        )

        if self.similarity_to_elevator > self.settings_dict["similarity_threshold_elevator"]:
            self.ever_crossed_threshold_elevator = True
        if self.similarity_to_tram > self.settings_dict["similarity_threshold_tram"]:
            self.ever_crossed_threshold_tram = True
        if self.similarity_to_teleportal > self.settings_dict["similarity_threshold_teleportal"]:
            self.ever_crossed_threshold_teleportal = True
        if self.similarity_to_egg > self.settings_dict["similarity_threshold_egg"]:
            self.ever_crossed_threshold_egg = True

        update_threshold_labels(self)

        if self.settings_dict["live_capture_region"]:
            set_preview_image(self.live_image, capture)

        current_frame_time = perf_counter_ns()
        fps = round(1000000000 / (current_frame_time - self.last_frame_time), 2)
        self.last_frame_time = current_frame_time

        self.analysis_fps_label.setText(f"Analysis FPS: {fps:.2f}")

    def pause_timer(self):
        # TODO: add what to do when you hit pause hotkey, if this even needs to be done
        pass

    @override
    def closeEvent(self, event: QtGui.QCloseEvent | None = None):
        """Exit safely when closing the window."""

        def exit_program() -> NoReturn:
            self.capture_method.close()
            if event is not None:
                event.accept()
            sys.exit()

        exit_program()

        # Fallthrough case: Prevent program from closing.
        event.ignore()


def perform_black_level_analysis(self, capture: MatLike | None):
    if not is_valid_image(capture):
        return

    self.is_frame_black, self.black_level = is_black(capture)

    self.black_level = self.black_level / 255.0 * 100


def perform_similarity_analysis(self, capture: MatLike | None):
    if not is_valid_image(capture):
        return

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_elevator"]
    )

    self.similarity_to_elevator = (
        max(
            comparison_method_to_use(capture, self.comparison_elevator_up_power),
            comparison_method_to_use(capture, self.comparison_elevator_up_varia),
            comparison_method_to_use(capture, self.comparison_elevator_up_gravity),
            comparison_method_to_use(capture, self.comparison_elevator_down_power),
            comparison_method_to_use(capture, self.comparison_elevator_down_varia),
            comparison_method_to_use(capture, self.comparison_elevator_down_gravity),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_tram"]
    )

    self.similarity_to_tram = (
        max(
            comparison_method_to_use(capture, self.comparison_train_left_power),
            comparison_method_to_use(capture, self.comparison_train_left_varia),
            comparison_method_to_use(capture, self.comparison_train_left_gravity),
            comparison_method_to_use(capture, self.comparison_train_right_power),
            comparison_method_to_use(capture, self.comparison_train_right_varia),
            comparison_method_to_use(capture, self.comparison_train_right_gravity),
        )
        * 100
    )

    self.similarity_to_teleportal = (
        max(
            comparison_method_to_use(capture, self.comparison_teleport_power),
            comparison_method_to_use(capture, self.comparison_teleport_varia),
            comparison_method_to_use(capture, self.comparison_teleport_gravity),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_teleportal"]
    )

    self.similarity_to_egg = (
        max(
            comparison_method_to_use(capture, self.comparison_capsule_power),
            comparison_method_to_use(capture, self.comparison_capsule_varia),
            comparison_method_to_use(capture, self.comparison_capsule_gravity),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_egg"]
    )

    self.similarity_to_elevator_max = max(
        self.similarity_to_elevator_max, self.similarity_to_elevator
    )
    self.similarity_to_tram_max = max(self.similarity_to_tram_max, self.similarity_to_tram)
    self.similarity_to_teleportal_max = max(
        self.similarity_to_teleportal_max, self.similarity_to_teleportal
    )
    self.similarity_to_egg_max = max(self.similarity_to_egg_max, self.similarity_to_egg)


def update_threshold_labels(self):  # noqa: PLR0912
    if self.black_level < self.settings_dict["black_threshold"]:
        self.black_indicator_label.setStyleSheet("background-color: green")
    else:
        self.black_indicator_label.setStyleSheet("background-color: red")

    if self.similarity_to_elevator > self.settings_dict["similarity_threshold_elevator"]:
        self.elevator_indicator_label.setStyleSheet("background-color: green")
    else:
        self.elevator_indicator_label.setStyleSheet("background-color: red")

    if self.similarity_to_tram > self.settings_dict["similarity_threshold_tram"]:
        self.tram_indicator_label.setStyleSheet("background-color: green")
    else:
        self.tram_indicator_label.setStyleSheet("background-color: red")

    if self.similarity_to_teleportal > self.settings_dict["similarity_threshold_teleportal"]:
        self.teleportal_indicator_label.setStyleSheet("background-color: green")
    else:
        self.teleportal_indicator_label.setStyleSheet("background-color: red")

    if self.similarity_to_egg > self.settings_dict["similarity_threshold_egg"]:
        self.egg_indicator_label.setStyleSheet("background-color: green")
    else:
        self.egg_indicator_label.setStyleSheet("background-color: red")

    if self.ever_crossed_threshold_elevator:
        self.elevator_indicator_ever_label.setStyleSheet("background-color: green")
    else:
        self.elevator_indicator_ever_label.setStyleSheet("background-color: red")

    if self.ever_crossed_threshold_tram:
        self.tram_indicator_ever_label.setStyleSheet("background-color: green")
    else:
        self.tram_indicator_ever_label.setStyleSheet("background-color: red")

    if self.ever_crossed_threshold_teleportal:
        self.teleportal_indicator_ever_label.setStyleSheet("background-color: green")
    else:
        self.teleportal_indicator_ever_label.setStyleSheet("background-color: red")

    if self.ever_crossed_threshold_egg:
        self.egg_indicator_ever_label.setStyleSheet("background-color: green")
    else:
        self.egg_indicator_ever_label.setStyleSheet("background-color: red")


def reset_statistics(self):
    self.similarity_to_elevator_max = 0.0
    self.similarity_to_tram_max = 0.0
    self.similarity_to_teleportal_max = 0.0
    self.similarity_to_egg_max = 0.0
    self.ever_crossed_threshold_tram = False
    self.ever_crossed_threshold_elevator = False
    self.ever_crossed_threshold_teleportal = False
    self.ever_crossed_threshold_egg = False


def load_comparison_images(self):
    self.comparison_capsule_gravity = read_and_format_image(
        "res/comparison/capsule_gravity_first.png"
    )
    self.comparison_capsule_power = read_and_format_image("res/comparison/capsule_power_first.png")
    self.comparison_capsule_varia = read_and_format_image("res/comparison/capsule_varia_first.png")
    self.comparison_elevator_down_gravity = read_and_format_image(
        "res/comparison/elevator_down_gravity_first.png"
    )
    self.comparison_elevator_down_power = read_and_format_image(
        "res/comparison/elevator_down_power_first.png"
    )
    self.comparison_elevator_down_varia = read_and_format_image(
        "res/comparison/elevator_down_varia_first.png"
    )
    self.comparison_elevator_up_gravity = read_and_format_image(
        "res/comparison/elevator_up_gravity_first.png"
    )
    self.comparison_elevator_up_power = read_and_format_image(
        "res/comparison/elevator_up_power_first.png"
    )
    self.comparison_elevator_up_varia = read_and_format_image(
        "res/comparison/elevator_up_varia_first.png"
    )
    self.comparison_teleport_gravity = read_and_format_image(
        "res/comparison/teleport_gravity_first.png"
    )
    self.comparison_teleport_power = read_and_format_image(
        "res/comparison/teleport_power_first.png"
    )
    self.comparison_teleport_varia = read_and_format_image(
        "res/comparison/teleport_varia_first.png"
    )
    self.comparison_train_left_gravity = read_and_format_image(
        "res/comparison/train_left_gravity_first.png"
    )
    self.comparison_train_left_power = read_and_format_image(
        "res/comparison/train_left_power_first.png"
    )
    self.comparison_train_left_varia = read_and_format_image(
        "res/comparison/train_left_varia_first.png"
    )
    self.comparison_train_right_gravity = read_and_format_image(
        "res/comparison/train_right_gravity_first.png"
    )
    self.comparison_train_right_power = read_and_format_image(
        "res/comparison/train_right_power_first.png"
    )
    self.comparison_train_right_varia = read_and_format_image(
        "res/comparison/train_right_varia_first.png"
    )


def read_and_format_image(filename):
    image_data = cv2.imread(filename)

    if image_data.shape[ImageShape.Channels] == BGR_CHANNEL_COUNT:
        image_data = cv2.cvtColor(image_data, cv2.COLOR_BGR2BGRA)

    return image_data


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
