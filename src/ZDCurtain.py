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
from gen import about, design, settings
from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

import error_messages
from about import open_about
from capture_method import CaptureMethodBase, CaptureMethodEnum
from frame_analysis import (
    get_comparison_method_by_name,
    get_top_third_of_capture,
    is_black,
    normalize_brightness_histogram,
)
from hotkeys import HOTKEYS, after_setting_hotkey, send_command
from region_selection import select_window
from settings import get_default_settings_from_ui, open_settings
from user_profile import (
    DEFAULT_PROFILE,
    load_settings,
    load_settings_on_open,
    save_settings,
    save_settings_as,
)
from utils import (
    BGRA_CHANNEL_COUNT,
    DREAD_MAX_DELTA_MS,
    FROZEN,
    ONE_SECOND,
    ZDCURTAIN_VERSION,
    is_valid_image,
    list_processes,
    ms_to_msms,
    ms_to_ns,
    ns_to_ms,
    resource_path,
)
from ZDImage import ZDImage, resize_image


class ZDCurtain(QMainWindow, design.Ui_MainWindow):
    # Signals
    pause_signal = QtCore.Signal()
    after_setting_hotkey_signal = QtCore.Signal()
    # Use this signal when trying to show an error from outside the main thread
    show_error_signal = QtCore.Signal(FunctionType)

    # Timers
    timer_load_removal = QtCore.QTimer()
    timer_load_removal.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer_frame_analysis = QtCore.QTimer()
    timer_frame_analysis.setTimerType(QtCore.Qt.TimerType.PreciseTimer)

    SettingsWidget: settings.Ui_SettingsWidget | None = None
    AboutWidget: about.Ui_AboutZDCurtainWidget | None = None

    def __init__(self):  # noqa: PLR0915 constructor
        super().__init__()

        self.hwnd = 0
        self.last_saved_settings = deepcopy(DEFAULT_PROFILE)
        self.capture_method = CaptureMethodBase(self)

        self.last_successfully_loaded_settings_file_path = ""
        """Path of the settings file to default to. `None` until we try to load once."""

        self.is_tracking = False

        # load removal
        self.is_load_being_removed = False
        self.load_time_removed_ms = 0

        # Confidence algorithm
        self.black_screen_detected_at_timestamp = 0
        self.black_screen_over_detected_at_timestamp = 0
        self.potential_load_detected_at_timestamp = 0
        self.confirmed_load_detected_at_timestamp = 0
        self.load_confidence_delta = 0

        self.in_black_screen = False
        self.last_black_screen_time = 0
        self.active_load_type = "none"

        self.load_cooldown_timestamp = 0
        self.load_cooldown_is_active = False
        self.load_cooldown_type = "none"

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
        self.similarity_to_end_screen = 0.0
        self.similarity_to_end_screen_max = 0.0

        # performance
        self.last_frame_time = 1

        # comparison images
        self.comparison_capsule_gravity = None
        self.comparison_capsule_power = None
        self.comparison_capsule_varia = None
        self.comparison_elevator_gravity = None
        self.comparison_elevator_power = None
        self.comparison_elevator_varia = None
        self.comparison_teleport_gravity = None
        self.comparison_teleport_power = None
        self.comparison_teleport_varia = None
        self.comparison_train_left_gravity = None
        self.comparison_train_left_power = None
        self.comparison_train_left_varia = None
        self.comparison_train_right_gravity = None
        self.comparison_train_right_power = None
        self.comparison_train_right_varia = None

        # screenshots
        self.screenshot_timer = 0
        self.screenshot_counter = 1

        load_comparison_images(self)

        # Setup global error handling
        def _show_error_signal_slot(error_message_box: Callable[..., object]):
            return error_message_box()

        self.show_error_signal.connect(_show_error_signal_slot)
        sys.excepthook = error_messages.make_excepthook(self)

        self.setupUi(self)
        self.setWindowTitle(f"ZDCurtain v.{ZDCURTAIN_VERSION}")

        # Hotkeys need to be initialized to be passed as thread arguments in hotkeys.py
        for hotkey in HOTKEYS:
            setattr(self, f"{hotkey}_hotkey", None)

        self.settings_dict = get_default_settings_from_ui(self)

        # connecting menu actions
        self.action_settings.triggered.connect(lambda: open_settings(self))
        self.action_save_settings.triggered.connect(lambda: save_settings(self))
        self.action_save_settings_as.triggered.connect(lambda: save_settings_as(self))
        self.action_load_settings.triggered.connect(lambda: load_settings(self))
        self.action_about.triggered.connect(lambda: open_about(self))
        self.action_exit.triggered.connect(lambda: self.closeEvent())  # noqa: PLW0108

        # connecting button clicks to functions
        self.select_window_button.clicked.connect(lambda: select_window_and_start_tracking(self))
        self.select_device_button.clicked.connect(lambda: open_settings(self))
        self.reset_statistics_button.clicked.connect(lambda: self.reset_statistics)
        self.begin_end_tracking_button.clicked.connect(self.on_tracking_button_press)

        # connect signals to functions
        self.after_setting_hotkey_signal.connect(lambda: after_setting_hotkey(self))

        self.timer_load_removal.timeout.connect(lambda: perform_load_removal_logic(self))
        self.timer_frame_analysis.timeout.connect(
            lambda: self.__update_live_image_details(None, called_from_timer=True)
        )
        self.timer_load_removal.start(int(ONE_SECOND / 60))
        self.timer_frame_analysis.start(int(ONE_SECOND / self.settings_dict["fps_limit"]))

        self.show()

        load_settings_on_open(self)

    def __try_to_recover_capture(self):
        capture = None

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

        return capture

    def __update_live_image_details(
        self,
        capture: MatLike | None,
        *,
        called_from_timer: bool = False,
    ):
        frame_start_time = perf_counter_ns()
        cropped_capture = None

        if called_from_timer:
            capture = self.capture_method.get_frame()

            if is_valid_image(capture):
                dim = (640, 360)
                resized_capture = resize_image(capture, dim, 1, cv2.INTER_NEAREST)

                if self.settings_dict["live_capture_region"]:
                    set_preview_image(self.live_image, resized_capture)

                if self.is_tracking:
                    cropped_capture = get_top_third_of_capture(resized_capture)
                    normalized_capture = normalize_brightness_histogram(resized_capture)

                    perform_black_level_analysis(self, cropped_capture)
                    perform_similarity_analysis(self, resized_capture, normalized_capture)

                    # if self.screenshot_timer >= 12:
                    # imwrite(f"sshot/sshot_{self.screenshot_counter}.png", resized_capture)
                    # self.screenshot_timer = 0
                    # self.screenshot_counter += 1

                    # self.screenshot_timer += 1
            else:
                return  # self.__try_to_recover_capture()

        update_labels(self)

        frame_end_time = perf_counter_ns()

        frame_time = ns_to_ms(frame_end_time - frame_start_time)

        if self.black_screen_detected_at_timestamp <= self.black_screen_over_detected_at_timestamp:
            self.last_black_screen_time = ns_to_ms(
                self.black_screen_over_detected_at_timestamp
                - self.black_screen_detected_at_timestamp
            )

        self.analysis_status_label.setText(
            f"Frame Time: {frame_time:.2f}, "
            + f"Last Black Screen Duration {self.last_black_screen_time}ms, "
            + f"TLTR: {self.load_time_removed_ms:.2f}ms"
        )

        tltr_m, tltr_s, tltr_ms = ms_to_msms(self.load_time_removed_ms)

        self.total_load_time_removed_label.setText(
            f"Total Load Time Removed: {tltr_m:.0f}m {tltr_s:.0f}s {tltr_ms:.0f}ms"
        )

    """         self.analysis_status_label.setText(
            f"pot: {self.potential_load_detected_at_timestamp}; con: "
            + f" {self.confirmed_load_detected_at_timestamp}; lt: {self.active_load_type}"
        ) """

    def on_tracking_button_press(self):
        if self.is_tracking:
            self.end_tracking()
        else:
            self.begin_tracking()

    def pause_timer(self):
        # TODO: add what to do when you hit pause hotkey, if this even needs to be done
        pass

    def reset_all_variables(self):
        self.reset_tracking_variables()
        self.reset_lrt()

    def reset_lrt(self):
        self.load_time_removed_ms = 0

    def reset_tracking_variables(self):
        self.active_load_type = "none"
        self.black_screen_detected_at_timestamp = 0
        self.black_screen_over_detected_at_timestamp = 0
        self.potential_load_detected_at_timestamp = 0
        self.confirmed_load_detected_at_timestamp = 0
        self.is_load_being_removed = False
        self.in_black_screen = False
        self.black_level = 1.0
        self.is_frame_black = False
        self.last_black_screen_time = 0
        self.load_confidence_delta = 0
        self.load_cooldown_timestamp = 0
        self.reset_similarity_variables()

    def reset_similarity_variables(self):
        self.similarity_to_tram = 0.0
        self.similarity_to_tram_max = 0.0
        self.similarity_to_teleportal = 0.0
        self.similarity_to_teleportal_max = 0.0
        self.similarity_to_elevator = 0.0
        self.similarity_to_elevator_max = 0.0
        self.similarity_to_egg = 0.0
        self.similarity_to_egg_max = 0.0
        self.similarity_to_end_screen = 0.0
        self.similarity_to_end_screen_max = 0.0

    def reset_statistics(self):
        self.reset_similarity_variables()

    def begin_tracking(self):
        self.reset_all_variables()
        self.is_tracking = True
        self.begin_end_tracking_button.setText("End Tracking")

    def end_tracking(self):
        self.reset_tracking_variables()
        self.is_tracking = False
        self.begin_end_tracking_button.setText("Begin Tracking")

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


def check_load_confidence(self, similarity, threshold):
    if similarity > threshold and self.active_load_type == "none":
        if self.potential_load_detected_at_timestamp == 0:
            self.potential_load_detected_at_timestamp = perf_counter_ns()

        if perf_counter_ns() - self.potential_load_detected_at_timestamp > ms_to_ns(
            self.settings_dict["load_confidence_threshold_ms"]
        ):
            self.confirmed_load_detected_at_timestamp = perf_counter_ns()

            self.load_confidence_delta = (
                self.confirmed_load_detected_at_timestamp - self.black_screen_detected_at_timestamp
            )

            return True

    return False


def is_end_screen(self, similarity, threshold):
    return similarity > threshold and self.active_load_type == "none"


def check_load_cooldown(self):
    if (
        self.load_cooldown_type != "none"
        and perf_counter_ns()
        > self.load_cooldown_timestamp
        + ms_to_ns(self.settings_dict[f"load_cooldown_{self.load_cooldown_type}_ms"])
    ):
        self.load_cooldown_timestamp = 0
        self.load_cooldown_type = "none"
        self.load_cooldown_is_active = False


def check_if_load_ending(self):
    if (
        self.black_screen_over_detected_at_timestamp > self.confirmed_load_detected_at_timestamp
        and self.is_load_being_removed
    ):
        send_command(self, "pause")

        if self.load_cooldown_type == "none" and self.active_load_type not in {"none", "black"}:
            self.load_cooldown_type = self.active_load_type
            self.load_cooldown_timestamp = perf_counter_ns()
            self.load_cooldown_is_active = True

        if (
            perf_counter_ns() - self.black_screen_over_detected_at_timestamp
            > self.load_confidence_delta
        ):
            self.single_load_time_removed_ms = ns_to_ms(
                self.load_confidence_delta
                + (
                    self.black_screen_over_detected_at_timestamp
                    - self.confirmed_load_detected_at_timestamp
                )
            )

            self.load_time_removed_ms += self.single_load_time_removed_ms

            self.active_load_type = "none"
            self.load_confidence_delta = 0
            self.potential_load_detected_at_timestamp = 0
            self.confirmed_load_detected_at_timestamp = 0

            self.is_load_being_removed = False


def perform_load_removal_logic(self):
    if is_end_screen(self, self.similarity_to_end_screen, 98):
        # stop tracking
        self.end_tracking()

    if not self.is_tracking:
        return

    check_load_cooldown(self)

    if self.black_level < self.settings_dict["black_threshold"] and not self.in_black_screen:
        self.in_black_screen = True
        self.black_screen_detected_at_timestamp = perf_counter_ns()

    if self.black_level >= self.settings_dict["black_threshold"] and self.in_black_screen:
        self.black_screen_over_detected_at_timestamp = perf_counter_ns()
        self.in_black_screen = False

    if (
        self.in_black_screen
        and self.active_load_type == "none"
        and not self.load_cooldown_is_active
        and perf_counter_ns() - self.black_screen_detected_at_timestamp
        > ms_to_ns(DREAD_MAX_DELTA_MS)
    ):
        self.confirmed_load_detected_at_timestamp = perf_counter_ns()
        self.active_load_type = "black"

    if self.active_load_type in {"none", "black"} and not self.load_cooldown_is_active:
        if check_load_confidence(
            self,
            self.similarity_to_elevator,
            self.settings_dict["similarity_threshold_elevator"],
        ):
            self.active_load_type = "elevator"

        if check_load_confidence(
            self, self.similarity_to_tram, self.settings_dict["similarity_threshold_tram"]
        ):
            self.active_load_type = "tram"

        if check_load_confidence(
            self,
            self.similarity_to_teleportal,
            self.settings_dict["similarity_threshold_teleportal"],
        ):
            self.active_load_type = "teleportal"

        if check_load_confidence(
            self,
            self.similarity_to_egg,
            self.settings_dict["similarity_threshold_egg"],
        ):
            self.active_load_type = "capsule"

    if not self.is_load_being_removed and self.active_load_type != "none":
        send_command(self, "pause")
        self.is_load_being_removed = True

    check_if_load_ending(self)


def perform_black_level_analysis(self, capture: MatLike | None):
    if not is_valid_image(capture):
        return

    self.is_frame_black, self.black_level = is_black(capture)

    self.black_level = self.black_level / 255.0 * 100


def perform_similarity_analysis(self, capture: MatLike | None, normalized_capture: MatLike):
    if not is_valid_image(capture):
        return

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_elevator"]
    )

    capture_type_to_use = (
        normalized_capture
        if self.settings_dict["similarity_use_normalized_capture_elevator"]
        else capture
    )

    self.similarity_to_elevator = (
        max(
            comparison_method_to_use(
                capture_type_to_use,
                self.comparison_elevator_power.image_data,
            ),
            comparison_method_to_use(
                capture_type_to_use,
                self.comparison_elevator_varia.image_data,
            ),
            comparison_method_to_use(
                capture_type_to_use,
                self.comparison_elevator_gravity.image_data,
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_tram"]
    )

    capture_type_to_use = (
        normalized_capture
        if self.settings_dict["similarity_use_normalized_capture_tram"]
        else capture
    )

    self.similarity_to_tram = (
        max(
            comparison_method_to_use(
                capture_type_to_use, self.comparison_train_left_power.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_train_left_varia.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_train_left_gravity.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_train_right_power.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_train_right_varia.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_train_right_gravity.image_data
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_teleportal"]
    )

    capture_type_to_use = (
        normalized_capture
        if self.settings_dict["similarity_use_normalized_capture_teleportal"]
        else capture
    )

    self.similarity_to_teleportal = (
        max(
            comparison_method_to_use(
                capture_type_to_use, self.comparison_teleport_power.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_teleport_varia.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_teleport_gravity.image_data
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_egg"]
    )

    capture_type_to_use = (
        normalized_capture
        if self.settings_dict["similarity_use_normalized_capture_egg"]
        else capture
    )

    self.similarity_to_egg = (
        max(
            comparison_method_to_use(capture_type_to_use, self.comparison_capsule_power.image_data),
            comparison_method_to_use(capture_type_to_use, self.comparison_capsule_varia.image_data),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_capsule_gravity.image_data
            ),
        )
        * 100
    )

    self.similarity_to_elevator_max = max(
        self.similarity_to_elevator_max, self.similarity_to_elevator
    )
    self.similarity_to_tram_max = max(self.similarity_to_tram_max, self.similarity_to_tram)
    self.similarity_to_teleportal_max = max(
        self.similarity_to_teleportal_max, self.similarity_to_teleportal
    )
    self.similarity_to_egg_max = max(self.similarity_to_egg_max, self.similarity_to_egg)

    self.similarity_to_egg = (
        max(
            comparison_method_to_use(capture_type_to_use, self.comparison_capsule_power.image_data),
            comparison_method_to_use(capture_type_to_use, self.comparison_capsule_varia.image_data),
            comparison_method_to_use(
                capture_type_to_use, self.comparison_capsule_gravity.image_data
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        self.settings_dict["similarity_algorithm_end_screen"]
    )

    capture_type_to_use = (
        normalized_capture
        if self.settings_dict["similarity_use_normalized_capture_end_screen"]
        else capture
    )

    self.similarity_to_end_screen = (
        comparison_method_to_use(capture_type_to_use, self.comparison_end_screen.image_data) * 100
    )

    self.similarity_to_end_screen_max = max(
        self.similarity_to_end_screen_max, self.similarity_to_end_screen
    )


def update_labels(self):  # noqa: PLR0912, PLR0915
    # Update title from target window or Capture Device name
    capture_region_window_label = (
        self.settings_dict["capture_device_name"]
        if self.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
        else self.settings_dict["captured_window_title"]
    )
    self.capture_region_window_label.setText(capture_region_window_label)

    self.image_black_label.setText(
        f"Current black level {self.black_level:.4f}, "
        + f"threshold {self.settings_dict['black_threshold']}%  "
    )

    self.similarity_to_elevator_label.setText(
        f"Similarity to elevator loading image: ({self.similarity_to_elevator:.4f}%, "
        + f"max {self.similarity_to_elevator_max:.4f}%)"
    )

    self.similarity_to_tram_label.setText(
        f"Similarity to tram loading image: ({self.similarity_to_tram:.4f}%, "
        + f"max {self.similarity_to_tram_max:.4f}%)"
    )

    self.similarity_to_teleportal_label.setText(
        f"Similarity to teleportal loading image: ({self.similarity_to_teleportal:.4f}%, "
        + f"max {self.similarity_to_teleportal_max:.4f}%)"
    )

    self.similarity_to_egg_label.setText(
        f"Similarity to Itorash elevator image: ({self.similarity_to_egg:.4f}%, "
        + f"max {self.similarity_to_egg_max:.4f}%)"
    )

    self.similarity_to_end_screen_label.setText(
        f"Similarity to end screen image: ({self.similarity_to_end_screen:.4f}%, "
        + f"max {self.similarity_to_end_screen_max:.4f}%)"
    )

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

    if self.similarity_to_end_screen > self.settings_dict["similarity_threshold_end_screen"]:
        self.end_indicator_label.setStyleSheet("background-color: green")
    else:
        self.end_indicator_label.setStyleSheet("background-color: red")

    if self.active_load_type == "black":
        self.black_indicator_load_label.setStyleSheet("background-color: green")
    else:
        self.black_indicator_load_label.setStyleSheet("background-color: red")

    if self.active_load_type == "elevator":
        self.elevator_indicator_load_label.setStyleSheet("background-color: green")
    else:
        self.elevator_indicator_load_label.setStyleSheet("background-color: red")

    if self.active_load_type == "tram":
        self.tram_indicator_load_label.setStyleSheet("background-color: green")
    else:
        self.tram_indicator_load_label.setStyleSheet("background-color: red")

    if self.active_load_type == "teleportal":
        self.teleportal_indicator_load_label.setStyleSheet("background-color: green")
    else:
        self.teleportal_indicator_load_label.setStyleSheet("background-color: red")

    if self.active_load_type == "capsule":
        self.egg_indicator_load_label.setStyleSheet("background-color: green")
    else:
        self.egg_indicator_load_label.setStyleSheet("background-color: red")

    if self.similarity_to_end_screen_max > self.settings_dict["similarity_threshold_end_screen"]:
        self.end_indicator_ever_label.setStyleSheet("background-color: green")
    else:
        self.end_indicator_ever_label.setStyleSheet("background-color: red")


def load_comparison_images(self):
    self.comparison_capsule_gravity = read_and_format_image("res/comparison/capsule_gravity.png")
    self.comparison_capsule_power = read_and_format_image("res/comparison/capsule_power.png")
    self.comparison_capsule_varia = read_and_format_image("res/comparison/capsule_varia.png")
    self.comparison_elevator_gravity = read_and_format_image("res/comparison/elevator_gravity.png")
    self.comparison_elevator_power = read_and_format_image("res/comparison/elevator_power.png")
    self.comparison_elevator_varia = read_and_format_image("res/comparison/elevator_varia.png")
    self.comparison_teleport_gravity = read_and_format_image("res/comparison/teleport_gravity.png")
    self.comparison_teleport_power = read_and_format_image("res/comparison/teleport_power.png")
    self.comparison_teleport_varia = read_and_format_image("res/comparison/teleport_varia.png")
    self.comparison_train_left_gravity = read_and_format_image(
        "res/comparison/train_left_gravity.png"
    )
    self.comparison_train_left_power = read_and_format_image("res/comparison/train_left_power.png")
    self.comparison_train_left_varia = read_and_format_image("res/comparison/train_left_varia.png")
    self.comparison_train_right_gravity = read_and_format_image(
        "res/comparison/train_right_gravity.png"
    )
    self.comparison_train_right_power = read_and_format_image(
        "res/comparison/train_right_power.png"
    )
    self.comparison_train_right_varia = read_and_format_image(
        "res/comparison/train_right_varia.png"
    )
    self.comparison_end_screen = read_and_format_image("res/comparison/end_screen.png")


def read_and_format_image(filename):
    return ZDImage(resource_path(filename))


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


def select_window_and_start_tracking(self):
    if self.settings_dict["start_tracking_automatically"] and not self.is_tracking:
        self.begin_tracking()

    select_window(self)


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
        app.setWindowIcon(QtGui.QIcon(":/resources/icon.ico"))

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
