#!/usr/bin/python3
from __future__ import annotations

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


from collections.abc import Callable
from copy import deepcopy
from math import floor
from types import FunctionType
from typing import NoReturn, override

import cv2
from cv2.typing import MatLike
from gen import about as about_ui, overlay as overlay_ui, settings as settings_ui, zdcurtain as zdcurtain_ui
from PySide6 import QtCore, QtGui
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication, QMainWindow

import error_messages
from capture_method import CaptureMethodBase, CaptureMethodEnum
from frame_analysis import crop_image, normalize_brightness_histogram
from hotkeys import HOTKEYS, after_setting_hotkey
from image_utilities import load_comparison_images, load_images, set_preview_image, take_screenshot
from load_removal import (
    mark_load_as_lost,
    perform_black_level_analysis,
    perform_load_removal_logic,
    perform_similarity_analysis,
)
from load_tracking import LoadRemovalSession, export_tracked_loads
from region_selection import select_window
from stylesheets import (
    style_progress_bar_fail,
    style_progress_bar_pass,
    style_threshold_line_fail,
    style_threshold_line_pass,
)
from ui.about_ui import open_about
from ui.overlay_ui import open_overlay
from ui.settings_ui import get_default_settings_from_ui, open_settings, set_screenshot_location
from user_profile import (
    DEFAULT_PROFILE,
    load_settings,
    load_settings_on_open,
    save_settings,
    save_settings_as,
)
from utils import (
    BLACKOUT_SIDE_LENGTH,
    ONE_SECOND,
    ZDCURTAIN_VERSION,
    LocalTime,
    create_icon,
    create_yes_no_dialog,
    debug_log,
    get_sanitized_filename,
    get_widget_position,
    is_valid_image,
    move_widget,
    ms_to_msms,
    ns_to_ms,
    rgba_to_bgra,
)
from ZDImage import ZDImage, resize_image


class ZDCurtain(QMainWindow, zdcurtain_ui.Ui_ZDCurtain):
    # Signals
    capture_state_changed_signal = QtCore.Signal()
    after_setting_hotkey_signal = QtCore.Signal()
    after_changing_icon_signal = QtCore.Signal()
    after_load_list_changed_signal = QtCore.Signal()
    after_load_time_removed_changed_signal = QtCore.Signal()
    after_changing_tracking_status = QtCore.Signal()
    # hotkey signals
    take_screenshot_signal = QtCore.Signal()
    # Use this signal when trying to show an error from outside the main thread
    show_error_signal = QtCore.Signal(FunctionType)

    # Timers
    timer_main = QtCore.QTimer()
    timer_main.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer_frame_analysis = QtCore.QTimer()
    timer_frame_analysis.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer_capture_stream_timed_out = QtCore.QTimer()
    timer_capture_stream_timed_out.setTimerType(QtCore.Qt.TimerType.PreciseTimer)

    SettingsWidget: settings_ui.Ui_SettingsWidget | None = None
    AboutWidget: about_ui.Ui_AboutZDCurtainWidget | None = None
    OverlayWidget: overlay_ui.Ui_OverlayWidget | None = None

    def __init__(self):
        super().__init__()

        debug_log(f"ZDCurtain v.{ZDCURTAIN_VERSION}")

        self.__init_variables()
        self.__init_measurement_variables()

        load_images(self)
        load_comparison_images(self)

        # Setup global error handling
        def _show_error_signal_slot(error_message_box: Callable[..., object]):
            return error_message_box()

        self.show_error_signal.connect(_show_error_signal_slot)

        self.setupUi(self)
        self.setWindowTitle(f"ZDCurtain v.{ZDCURTAIN_VERSION}")

        sys.excepthook = error_messages.make_excepthook(self)

        # Hotkeys need to be initialized to be passed as thread arguments in hotkeys.py
        for hotkey in HOTKEYS:
            setattr(self, f"{hotkey}_hotkey", None)

        self.settings_dict = get_default_settings_from_ui()

        # Menu

        self.action_hide_analysis_elements.setChecked(self.settings_dict["hide_analysis_elements"])
        self.action_show_frame_info.setChecked(not self.settings_dict["hide_frame_info"])

        self.end_screen_tracking_bar.setHidden(True)
        self.end_screen_tracking_max_label.setHidden(True)
        self.end_screen_tracking_max_line.setHidden(True)
        self.end_screen_tracking_value_label.setHidden(True)
        self.end_screen_tracking_value_line.setHidden(True)
        self.end_screen_tracking_icon.setHidden(True)
        self.end_screen_threshold_value_line.setHidden(True)

        if self.settings_dict["start_tracking_automatically"]:
            self.begin_tracking()
        else:
            self.end_tracking()

        self.__setup_bindings()

        self.timer_main.start(int(ONE_SECOND / 60))
        self.timer_frame_analysis.start(int(ONE_SECOND / self.settings_dict["fps_limit"]))

        self.black_screen_detection_area_label.setGeometry(
            10 + int(self.settings_dict["black_screen_detection_region"]["x"]),
            10 + int(self.settings_dict["black_screen_detection_region"]["y"]),
            int(self.settings_dict["black_screen_detection_region"]["width"]),
            int(self.settings_dict["black_screen_detection_region"]["height"]),
        )

        self.show()

        load_settings_on_open(self)

    def __init_measurement_variables(self):
        self.load_removal_session = None
        self.is_tracking = False

        # load classification and measurement
        self.active_load_type = "none"
        self.potential_load_type = "none"
        self.load_cooldown_type = "none"
        self.single_load_time_removed_ms = 0.0
        self.load_time_removed_ms = 0.0
        self.load_cooldown_timestamp = 0

        # frame classification
        self.average_luminance = 0.0
        self.full_black_level = 1.0
        self.full_shannon_entropy = 100.0
        self.slice_black_level = 1.0
        self.slice_shannon_entropy = 100.0
        self.similarity_to_egg = 0.0
        self.similarity_to_elevator = 0.0
        self.similarity_to_end_screen = 0.0
        self.similarity_to_game_over_screen: int = 0
        self.similarity_to_loading_widget: int = 0
        self.similarity_to_teleportal = 0.0
        self.similarity_to_tram = 0.0

        # intra-load timestamping and measurement
        self.last_black_screen_time = 0
        self.full_black_detected_at_timestamp = 0
        self.full_black_over_detected_at_timestamp = 0
        self.slice_black_detected_at_timestamp = 0
        self.slice_black_over_detected_at_timestamp = 0
        self.confirmed_load_detected_at_timestamp = 0
        self.potential_load_detected_at_timestamp = 0
        self.load_confidence_delta = 0
        self.captured_window_title_before_load = ""

        # frame status
        self.in_black_screen = False
        self.in_black_slice = False
        self.in_game_over_screen = False
        self.is_frame_black = False
        self.is_load_being_removed = False
        self.should_block_load_detection = False
        self.load_cooldown_is_active = False

        # load classification extreme values
        self.full_shannon_entropy_min = 100.0
        self.slice_shannon_entropy_min = 100.0
        self.similarity_to_egg_max = 0.0
        self.similarity_to_elevator_max = 0.0
        self.similarity_to_end_screen_max = 0.0
        self.similarity_to_game_over_screen_max: int = 0
        self.similarity_to_loading_widget_max: int = 0
        self.similarity_to_teleportal_max = 0.0
        self.similarity_to_tram_max = 0.0

        # performance
        self.last_frame_time = 1

    def __init_variables(self):
        self.last_saved_settings = deepcopy(DEFAULT_PROFILE)
        self.last_successfully_loaded_settings_file_path = ""
        """Path of the settings file to default to. `None` until we try to load once."""

        # Capture
        self.hwnd = 0
        self.capture_method = CaptureMethodBase(self)
        self.capture_view_raw = None
        self.capture_view_resized = None
        self.capture_view_resized_normalized = None
        self.capture_view_resized_cropped = None
        self.ever_had_capture = False
        self.attempt_to_recover_capture_if_lost = False

        # icons
        self.elevator_icon = None
        self.tram_icon = None
        self.teleportal_icon = None
        self.capsule_icon = None
        self.elevator_icon_tentative = None
        self.tram_icon_tentative = None
        self.teleportal_icon_tentative = None
        self.capsule_icon_tentative = None
        self.gunship_icon = None
        self.loading_icon = None
        self.loading_icon_grayed = None

        # comparison images
        self.comparison_capsule_gravity: ZDImage
        self.comparison_capsule_power: ZDImage
        self.comparison_capsule_varia: ZDImage
        self.comparison_elevator_gravity: ZDImage
        self.comparison_elevator_power: ZDImage
        self.comparison_elevator_varia: ZDImage
        self.comparison_teleport_gravity: ZDImage
        self.comparison_teleport_power: ZDImage
        self.comparison_teleport_varia: ZDImage
        self.comparison_train_left_gravity: ZDImage
        self.comparison_train_left_power: ZDImage
        self.comparison_train_left_varia: ZDImage
        self.comparison_train_right_gravity: ZDImage
        self.comparison_train_right_power: ZDImage
        self.comparison_train_right_varia: ZDImage
        self.comparison_end_screen: ZDImage
        self.comparison_game_over_screen: ZDImage
        self.comparison_loading_widget: ZDImage

    def __bind_icons(self):
        create_icon(self.elevator_tracking_icon, self.elevator_icon)
        create_icon(self.tram_tracking_icon, self.tram_icon)
        create_icon(self.teleportal_tracking_icon, self.teleportal_icon)
        create_icon(self.egg_tracking_icon, self.capsule_icon)
        create_icon(self.end_screen_tracking_icon, self.gunship_icon)
        create_icon(self.black_screen_load_icon, self.loading_icon_grayed)

    def __setup_bindings(self):
        # connecting menu actions
        # file

        self.action_save_settings.triggered.connect(lambda: save_settings(self))
        self.action_save_settings_as.triggered.connect(lambda: save_settings_as(self))
        self.action_load_settings.triggered.connect(lambda: load_settings(self))
        self.action_export_tracked_loads.triggered.connect(
            lambda: export_tracked_loads(self.load_removal_session)
        )
        self.action_exit.triggered.connect(self.closeEvent)

        # Tracking
        self.action_reset_statistics.triggered.connect(self.on_reset_statistics_button_press)
        self.action_clear_load_removal_session.triggered.connect(
            self.on_clear_load_removal_session_button_press
        )
        self.action_settings.triggered.connect(lambda: open_settings(self))
        # View
        self.action_hide_analysis_elements.changed.connect(
            lambda: self.set_analysis_elements_hidden(self.action_hide_analysis_elements.isChecked())
        )
        self.action_capture_standard.triggered.connect(
            lambda: self.set_capture_type_for_screenshots("standard_resized")
        )
        self.action_capture_normalized.triggered.connect(
            lambda: self.set_capture_type_for_screenshots("normalized_resized")
        )
        self.action_show_frame_info.changed.connect(
            lambda: self.set_frame_info_hidden(not self.action_show_frame_info.isChecked())
        )
        # Window
        self.action_show_stream_overlay.triggered.connect(lambda: open_overlay(self))
        # Help
        self.action_about.triggered.connect(lambda: open_about(self))

        # connecting button clicks to functions
        self.select_window_button.clicked.connect(self.__select_window_and_start_tracking)
        self.select_device_button.clicked.connect(lambda: open_settings(self))
        self.reset_statistics_button.clicked.connect(self.on_reset_statistics_button_press)
        self.clear_load_removal_session_button.clicked.connect(
            self.on_clear_load_removal_session_button_press
        )
        self.begin_end_tracking_button.clicked.connect(self.on_tracking_button_press)
        self.take_screenshot_button.clicked.connect(self.__on_take_screenshot_button_pressed)

        # connect signals to functions
        self.after_setting_hotkey_signal.connect(lambda: after_setting_hotkey(self))
        self.capture_state_changed_signal.connect(self.on_capture_state_changed)
        self.after_load_list_changed_signal.connect(self.refresh_previous_loads_list)
        self.after_load_time_removed_changed_signal.connect(
            lambda: self.update_load_time_removed(self.total_load_time_removed_label)
        )

        self.timer_main.timeout.connect(self.__run_app_logic)
        self.timer_frame_analysis.timeout.connect(
            lambda: self.__update_live_image_details(None, called_from_timer=True)
        )
        self.timer_capture_stream_timed_out.timeout.connect(self.__give_up_capture_recovery)

        # image bindings
        self.__bind_icons()

        # function bindings
        self.set_analysis_elements_hidden(self.settings_dict["hide_analysis_elements"])
        self.set_frame_info_hidden(self.settings_dict["hide_frame_info"])
        self.set_capture_type_for_screenshots(self.settings_dict["capture_view_preview"])

        # Set up capture view select
        action_group = QtGui.QActionGroup(self, exclusionPolicy=QActionGroup.ExclusionPolicy.Exclusive)
        a = action_group.addAction(self.action_capture_standard)
        b = action_group.addAction(self.action_capture_normalized)
        self.menuCapture.addActions([a, b])

    def __select_window_and_start_tracking(self):
        select_window(self)

        if is_valid_image(self.capture_view_raw):
            self.setWindowTitle(f"ZDCurtain v.{ZDCURTAIN_VERSION}")

            if self.settings_dict["start_tracking_automatically"] and not self.is_tracking:
                self.begin_tracking()

    def __try_to_recover_capture(self):
        self.capture_view_raw = None

        # Try to recover by using the window name
        if self.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE:
            self.live_image.setText("Waiting for capture device...")
        else:
            message = "Trying to recover window..."
            if self.settings_dict["capture_method"] == CaptureMethodEnum.BITBLT:
                message += "\n(captured window may be incompatible with BitBlt)"
            self.live_image.setText(message)
            recovered = self.capture_method.recover_window(self.settings_dict["captured_window_title"])
            if recovered:
                self.capture_view_raw = self.capture_method.get_frame()
                self.timer_capture_stream_timed_out.stop()
                self.capture_state_changed_signal.emit()

        return self.capture_view_raw

    def __give_up_capture_recovery(self):
        self.setWindowTitle(f"**LOST CAPTURE** ZDCurtain v.{ZDCURTAIN_VERSION}")
        QApplication.alert(self, 0)
        self.attempt_to_recover_capture_if_lost = False
        self.ever_had_capture = False
        self.timer_capture_stream_timed_out.stop()
        self.live_image.setText("Couldn't find capture stream to recover!")
        self.settings_dict["captured_window_title"] = ""
        self.show_error_signal.emit(error_messages.couldnt_find_capture_to_recover)

    def __run_app_logic(self):
        self.__update_ui()

    def __update_live_image_details(
        self,
        capture: MatLike | None,
        *,
        called_from_timer: bool = False,
    ):
        frame_start_time = perf_counter_ns()
        self.capture_view_resized_cropped = None

        if called_from_timer:
            self.capture_view_raw = self.capture_method.get_frame()

            if is_valid_image(self.capture_view_raw):
                if not self.ever_had_capture:
                    self.ever_had_capture = True

                dim = (640, 360)
                self.capture_view_resized = resize_image(self.capture_view_raw.copy(), dim, 1, cv2.INTER_AREA)
                # black out rounded corners
                black = rgba_to_bgra((0, 0, 0, 255))

                cv2.rectangle(
                    self.capture_view_resized,
                    (0, dim[1] - BLACKOUT_SIDE_LENGTH),
                    (BLACKOUT_SIDE_LENGTH, dim[1]),
                    black,
                    -1,
                )
                cv2.rectangle(
                    self.capture_view_resized,
                    (dim[0] - BLACKOUT_SIDE_LENGTH, dim[1] - BLACKOUT_SIDE_LENGTH),
                    (dim[0], dim[1]),
                    black,
                    -1,
                )

                self.capture_view_resized_normalized = normalize_brightness_histogram(
                    self.capture_view_resized.copy()
                )

                capture_view_to_use = self.get_capture_view_by_name(
                    self.settings_dict["capture_view_preview"]
                )

                if self.settings_dict["live_capture_region"]:
                    set_preview_image(self.live_image, capture_view_to_use)

                if self.is_tracking:
                    bsd_area = self.settings_dict["black_screen_detection_region"]

                    self.capture_view_resized_cropped = crop_image(
                        self.capture_view_resized.copy(),
                        bsd_area["x"],
                        bsd_area["y"],
                        bsd_area["x"] + bsd_area["width"],
                        bsd_area["y"] + bsd_area["height"],
                    )

                    perform_black_level_analysis(self)
                    perform_similarity_analysis(self)
                    perform_load_removal_logic(self)
            elif (
                self.settings_dict["captured_window_title"]
                and self.ever_had_capture
                and self.attempt_to_recover_capture_if_lost
            ):
                if not self.timer_capture_stream_timed_out.isActive():
                    self.timer_capture_stream_timed_out.start(self.settings_dict["capture_stream_timeout_ms"])
                    # if it happens during a currently tracked load, stop tracking the load IMMEDIATELY
                    mark_load_as_lost(self)

                self.__try_to_recover_capture()

        frame_end_time = perf_counter_ns()

        frame_time = ns_to_ms(frame_end_time - frame_start_time)

        if self.full_black_detected_at_timestamp <= self.full_black_over_detected_at_timestamp:
            self.last_black_screen_time = ns_to_ms(
                self.full_black_over_detected_at_timestamp - self.full_black_detected_at_timestamp
            )

        self.frame_info_label.setText(
            "Frame Info\n"
            + f"Load Cooldown Active: {self.load_cooldown_is_active}\n"
            + f"Frame Time: {frame_time:.2f}\n"
            + f"Game Over Descriptors Found (current, max): {self.similarity_to_game_over_screen:.0f}, "
            + f"{self.similarity_to_game_over_screen_max:.0f}\n"
            + "Loading Widget Descriptors Found (current, max): "
            + f"{self.similarity_to_loading_widget:.0f}, "
            + f"{self.similarity_to_loading_widget_max:.0f}\n"
            + f"In Game Over?: {self.in_game_over_screen}\n"
            + f"Load Detection Blocked?: {self.should_block_load_detection}\n"
            + f"Last Black Screen Duration {self.last_black_screen_time}ms\n"
            + f"Minimum Entropy (full, slice) {self.full_shannon_entropy_min:.2f}, "
            + f"{self.slice_shannon_entropy_min:.2f}"
        )

    def on_tracking_button_press(self):
        if self.is_tracking:
            self.end_tracking()
        else:
            self.begin_tracking()

    def on_clear_load_removal_session_button_press(self):
        create_yes_no_dialog(
            "Reset Load Data",
            "This will clear all load removal data for this tracking session, "
            + "including the total load time removed. Are you sure you want to do this?",
            self.reset_all_variables,
            None,
        )

    def reset_icons(self):
        self.__bind_icons()

    def reset_all_variables(self):
        self.__reset_tracking_variables()
        self.__reset_load_data()
        self.__bind_icons()

    def __reset_tracking_variables(self):
        # load classification and measurement
        self.active_load_type = "none"
        self.potential_load_type = "none"
        self.load_cooldown_type = "none"
        self.single_load_time_removed_ms = 0.0
        self.load_time_removed_ms = 0.0
        self.load_cooldown_timestamp = 0

        # frame classification
        self.average_luminance = 0.0
        self.full_black_level = 1.0
        self.full_shannon_entropy = 100.0
        self.slice_black_level = 1.0
        self.slice_shannon_entropy = 100.0
        self.similarity_to_egg = 0.0
        self.similarity_to_elevator = 0.0
        self.similarity_to_end_screen = 0.0
        self.similarity_to_game_over_screen: int = 0
        self.similarity_to_loading_widget: int = 0
        self.similarity_to_teleportal = 0.0
        self.similarity_to_tram = 0.0

        # intra-load timestamping and measurement
        self.last_black_screen_time = 0
        self.full_black_detected_at_timestamp = 0
        self.full_black_over_detected_at_timestamp = 0
        self.slice_black_detected_at_timestamp = 0
        self.slice_black_over_detected_at_timestamp = 0
        self.confirmed_load_detected_at_timestamp = 0
        self.potential_load_detected_at_timestamp = 0
        self.load_confidence_delta = 0
        self.captured_window_title_before_load = ""

        # frame status
        self.in_black_screen = False
        self.in_black_slice = False
        self.in_game_over_screen = False
        self.is_frame_black = False
        self.is_load_being_removed = False
        self.should_block_load_detection = False
        self.load_cooldown_is_active = False

        self.__reset_similarity_variables()

    def __reset_similarity_variables(self):
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
        self.similarity_to_game_over_screen: int = 0
        self.similarity_to_game_over_screen_max: int = 0
        self.similarity_to_loading_widget: int = 0
        self.similarity_to_loading_widget_max: int = 0
        self.full_shannon_entropy = 100.0
        self.full_shannon_entropy_min = 100.0
        self.slice_shannon_entropy = 100.0
        self.slice_shannon_entropy_min = 100.0

    def on_reset_statistics_button_press(self):
        self.__reset_similarity_variables()

    def begin_tracking(self):
        if self.is_tracking:  # we're already tracking, no need to run this
            return

        if (
            self.settings_dict["clear_previous_session_on_begin_tracking"]
            and self.load_removal_session is not None
            and self.load_removal_session.get_load_count() > 0
        ):
            create_yes_no_dialog(
                "Reset Load Data",
                "Starting a new tracking session will remove all load removal data for the "
                + "current session, including the total load time removed. "
                + "Are you sure you want to do this? (You can change this behavior in the "
                + "settings.)",
                self.__reset_load_data_and_begin_tracking,
                None,
            )
        elif (
            not self.settings_dict["clear_previous_session_on_begin_tracking"]
            and self.load_removal_session is not None
            and self.load_removal_session.get_load_count() > 0
        ):
            self.__begin_tracking()
        elif self.load_removal_session is None:
            self.load_removal_session = LoadRemovalSession()
        else:
            self.__begin_tracking()

    def __reset_load_data(self):
        self.load_removal_session = LoadRemovalSession()
        self.single_load_time_removed_ms = 0
        self.load_time_removed_ms = 0
        self.screenshot_counter = 0
        self.previous_loads_list.clear()
        self.after_load_time_removed_changed_signal.emit()

    def __reset_load_data_and_begin_tracking(self):
        self.__reset_load_data()
        self.__begin_tracking()

    def __begin_tracking(self):
        self.is_tracking = True
        self.begin_end_tracking_button.setText("End Tracking")
        self.after_changing_tracking_status.emit()

    def end_tracking(self, *, ending_due_to_error=False):
        if not self.is_tracking:  # we're not tracking, no need to run this
            return

        if (
            self.load_removal_session is not None
            and self.load_removal_session.get_load_count() > 0
            and not ending_due_to_error
        ):
            if self.is_load_being_removed:
                create_yes_no_dialog(
                    "Warning",
                    "Ending tracking during a load can have adverse effects. "
                    + "Are you sure you want to do this?",
                    self.__end_tracking(),
                    None,
                )
            else:
                self.__end_tracking()

            if not self.is_tracking:
                create_yes_no_dialog(
                    "Export Load Removal Session",
                    "Would you like to export the results of your load removal session to a file?",
                    lambda: export_tracked_loads(self.load_removal_session),
                    None,
                )
        else:
            self.__end_tracking()

    def __end_tracking(self):
        self.__reset_tracking_variables()
        self.is_tracking = False
        self.begin_end_tracking_button.setText("Begin Tracking")
        self.__bind_icons()

        if self.is_load_being_removed:
            mark_load_as_lost(self)

        self.after_changing_tracking_status.emit()

    def __update_ui(self):
        self.__update_capture_region_label()
        self.__update_buttons()
        self.__update_statistics_values()
        self.__update_statistics_display_colors()
        self.__update_statistics_widget_locations()

    def set_analysis_elements_hidden(self, should_hide):
        self.settings_dict["hide_analysis_elements"] = not should_hide
        self.black_screen_detection_area_label.setHidden(should_hide)

    def set_frame_info_hidden(self, should_hide):
        self.settings_dict["hide_frame_info"] = not should_hide
        self.frame_info_label.setHidden(should_hide)

    def set_capture_type_for_screenshots(self, capture_type):
        self.settings_dict["capture_view_preview"] = capture_type
        match capture_type:
            case "standard_resized":
                self.action_capture_standard.setChecked(True)
                self.screenshot_capture_view_label.setText("Standard View")
            case "normalized_resized":
                self.action_capture_normalized.setChecked(True)
                self.screenshot_capture_view_label.setText("Normalized View")
            case _:
                raise KeyError(f"{capture_type!r} is not a valid capture type for screenshots")

    def get_capture_type_for_screenshots(self, capture_type):
        match capture_type:
            case "standard_resized":
                return self.capture_view_resized
            case "normalized_resized":
                return self.capture_view_resized_normalized
            case _:
                raise KeyError(f"{capture_type!r} is not a valid capture type for screenshots")

    def get_capture_view_by_name(self, capture_view_name: str) -> MatLike:
        capture_view_to_use = None
        match capture_view_name:
            case "standard_resized":
                capture_view_to_use = self.capture_view_resized
            case "normalized_resized":
                capture_view_to_use = self.capture_view_resized_normalized
            case "cropped_resized":
                capture_view_to_use = self.capture_view_resized_cropped
            case "raw":
                capture_view_to_use = self.capture_view_raw
            case _:
                raise KeyError(f"{capture_view_name!r} is not a valid capture view")

        if not is_valid_image(capture_view_to_use):
            raise ValueError(f'Unable to obtain capture type "{capture_view_name}"')

        return capture_view_to_use

    def set_middle_of_load_dependencies_enabled(self, *, should_be_enabled: bool):
        self.clear_load_removal_session_button.setEnabled(should_be_enabled)
        self.action_clear_load_removal_session.setEnabled(should_be_enabled)
        self.action_export_tracked_loads.setEnabled(should_be_enabled)

    def set_active_capture_dependencies_enabled(self, *, should_be_enabled: bool):
        self.reset_statistics_button.setEnabled(should_be_enabled)
        self.action_clear_load_removal_session.setEnabled(should_be_enabled)
        self.clear_load_removal_session_button.setEnabled(should_be_enabled)

    def on_capture_state_changed(self):
        if (
            self.settings_dict["captured_window_title"] != self.captured_window_title_before_load
            and self.is_load_being_removed
        ):
            # it looks like the capture state changed in the middle of a load, we should give a warning
            mark_load_as_lost(self)

        self.timer_capture_stream_timed_out.stop()

        self.attempt_to_recover_capture_if_lost = True
        self.set_active_capture_dependencies_enabled(should_be_enabled=True)

    def update_load_time_removed(self, label):
        tltr_m, tltr_s, tltr_ms = ms_to_msms(self.load_time_removed_ms)

        if tltr_m > 0 or tltr_s > 0 or tltr_ms > 0:
            label.setText(f"{tltr_m:.0f}m {tltr_s:.0f}s {tltr_ms:.0f}ms")
        else:
            label.setText("--m --s ---ms")

    def refresh_previous_loads_list(self):
        if self.load_removal_session is not None:
            loads = self.load_removal_session.get_loads()

            if loads is not None:
                reversed_loads = list(reversed(loads))
                self.previous_loads_list.clear()

                self.previous_loads_list.addItems([load.to_string() for load in reversed_loads])

    def __update_buttons(self):
        if is_valid_image(self.capture_view_raw) and not self.reset_statistics_button.isEnabled():
            self.set_active_capture_dependencies_enabled(should_be_enabled=True)

        if not is_valid_image(self.capture_view_raw) and self.reset_statistics_button.isEnabled():
            self.set_active_capture_dependencies_enabled(should_be_enabled=False)

    def __update_capture_region_label(self):
        # Update title from target window or Capture Device name
        capture_region_window_label = (
            self.settings_dict["capture_device_name"]
            if self.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
            else self.settings_dict["captured_window_title"]
        )

        self.capture_region_window_label.setText(capture_region_window_label)

    def __update_statistics_values(self):
        black_level_text = f"{self.full_black_level:.0f}" if self.is_tracking else "--"

        # labels
        self.black_level_numerical_label.setText(f"{black_level_text}")
        # max
        self.elevator_tracking_max_label.setText(f"{self.similarity_to_elevator_max:.0f}%")
        self.tram_tracking_max_label.setText(f"{self.similarity_to_tram_max:.0f}%")
        self.teleportal_tracking_max_label.setText(f"{self.similarity_to_teleportal_max:.0f}%")
        self.egg_tracking_max_label.setText(f"{self.similarity_to_egg_max:.0f}%")
        self.end_screen_tracking_max_label.setText(f"{self.similarity_to_end_screen_max:.0f}%")
        # values
        self.elevator_tracking_value_label.setText(f"{self.similarity_to_elevator:.0f}%")
        self.tram_tracking_value_label.setText(f"{self.similarity_to_tram:.0f}%")
        self.teleportal_tracking_value_label.setText(f"{self.similarity_to_teleportal:.0f}%")
        self.egg_tracking_value_label.setText(f"{self.similarity_to_egg:.0f}%")
        self.end_screen_tracking_value_label.setText(f"{self.similarity_to_end_screen:.0f}%")
        # threshold

        # progress bars
        self.entropy_bar.setValue(int(self.full_shannon_entropy))
        self.entropy_bar_slice.setValue(int(self.slice_shannon_entropy))
        self.elevator_tracking_bar.setValue(int(self.similarity_to_elevator))
        self.tram_tracking_bar.setValue(int(self.similarity_to_tram))
        self.teleportal_tracking_bar.setValue(int(self.similarity_to_teleportal))
        self.egg_tracking_bar.setValue(int(self.similarity_to_egg))
        self.end_screen_tracking_bar.setValue(int(self.similarity_to_end_screen))

    def __update_statistics_display_colors(self):
        # dynamic colors
        self.average_luminance_display.setStyleSheet(
            f"background-color: hsl(0%,0%,{floor(self.average_luminance / 255 * 100)}%)"
        )

        if self.similarity_to_elevator > self.settings_dict["similarity_threshold_elevator"]:
            self.elevator_tracking_bar.setStyleSheet(style_progress_bar_pass)
            self.elevator_threshold_value_line.setStyleSheet(style_threshold_line_pass)
        else:
            self.elevator_tracking_bar.setStyleSheet(style_progress_bar_fail)
            self.elevator_threshold_value_line.setStyleSheet(style_threshold_line_fail)

        if self.similarity_to_tram > self.settings_dict["similarity_threshold_tram"]:
            self.tram_tracking_bar.setStyleSheet(style_progress_bar_pass)
            self.tram_threshold_value_line.setStyleSheet(style_threshold_line_pass)
        else:
            self.tram_tracking_bar.setStyleSheet(style_progress_bar_fail)
            self.tram_threshold_value_line.setStyleSheet(style_threshold_line_fail)

        if self.similarity_to_teleportal > self.settings_dict["similarity_threshold_teleportal"]:
            self.teleportal_tracking_bar.setStyleSheet(style_progress_bar_pass)
            self.teleportal_threshold_value_line.setStyleSheet(style_threshold_line_pass)
        else:
            self.teleportal_tracking_bar.setStyleSheet(style_progress_bar_fail)
            self.teleportal_threshold_value_line.setStyleSheet(style_threshold_line_fail)

        if self.similarity_to_egg > self.settings_dict["similarity_threshold_egg"]:
            self.egg_tracking_bar.setStyleSheet(style_progress_bar_pass)
            self.egg_threshold_value_line.setStyleSheet(style_threshold_line_pass)
        else:
            self.egg_tracking_bar.setStyleSheet(style_progress_bar_fail)
            self.egg_threshold_value_line.setStyleSheet(style_threshold_line_fail)

        if self.similarity_to_end_screen > self.settings_dict["similarity_threshold_end_screen"]:
            self.end_screen_tracking_bar.setStyleSheet(style_progress_bar_pass)
            self.end_screen_threshold_value_line.setStyleSheet(style_threshold_line_pass)
        else:
            self.end_screen_tracking_bar.setStyleSheet(style_progress_bar_fail)
            self.end_screen_threshold_value_line.setStyleSheet(style_threshold_line_fail)

    def __update_statistics_widget_locations(self):
        # dynamic label positioning
        progress_bar_max_y = 120

        # values
        x, _ = get_widget_position(self.elevator_tracking_value_widget)
        move_widget(
            self.elevator_tracking_value_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_elevator),
        )
        x, _ = get_widget_position(self.tram_tracking_value_widget)
        move_widget(
            self.tram_tracking_value_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_tram),
        )
        x, _ = get_widget_position(self.teleportal_tracking_value_widget)
        move_widget(
            self.teleportal_tracking_value_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_teleportal),
        )
        x, _ = get_widget_position(self.egg_tracking_value_widget)
        move_widget(
            self.egg_tracking_value_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_egg),
        )
        x, _ = get_widget_position(self.end_screen_tracking_value_widget)
        move_widget(
            self.end_screen_tracking_value_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_end_screen),
        )

        # max
        x, _ = get_widget_position(self.elevator_tracking_max_widget)
        move_widget(
            self.elevator_tracking_max_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_elevator_max),
        )
        x, _ = get_widget_position(self.tram_tracking_max_widget)
        move_widget(
            self.tram_tracking_max_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_tram_max),
        )
        x, _ = get_widget_position(self.teleportal_tracking_max_widget)
        move_widget(
            self.teleportal_tracking_max_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_teleportal_max),
        )
        x, _ = get_widget_position(self.egg_tracking_max_widget)
        move_widget(
            self.egg_tracking_max_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_egg_max),
        )
        x, _ = get_widget_position(self.end_screen_tracking_max_widget)
        move_widget(
            self.end_screen_tracking_max_widget,
            x,
            progress_bar_max_y - floor(self.similarity_to_end_screen_max),
        )

        progress_bar_max_y = 134

        # thresholds
        x, _ = get_widget_position(self.elevator_threshold_value_line)
        move_widget(
            self.elevator_threshold_value_line,
            x,
            progress_bar_max_y - floor(self.settings_dict["similarity_threshold_elevator"]),
        )
        x, _ = get_widget_position(self.tram_threshold_value_line)
        move_widget(
            self.tram_threshold_value_line,
            x,
            progress_bar_max_y - floor(self.settings_dict["similarity_threshold_tram"]),
        )
        x, _ = get_widget_position(self.teleportal_threshold_value_line)
        move_widget(
            self.teleportal_threshold_value_line,
            x,
            progress_bar_max_y - floor(self.settings_dict["similarity_threshold_teleportal"]),
        )
        x, _ = get_widget_position(self.egg_threshold_value_line)
        move_widget(
            self.egg_threshold_value_line,
            x,
            progress_bar_max_y - floor(self.settings_dict["similarity_threshold_egg"]),
        )
        x, _ = get_widget_position(self.end_screen_threshold_value_line)
        move_widget(
            self.end_screen_threshold_value_line,
            x,
            progress_bar_max_y - floor(self.settings_dict["similarity_threshold_end_screen"]),
        )

    def __on_take_screenshot_button_pressed(self):
        capture_view = self.get_capture_type_for_screenshots(self.settings_dict["capture_view_preview"])
        if not is_valid_image(capture_view):
            error_messages.invalid_screenshot()
            return

        if not self.settings_dict["screenshot_directory"]:
            set_screenshot_location(self)

        if not self.settings_dict["screenshot_directory"]:
            error_messages.screenshot_directory_not_set()
            return

        now = LocalTime()

        filename = get_sanitized_filename(f"zdcurtain_{now.date}")

        take_screenshot(
            self.settings_dict["screenshot_directory"],
            filename,
            capture_view,
        )

    @override
    def closeEvent(self, event: QtGui.QCloseEvent | None = None):
        """Exit safely when closing the window."""

        def exit_program(_zdcurtain_ref, event) -> NoReturn:
            _zdcurtain_ref.capture_method.close()
            if event is not None:
                event.accept()
            sys.exit()

        exit_program(self, event)

        # Fallthrough case: Prevent program from closing.
        event.ignore()
