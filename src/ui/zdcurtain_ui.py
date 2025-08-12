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

from collections.abc import Callable
from copy import deepcopy
from math import floor
from types import FunctionType
from typing import NoReturn, override

import cv2
from cv2.typing import MatLike
from gen import about as about_ui, settings as settings_ui, zdcurtain as zdcurtain_ui
from PySide6 import QtCore, QtGui
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QLabel, QMainWindow

import error_messages
from capture_method import CaptureMethodBase, CaptureMethodEnum
from frame_analysis import get_black_screen_detection_area, normalize_brightness_histogram
from hotkeys import HOTKEYS, after_setting_hotkey
from load_removal import (
    end_tracking_load,
    perform_black_level_analysis,
    perform_load_removal_logic,
    perform_similarity_analysis,
)
from load_tracking import LoadRemovalSession, export_tracked_loads
from region_selection import select_window
from stylesheets import style_progress_bar_fail, style_progress_bar_pass
from ui.about_ui import open_about
from ui.settings_ui import get_default_settings_from_ui, open_settings
from user_profile import (
    DEFAULT_PROFILE,
    load_settings,
    load_settings_on_open,
    save_settings,
    save_settings_as,
)
from utils import (
    BGR_CHANNEL_COUNT,
    BGRA_CHANNEL_COUNT,
    ONE_SECOND,
    ZDCURTAIN_VERSION,
    ImageShape,
    LocalTime,
    create_icon,
    create_yes_no_dialog,
    get_widget_position,
    imread,
    imwrite,
    is_valid_image,
    move_widget,
    ms_to_msms,
    ns_to_ms,
    resource_path,
)
from ZDImage import ZDImage, resize_image


class ZDCurtain(QMainWindow, zdcurtain_ui.Ui_ZDCurtain):
    # Signals
    pause_signal = QtCore.Signal()
    capture_state_changed_signal = QtCore.Signal()
    after_setting_hotkey_signal = QtCore.Signal()
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

    def __init__(self):
        super().__init__()

        self.__init_variables()
        self.__init_measurement_variables()

        load_images(self)

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
        # load removal
        self.is_tracking = False
        self.is_load_being_removed = False
        self.single_load_time_removed_ms = 0.0
        self.load_time_removed_ms = 0.0
        self.load_removal_session = None
        self.captured_window_title_before_load = ""

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
        self.blacklevel_entropy = 0.0
        self.average_luminance = 0.0
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
        self.gunship_icon = None
        self.loading_icon = None

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

        # screenshots
        self.screenshot_timer = 0
        self.screenshot_counter = 1
        self.take_screenshots = False

    def __bind_icons(self):
        create_icon(self.elevator_tracking_icon, self.elevator_icon)
        create_icon(self.tram_tracking_icon, self.tram_icon)
        create_icon(self.teleportal_tracking_icon, self.teleportal_icon)
        create_icon(self.egg_tracking_icon, self.capsule_icon)
        create_icon(self.end_screen_tracking_icon, self.gunship_icon)

    def __setup_bindings(self):
        # connecting menu actions
        self.action_settings.triggered.connect(lambda: open_settings(self))
        self.action_save_settings.triggered.connect(lambda: save_settings(self))
        self.action_save_settings_as.triggered.connect(lambda: save_settings_as(self))
        self.action_load_settings.triggered.connect(lambda: load_settings(self))
        self.action_capture_standard.triggered.connect(
            lambda: self.set_capture_type_for_screenshots("standard_resized")
        )
        self.action_capture_normalized.triggered.connect(
            lambda: self.set_capture_type_for_screenshots("normalized_resized")
        )
        self.action_hide_analysis_elements.changed.connect(
            lambda: self.set_analysis_elements_hidden(self.settings_dict["hide_analysis_elements"])
        )
        self.action_export_tracked_loads.triggered.connect(
            lambda: export_tracked_loads(self.load_removal_session)
        )
        self.action_about.triggered.connect(lambda: open_about(self))
        self.action_exit.triggered.connect(lambda: self.closeEvent())  # noqa: PLW0108

        # connecting button clicks to functions
        self.select_window_button.clicked.connect(lambda: select_window_and_start_tracking(self))
        self.select_device_button.clicked.connect(lambda: open_settings(self))
        self.reset_statistics_button.clicked.connect(self.on_reset_statistics_button_press)
        self.clear_load_removal_session_button.clicked.connect(
            self.on_clear_load_removal_session_button_press
        )
        self.begin_end_tracking_button.clicked.connect(self.on_tracking_button_press)

        # connect signals to functions
        self.after_setting_hotkey_signal.connect(lambda: after_setting_hotkey(self))
        self.capture_state_changed_signal.connect(lambda: on_capture_state_changed(self))

        self.timer_main.timeout.connect(self.__run_app_logic)
        self.timer_frame_analysis.timeout.connect(
            lambda: self.__update_live_image_details(None, called_from_timer=True)
        )
        self.timer_capture_stream_timed_out.timeout.connect(self.__give_up_capture_recovery)

        # image bindings
        self.__bind_icons()

        # function bindings
        self.set_analysis_elements_hidden(self.settings_dict["hide_analysis_elements"])
        self.set_capture_type_for_screenshots(self.settings_dict["capture_view_preview"])

        # Set up capture view select
        action_group = QtGui.QActionGroup(self, exclusionPolicy=QActionGroup.ExclusionPolicy.Exclusive)
        a = action_group.addAction(self.action_capture_standard)
        b = action_group.addAction(self.action_capture_normalized)
        self.menuCapture.addActions([a, b])

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
        self.attempt_to_recover_capture_if_lost = False
        self.ever_had_capture = False
        self.timer_capture_stream_timed_out.stop()
        self.live_image.setText("Couldn't find capture stream to recover!")
        self.settings_dict["captured_window_title"] = ""
        self.show_error_signal.emit(error_messages.couldnt_find_capture_to_recover)

    def __run_app_logic(self):
        update_ui(self)

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
                self.capture_view_resized = resize_image(self.capture_view_raw, dim, 1, cv2.INTER_AREA)
                self.capture_view_resized_normalized = normalize_brightness_histogram(
                    self.capture_view_resized
                )

                capture_view_to_use = self.get_capture_view_by_name(
                    self.settings_dict["capture_view_preview"]
                )

                if self.settings_dict["live_capture_region"]:
                    set_preview_image(self.live_image, capture_view_to_use)

                if self.is_tracking:
                    self.capture_view_resized_cropped = get_black_screen_detection_area(
                        self.capture_view_resized
                    )

                    perform_black_level_analysis(self)
                    perform_similarity_analysis(self)
                    perform_load_removal_logic(self)

                    if self.take_screenshots:
                        if self.screenshot_timer >= 4:
                            imwrite(
                                f"sshot/sshot_{self.screenshot_counter}.png",
                                self.capture_view_resized_normalized,
                            )
                            self.screenshot_timer = 0
                            self.screenshot_counter += 1

                        self.screenshot_timer += 1
            elif (
                self.settings_dict["captured_window_title"]
                and self.ever_had_capture
                and self.attempt_to_recover_capture_if_lost
            ):
                if not self.timer_capture_stream_timed_out.isActive():
                    self.timer_capture_stream_timed_out.start(self.settings_dict["capture_stream_timeout_ms"])
                    # if it happens during a currently tracked load, stop tracking the load IMMEDIATELY
                    throw_out_in_progress_load(self)

                self.__try_to_recover_capture()

        frame_end_time = perf_counter_ns()

        frame_time = ns_to_ms(frame_end_time - frame_start_time)

        if self.black_screen_detected_at_timestamp <= self.black_screen_over_detected_at_timestamp:
            self.last_black_screen_time = ns_to_ms(
                self.black_screen_over_detected_at_timestamp - self.black_screen_detected_at_timestamp
            )

        self.analysis_status_label.setText(
            f"Frame Time: {frame_time:.2f}, Load Type: {self.active_load_type}, "
            + f"Last Black Screen Duration {self.last_black_screen_time}ms "
        )

        tltr_m, tltr_s, tltr_ms = ms_to_msms(self.load_time_removed_ms)

        self.total_load_time_removed_label.setText(f"{tltr_m:.0f}m {tltr_s:.0f}s {tltr_ms:.0f}ms")

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

    def pause_timer(self):
        # TODO: add what to do when you hit pause hotkey, if this even needs to be done
        pass

    def reset_icons(self):
        self.__bind_icons()

    def reset_all_variables(self):
        self.__reset_tracking_variables()
        self.__reset_load_data()

    def __reset_tracking_variables(self):
        self.active_load_type = "none"
        self.black_screen_detected_at_timestamp = 0
        self.black_screen_over_detected_at_timestamp = 0
        self.potential_load_detected_at_timestamp = 0
        self.confirmed_load_detected_at_timestamp = 0
        self.is_load_being_removed = False
        self.in_black_screen = False
        self.black_level = 1.0
        self.blacklevel_entropy = 100.0
        self.is_frame_black = False
        self.last_black_screen_time = 0
        self.load_confidence_delta = 0
        self.load_cooldown_timestamp = 0
        self.load_cooldown_is_active = False
        self.load_cooldown_type = "none"
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
        else:
            if self.load_removal_session is None:
                self.load_removal_session = LoadRemovalSession()

            self.__begin_tracking()

    def __reset_load_data(self):
        self.load_removal_session = LoadRemovalSession()
        self.previous_loads_list.clear()

    def __reset_load_data_and_begin_tracking(self):
        self.__reset_load_data()
        self.__begin_tracking()

    def __begin_tracking(self):
        self.is_tracking = True
        self.begin_end_tracking_button.setText("End Tracking")
        if not self.action_hide_analysis_elements:
            self.analysis_status_label.show()

    def end_tracking(self, *, ending_due_to_error=False):
        if not self.is_tracking:  # we're not tracking, no need to run this
            return

        self.__reset_tracking_variables()
        self.is_tracking = False
        self.begin_end_tracking_button.setText("Begin Tracking")

        if not self.action_hide_analysis_elements:
            self.analysis_status_label.hide()

        if (
            self.load_removal_session is not None
            and self.load_removal_session.get_load_count() > 0
            and not ending_due_to_error
        ):
            create_yes_no_dialog(
                "Export Load Removal Session",
                "Would you like to export the results of your load removal session to a file?",
                lambda: export_tracked_loads(self.load_removal_session),
                None,
            )

    def set_analysis_elements_hidden(self, should_hide):
        self.settings_dict["hide_analysis_elements"] = not should_hide
        self.black_screen_detection_area_label.setHidden(should_hide)
        self.analysis_status_label.setHidden(should_hide)
        self.analysis_load_cooldown_label.setHidden(should_hide)

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
        self.begin_end_tracking_button.setEnabled(should_be_enabled)
        self.clear_load_removal_session_button.setEnabled(should_be_enabled)
        self.action_export_tracked_loads.setEnabled(should_be_enabled)

    def set_active_capture_dependencies_enabled(self, *, should_be_enabled: bool):
        self.reset_statistics_button.setEnabled(should_be_enabled)
        self.begin_end_tracking_button.setEnabled(should_be_enabled)
        self.clear_load_removal_session_button.setEnabled(should_be_enabled)

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


def throw_out_in_progress_load(_zdcurtain_ref: "ZDCurtain"):
    if _zdcurtain_ref.load_removal_session is None:
        return

    if _zdcurtain_ref.is_load_being_removed:
        load_lost_at = LocalTime()

        lost_load_record = _zdcurtain_ref.load_removal_session.create_lost_load_record(
            _zdcurtain_ref.active_load_type, load_lost_at
        )

        _zdcurtain_ref.previous_loads_list.insertItem(0, lost_load_record.to_string())

        _zdcurtain_ref.show_error_signal.emit(
            lambda: error_messages.capture_stream_lost_during_load(load_lost_at)
        )

        end_tracking_load(_zdcurtain_ref)


def on_capture_state_changed(_zdcurtain_ref: "ZDCurtain"):
    if (
        _zdcurtain_ref.settings_dict["captured_window_title"]
        != _zdcurtain_ref.captured_window_title_before_load
        and _zdcurtain_ref.is_load_being_removed
    ):
        # it looks like the capture state changed in the middle of a load, we should give a warning
        throw_out_in_progress_load(_zdcurtain_ref)

    _zdcurtain_ref.timer_capture_stream_timed_out.stop()

    _zdcurtain_ref.attempt_to_recover_capture_if_lost = True
    _zdcurtain_ref.set_active_capture_dependencies_enabled(should_be_enabled=True)


def update_ui(_zdcurtain_ref: "ZDCurtain"):
    # Update title from target window or Capture Device name
    capture_region_window_label = (
        _zdcurtain_ref.settings_dict["capture_device_name"]
        if _zdcurtain_ref.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
        else _zdcurtain_ref.settings_dict["captured_window_title"]
    )

    if (
        is_valid_image(_zdcurtain_ref.capture_view_raw)
        and not _zdcurtain_ref.reset_statistics_button.isEnabled()
    ):
        _zdcurtain_ref.set_active_capture_dependencies_enabled(should_be_enabled=True)

    if (
        not is_valid_image(_zdcurtain_ref.capture_view_raw)
        and _zdcurtain_ref.reset_statistics_button.isEnabled()
    ):
        _zdcurtain_ref.set_active_capture_dependencies_enabled(should_be_enabled=False)

    _zdcurtain_ref.capture_region_window_label.setText(capture_region_window_label)

    black_level_text = f"{_zdcurtain_ref.black_level:.0f}" if _zdcurtain_ref.is_tracking else "--"

    # labels
    _zdcurtain_ref.black_level_label.setText(f"{black_level_text}")
    _zdcurtain_ref.elevator_tracking_max_label.setText(f"{_zdcurtain_ref.similarity_to_elevator_max:.0f}")
    _zdcurtain_ref.tram_tracking_max_label.setText(f"{_zdcurtain_ref.similarity_to_tram_max:.0f}")
    _zdcurtain_ref.teleportal_tracking_max_label.setText(f"{_zdcurtain_ref.similarity_to_teleportal_max:.0f}")
    _zdcurtain_ref.egg_tracking_max_label.setText(f"{_zdcurtain_ref.similarity_to_egg_max:.0f}")
    _zdcurtain_ref.end_screen_tracking_max_label.setText(f"{_zdcurtain_ref.similarity_to_end_screen_max:.0f}")

    # progress bars
    _zdcurtain_ref.entropy_bar.setValue(int(_zdcurtain_ref.blacklevel_entropy))
    _zdcurtain_ref.elevator_tracking_bar.setValue(int(_zdcurtain_ref.similarity_to_elevator))
    _zdcurtain_ref.tram_tracking_bar.setValue(int(_zdcurtain_ref.similarity_to_tram))
    _zdcurtain_ref.teleportal_tracking_bar.setValue(int(_zdcurtain_ref.similarity_to_teleportal))
    _zdcurtain_ref.egg_tracking_bar.setValue(int(_zdcurtain_ref.similarity_to_egg))
    _zdcurtain_ref.end_screen_tracking_bar.setValue(int(_zdcurtain_ref.similarity_to_end_screen))

    # dynamic colors
    _zdcurtain_ref.black_average_label.setStyleSheet(
        f"background-color: hsl(0%,0%,{floor(_zdcurtain_ref.average_luminance / 255 * 100)}%)"
    )

    _zdcurtain_ref.elevator_tracking_bar.setStyleSheet(
        style_progress_bar_pass
        if _zdcurtain_ref.similarity_to_elevator
        > _zdcurtain_ref.settings_dict["similarity_threshold_elevator"]
        else style_progress_bar_fail
    )
    _zdcurtain_ref.tram_tracking_bar.setStyleSheet(
        style_progress_bar_pass
        if _zdcurtain_ref.similarity_to_tram > _zdcurtain_ref.settings_dict["similarity_threshold_tram"]
        else style_progress_bar_fail
    )
    _zdcurtain_ref.teleportal_tracking_bar.setStyleSheet(
        style_progress_bar_pass
        if _zdcurtain_ref.similarity_to_teleportal
        > _zdcurtain_ref.settings_dict["similarity_threshold_teleportal"]
        else style_progress_bar_fail
    )
    _zdcurtain_ref.egg_tracking_bar.setStyleSheet(
        style_progress_bar_pass
        if _zdcurtain_ref.similarity_to_egg > _zdcurtain_ref.settings_dict["similarity_threshold_egg"]
        else style_progress_bar_fail
    )
    _zdcurtain_ref.end_screen_tracking_bar.setStyleSheet(
        style_progress_bar_pass
        if _zdcurtain_ref.similarity_to_end_screen
        > _zdcurtain_ref.settings_dict["similarity_threshold_end_screen"]
        else style_progress_bar_fail
    )

    # dynamic label positioning

    progress_bar_max_y = 120

    x, _ = get_widget_position(_zdcurtain_ref.elevator_tracking_max_widget)

    move_widget(
        _zdcurtain_ref.elevator_tracking_max_widget,
        x,
        progress_bar_max_y - floor(_zdcurtain_ref.similarity_to_elevator_max),
    )

    x, _ = get_widget_position(_zdcurtain_ref.tram_tracking_max_widget)

    move_widget(
        _zdcurtain_ref.tram_tracking_max_widget,
        x,
        progress_bar_max_y - floor(_zdcurtain_ref.similarity_to_tram_max),
    )

    x, _ = get_widget_position(_zdcurtain_ref.teleportal_tracking_max_widget)

    move_widget(
        _zdcurtain_ref.teleportal_tracking_max_widget,
        x,
        progress_bar_max_y - floor(_zdcurtain_ref.similarity_to_teleportal_max),
    )

    x, _ = get_widget_position(_zdcurtain_ref.egg_tracking_max_widget)

    move_widget(
        _zdcurtain_ref.egg_tracking_max_widget,
        x,
        progress_bar_max_y - floor(_zdcurtain_ref.similarity_to_egg_max),
    )

    x, _ = get_widget_position(_zdcurtain_ref.end_screen_tracking_max_widget)

    move_widget(
        _zdcurtain_ref.end_screen_tracking_max_widget,
        x,
        progress_bar_max_y - floor(_zdcurtain_ref.similarity_to_end_screen_max),
    )


def load_images(_zdcurtain_ref):
    _zdcurtain_ref.elevator_icon = read_image("res/icons/elevator_icon.png")
    _zdcurtain_ref.tram_icon = read_image("res/icons/tram_icon.png")
    _zdcurtain_ref.teleportal_icon = read_image("res/icons/teleportal_icon.png")
    _zdcurtain_ref.capsule_icon = read_image("res/icons/capsule_icon.png")
    _zdcurtain_ref.gunship_icon = read_image("res/icons/gunship_icon_small.png")
    _zdcurtain_ref.loading_icon = read_image("res/icons/loading_icon.png")

    load_comparison_images(_zdcurtain_ref)


def load_comparison_images(_zdcurtain_ref):
    _zdcurtain_ref.comparison_capsule_gravity = read_and_format_zdimage("res/comparison/capsule_gravity.png")
    _zdcurtain_ref.comparison_capsule_power = read_and_format_zdimage("res/comparison/capsule_power.png")
    _zdcurtain_ref.comparison_capsule_varia = read_and_format_zdimage("res/comparison/capsule_varia.png")
    _zdcurtain_ref.comparison_elevator_gravity = read_and_format_zdimage(
        "res/comparison/elevator_gravity.png"
    )
    _zdcurtain_ref.comparison_elevator_power = read_and_format_zdimage("res/comparison/elevator_power.png")
    _zdcurtain_ref.comparison_elevator_varia = read_and_format_zdimage("res/comparison/elevator_varia.png")
    _zdcurtain_ref.comparison_teleport_gravity = read_and_format_zdimage(
        "res/comparison/teleport_gravity.png"
    )
    _zdcurtain_ref.comparison_teleport_power = read_and_format_zdimage("res/comparison/teleport_power.png")
    _zdcurtain_ref.comparison_teleport_varia = read_and_format_zdimage("res/comparison/teleport_varia.png")
    _zdcurtain_ref.comparison_train_left_gravity = read_and_format_zdimage(
        "res/comparison/train_left_gravity.png"
    )
    _zdcurtain_ref.comparison_train_left_power = read_and_format_zdimage(
        "res/comparison/train_left_power.png"
    )
    _zdcurtain_ref.comparison_train_left_varia = read_and_format_zdimage(
        "res/comparison/train_left_varia.png"
    )
    _zdcurtain_ref.comparison_train_right_gravity = read_and_format_zdimage(
        "res/comparison/train_right_gravity.png"
    )
    _zdcurtain_ref.comparison_train_right_power = read_and_format_zdimage(
        "res/comparison/train_right_power.png"
    )
    _zdcurtain_ref.comparison_train_right_varia = read_and_format_zdimage(
        "res/comparison/train_right_varia.png"
    )
    _zdcurtain_ref.comparison_end_screen = read_and_format_zdimage("res/comparison/end_screen.png")


def read_image(filename):
    image = imread(resource_path(filename), cv2.IMREAD_UNCHANGED)

    if image.shape[ImageShape.Channels] == BGR_CHANNEL_COUNT:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGRA)
    else:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA)

    return image


def read_and_format_zdimage(filename):
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


def select_window_and_start_tracking(_zdcurtain_ref):
    select_window(_zdcurtain_ref)

    if (
        _zdcurtain_ref.settings_dict["start_tracking_automatically"]
        and not _zdcurtain_ref.is_tracking
        and is_valid_image(_zdcurtain_ref.capture_view_raw)
    ):
        _zdcurtain_ref.begin_tracking()
