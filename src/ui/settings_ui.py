from functools import partial
from typing import TYPE_CHECKING, Any, cast

from gen import settings as settings_ui
from PySide6 import QtWidgets
from PySide6.QtWidgets import QFileDialog

from capture_method import (
    CAPTURE_METHODS,
    CameraInfo,
    CaptureMethodEnum,
    change_capture_method,
    get_all_video_capture_devices,
)
from hotkeys import HOTKEYS, set_hotkey
from user_profile import DEFAULT_PROFILE, UserProfileDict
from utils import ONE_SECOND, fire_and_forget

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain


class __SettingsWidget(QtWidgets.QWidget, settings_ui.Ui_SettingsWidget):
    __stream_overlay_text_color: tuple = ("Automatic", "Black", "White")

    def __init__(self, zdcurtain: "ZDCurtain"):
        super().__init__()
        self.__video_capture_devices: list[CameraInfo] = []
        """
        Used to temporarily store the existing cameras,
        we don't want to call `get_all_video_capture_devices` again
        and possibly have a different result
        """

        self.setupUi(self)

        self._zdcurtain_ref = zdcurtain
        # Don't autofocus any particular field
        self.setFocus()

        # region Build the Capture method combobox  # fmt: skip
        capture_method_values = CAPTURE_METHODS.values()
        self.__set_all_capture_devices()
        self.capture_method_combobox.addItems([
            f"- {method.name} ({method.short_description})" for method in capture_method_values
        ])

        build_documentation(self)
        self.__setup_bindings()

        self.show()

    def __update_default_threshold(self, key: str, value: Any):
        self.__set_value(key, value)

    def __set_value(self, key: str, value: Any):
        self._zdcurtain_ref.settings_dict[key] = value

    def get_capture_device_index(self, capture_device_id: int):
        """Returns 0 if the capture_device_id is invalid."""
        try:
            return [
                device.device_id  # fmt: skip
                for device in self.__video_capture_devices
            ].index(capture_device_id)
        except ValueError:
            return 0

    def __enable_capture_device_if_its_selected_method(
        self,
        selected_capture_method: str | CaptureMethodEnum | None = None,
    ):
        if selected_capture_method is None:
            selected_capture_method = self._zdcurtain_ref.settings_dict["capture_method"]
        is_video_capture_device = selected_capture_method == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
        self.capture_device_combobox.setEnabled(is_video_capture_device)
        if is_video_capture_device:
            self.capture_device_combobox.setCurrentIndex(
                self.get_capture_device_index(self._zdcurtain_ref.settings_dict["capture_device_id"])
            )
        else:
            self.capture_device_combobox.setPlaceholderText('Select "Video Capture Device" above')
            self.capture_device_combobox.setCurrentIndex(-1)

    def __capture_method_changed(self):
        selected_capture_method = CAPTURE_METHODS.get_method_by_index(
            self.capture_method_combobox.currentIndex()
        )
        self.__enable_capture_device_if_its_selected_method(selected_capture_method)
        change_capture_method(selected_capture_method, self._zdcurtain_ref)

        return selected_capture_method

    def __capture_device_changed(self):
        device_index = self.capture_device_combobox.currentIndex()
        if device_index == -1:
            return
        capture_device = self.__video_capture_devices[device_index]
        self._zdcurtain_ref.settings_dict["capture_device_name"] = capture_device.name
        self._zdcurtain_ref.settings_dict["capture_device_id"] = capture_device.device_id
        if self._zdcurtain_ref.settings_dict["capture_method"] == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE:
            # Re-initializes the VideoCaptureDeviceCaptureMethod
            change_capture_method(CaptureMethodEnum.VIDEO_CAPTURE_DEVICE, self._zdcurtain_ref)

    def __fps_limit_changed(self, value: int):
        value = self.fps_limit_spinbox.value()
        self._zdcurtain_ref.settings_dict["fps_limit"] = value
        self._zdcurtain_ref.timer_frame_analysis.setInterval(int(ONE_SECOND / value))

    @fire_and_forget
    def __set_all_capture_devices(self):
        self.__video_capture_devices = get_all_video_capture_devices()
        if len(self.__video_capture_devices) > 0:
            for i in range(self.capture_device_combobox.count()):
                self.capture_device_combobox.removeItem(i)
            self.capture_device_combobox.addItems([
                f"* {device.name}"
                + (f" [{device.backend}]" if device.backend else "")
                + (" (occupied)" if device.occupied else "")
                for device in self.__video_capture_devices
            ])
            self.__enable_capture_device_if_its_selected_method()
        else:
            self.capture_device_combobox.setPlaceholderText("No device found.")

    def __on_screenshot_location_folder_button_pressed(self):
        set_screenshot_location(self._zdcurtain_ref)
        self.locations_screenshot_folder_input.setText(
            self._zdcurtain_ref.settings_dict["screenshot_directory"]
        )

    def __on_blink_when_tracking_disabled_checkbox_changed(self):
        self.__set_value(
            "blink_when_tracking_disabled", self.blink_when_tracking_disabled_checkbox.isChecked()
        )
        self._zdcurtain_ref.after_changing_tracking_status.emit()

    def __setup_bindings(self):
        # Hotkey initial values and bindings
        for hotkey in HOTKEYS:
            hotkey_input: QtWidgets.QLineEdit = getattr(self, f"{hotkey}_input")
            set_hotkey_hotkey_button: QtWidgets.QPushButton = getattr(
                self,
                f"set_{hotkey}_hotkey_button",
            )
            hotkey_input.setText(self._zdcurtain_ref.settings_dict.get(f"{hotkey}_hotkey", ""))

            set_hotkey_hotkey_button.clicked.connect(partial(set_hotkey, self._zdcurtain_ref, hotkey=hotkey))

        # region Set initial values
        # Capture Settings
        self.fps_limit_spinbox.setValue(self._zdcurtain_ref.settings_dict["fps_limit"])
        self.live_capture_region_checkbox.setChecked(self._zdcurtain_ref.settings_dict["live_capture_region"])
        self.capture_method_combobox.setCurrentIndex(
            CAPTURE_METHODS.get_index(self._zdcurtain_ref.settings_dict["capture_method"])
        )

        # Image Analysis Settings
        self.black_screen_threshold_spinbox.setValue(self._zdcurtain_ref.settings_dict["black_threshold"])
        self.black_screen_entropy_threshold_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["black_entropy_threshold"]
        )
        self.load_confidence_threshold_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["load_confidence_threshold_ms"]
        )
        self.elevator_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_elevator"]
        )
        self.tram_similarity_spinbox.setValue(self._zdcurtain_ref.settings_dict["similarity_threshold_tram"])
        self.teleportal_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_teleportal"]
        )
        self.egg_similarity_spinbox.setValue(self._zdcurtain_ref.settings_dict["similarity_threshold_egg"])
        self.end_screen_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_end_screen"]
        )
        self.start_tracking_automatically_checkbox.setChecked(
            self._zdcurtain_ref.settings_dict["start_tracking_automatically"]
        )
        self.clear_previous_session_on_begin_tracking_checkbox.setChecked(
            self._zdcurtain_ref.settings_dict["clear_previous_session_on_begin_tracking"]
        )
        self.stream_overlay_text_color_combobox.setCurrentIndex(
            self.__stream_overlay_text_color.index(
                self._zdcurtain_ref.settings_dict["stream_overlay_text_color"]
            )
        )
        self.ask_to_export_data_combobox.setCurrentIndex(
            self._zdcurtain_ref.settings_dict["ask_to_export_data"]
        )
        # Overlay Settings
        self.blink_when_tracking_disabled_checkbox.setChecked(
            self._zdcurtain_ref.settings_dict["blink_when_tracking_disabled"]
        )
        self.open_overlay_on_open_checkbox.setChecked(
            self._zdcurtain_ref.settings_dict["stream_overlay_open_on_open"]
        )
        # endregion

        # region Binding
        # Capture Settings
        self.fps_limit_spinbox.valueChanged.connect(self.__fps_limit_changed)
        self.live_capture_region_checkbox.stateChanged.connect(
            lambda: self.__set_value(
                "live_capture_region",
                self.live_capture_region_checkbox.isChecked(),
            )
        )
        self.capture_method_combobox.currentIndexChanged.connect(
            lambda: self.__set_value("capture_method", self.__capture_method_changed())
        )
        self.capture_device_combobox.currentIndexChanged.connect(self.__capture_device_changed)

        # Image Analysis Settings
        self.black_screen_threshold_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "black_threshold", self.black_screen_threshold_spinbox.value()
            )
        )
        self.black_screen_entropy_threshold_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "black_entropy_threshold", self.black_screen_entropy_threshold_spinbox.value()
            )
        )
        self.load_confidence_threshold_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "load_confidence_threshold_ms", self.load_confidence_threshold_spinbox.value()
            )
        )
        self.elevator_similarity_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "similarity_threshold_elevator", self.elevator_similarity_spinbox.value()
            )
        )
        self.tram_similarity_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "similarity_threshold_tram", self.tram_similarity_spinbox.value()
            )
        )
        self.teleportal_similarity_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "similarity_threshold_teleportal", self.teleportal_similarity_spinbox.value()
            )
        )
        self.egg_similarity_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "similarity_threshold_egg", self.egg_similarity_spinbox.value()
            )
        )
        self.end_screen_similarity_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "similarity_threshold_end_screen", self.end_screen_similarity_spinbox.value()
            )
        )

        # stream overlay settings
        self.stream_overlay_text_color_combobox.currentIndexChanged.connect(
            lambda: self.__set_value(
                "stream_overlay_text_color", self.stream_overlay_text_color_combobox.currentText()
            )
        )
        self.blink_when_tracking_disabled_checkbox.stateChanged.connect(
            self.__on_blink_when_tracking_disabled_checkbox_changed
        )

        # other settings
        self.start_tracking_automatically_checkbox.stateChanged.connect(
            lambda: self.__set_value(
                "start_tracking_automatically",
                self.start_tracking_automatically_checkbox.isChecked(),
            )
        )
        self.open_overlay_on_open_checkbox.stateChanged.connect(
            lambda: self.__set_value(
                "stream_overlay_open_on_open",
                self.open_overlay_on_open_checkbox.isChecked(),
            )
        )
        self.clear_previous_session_on_begin_tracking_checkbox.stateChanged.connect(
            lambda: self.__set_value(
                "clear_previous_session_on_begin_tracking",
                self.clear_previous_session_on_begin_tracking_checkbox.isChecked(),
            )
        )
        self.live_capture_region_checkbox.stateChanged.connect(
            lambda: self.__set_value(
                "live_capture_region",
                self.live_capture_region_checkbox.isChecked(),
            )
        )
        self.ask_to_export_data_combobox.currentIndexChanged.connect(
            lambda: self.__set_value("ask_to_export_data", self.ask_to_export_data_combobox.currentIndex())
        )

        # screenshots
        self.locations_screenshot_folder_input.setText(
            self._zdcurtain_ref.settings_dict["screenshot_directory"]
        )
        self.locations_screenshot_folder_button.clicked.connect(
            self.__on_screenshot_location_folder_button_pressed
        )

        # endregion


def set_screenshot_location(_zdcurtain_ref: "ZDCurtain"):
    selected_directory = QFileDialog.getExistingDirectory()

    if selected_directory:
        _zdcurtain_ref.settings_dict["screenshot_directory"] = selected_directory
    else:
        _zdcurtain_ref.settings_dict["screenshot_directory"] = ""


def open_settings(zdcurtain: "ZDCurtain"):
    if not zdcurtain.SettingsWidget or cast(QtWidgets.QWidget, zdcurtain.SettingsWidget).isHidden():
        zdcurtain.SettingsWidget = __SettingsWidget(zdcurtain)


def get_default_settings_from_ui():
    temp_dialog = QtWidgets.QWidget()
    default_settings_dialog = settings_ui.Ui_SettingsWidget()
    default_settings_dialog.setupUi(temp_dialog)
    default_settings: UserProfileDict = {
        "fps_limit": default_settings_dialog.fps_limit_spinbox.value(),
        "live_capture_region": default_settings_dialog.live_capture_region_checkbox.isChecked(),
        "capture_method": CAPTURE_METHODS.get_method_by_index(
            default_settings_dialog.capture_method_combobox.currentIndex()
        ),
        "capture_stream_timeout_ms": DEFAULT_PROFILE["capture_stream_timeout_ms"],
        "capture_device_id": default_settings_dialog.capture_device_combobox.currentIndex(),
        "capture_device_name": "",
        "captured_window_title": "",
        "take_screenshot_hotkey": default_settings_dialog.take_screenshot_input.text(),
        "begin_tracking_hotkey": default_settings_dialog.begin_tracking_input.text(),
        "end_tracking_hotkey": default_settings_dialog.end_tracking_input.text(),
        "clear_load_removal_session_hotkey": default_settings_dialog.clear_load_removal_session_input.text(),
        "stream_overlay_text_color": default_settings_dialog.stream_overlay_text_color_combobox.currentText(),
        "stream_overlay_open_on_open": default_settings_dialog.open_overlay_on_open_checkbox.isChecked(),
        "start_tracking_automatically": default_settings_dialog.start_tracking_automatically_checkbox.isChecked(),  # noqa: E501
        "clear_previous_session_on_begin_tracking": default_settings_dialog.clear_previous_session_on_begin_tracking_checkbox.isChecked(),  # noqa: E501
        "ask_to_export_data": default_settings_dialog.ask_to_export_data_combobox.currentIndex(),
        "blink_when_tracking_disabled": default_settings_dialog.blink_when_tracking_disabled_checkbox.isChecked(),
        "hide_analysis_elements": DEFAULT_PROFILE["hide_analysis_elements"],
        "hide_frame_info": DEFAULT_PROFILE["hide_frame_info"],
        "overlay_color_key_rgb": DEFAULT_PROFILE["overlay_color_key_rgb"],
        "black_threshold": default_settings_dialog.black_screen_threshold_spinbox.value(),
        "black_entropy_threshold": default_settings_dialog.black_screen_entropy_threshold_spinbox.value(),
        "capture_view_preview": DEFAULT_PROFILE["capture_view_preview"],
        "capture_view_elevator": DEFAULT_PROFILE["capture_view_elevator"],
        "capture_view_tram": DEFAULT_PROFILE["capture_view_tram"],
        "capture_view_teleportal": DEFAULT_PROFILE["capture_view_teleportal"],
        "capture_view_egg": DEFAULT_PROFILE["capture_view_egg"],
        "capture_view_end_screen": DEFAULT_PROFILE["capture_view_end_screen"],
        "similarity_algorithm_elevator": DEFAULT_PROFILE["similarity_algorithm_elevator"],
        "similarity_algorithm_tram": DEFAULT_PROFILE["similarity_algorithm_tram"],
        "similarity_algorithm_teleportal": DEFAULT_PROFILE["similarity_algorithm_teleportal"],
        "similarity_algorithm_egg": DEFAULT_PROFILE["similarity_algorithm_egg"],
        "similarity_algorithm_end_screen": DEFAULT_PROFILE["similarity_algorithm_end_screen"],
        "similarity_threshold_elevator": default_settings_dialog.elevator_similarity_spinbox.value(),
        "similarity_threshold_tram": default_settings_dialog.tram_similarity_spinbox.value(),
        "similarity_threshold_teleportal": default_settings_dialog.teleportal_similarity_spinbox.value(),
        "similarity_threshold_egg": default_settings_dialog.egg_similarity_spinbox.value(),
        "similarity_threshold_end_screen": default_settings_dialog.end_screen_similarity_spinbox.value(),
        "load_cooldown_elevator_ms": DEFAULT_PROFILE["load_cooldown_elevator_ms"],
        "load_cooldown_tram_ms": DEFAULT_PROFILE["load_cooldown_tram_ms"],
        "load_cooldown_teleportal_ms": DEFAULT_PROFILE["load_cooldown_teleportal_ms"],
        "load_cooldown_egg_ms": DEFAULT_PROFILE["load_cooldown_egg_ms"],
        "load_cooldown_spinner_ms": DEFAULT_PROFILE["load_cooldown_spinner_ms"],
        "load_confidence_threshold_ms": default_settings_dialog.load_confidence_threshold_spinbox.value(),
        "screenshot_directory": DEFAULT_PROFILE["screenshot_directory"],
        "capture_region": DEFAULT_PROFILE["capture_region"],
        "black_screen_detection_region": DEFAULT_PROFILE["black_screen_detection_region"],
    }
    del temp_dialog
    return default_settings


def build_documentation(self):
    # Build tooltip instructions  # fmt: skip
    fps_limit_tooltip = (
        "Limit how fast image analysis runs. Higher values will \n"
        + "provide more accurate load removal at the expense of more \n"
        + "processing power."
    )

    self.fps_limit_label.setToolTip(fps_limit_tooltip)
    self.fps_limit_spinbox.setToolTip(fps_limit_tooltip)

    live_capture_region_tooltip = "Show or hide the live capture region."

    self.live_capture_region_checkbox.setToolTip(live_capture_region_tooltip)

    capture_method_values = CAPTURE_METHODS.values()
    capture_method_tooltip = "\n\n".join(
        f"{method.name} :\n{method.description}" for method in capture_method_values
    )

    self.capture_method_label.setToolTip(capture_method_tooltip)
    self.capture_method_combobox.setToolTip(capture_method_tooltip)

    black_threshold_tooltip = (
        "Tolerance for black screen loads. The lower the value, the\n"
        + "closer the screen needs to be to pure black for ZDCurtain\n"
        + "to recognize the load.\n\n"
        + "Use in conjunction with the Black Screen Entropy Threshold\n"
        + "to recognize black screens regardless of individual hardware\n"
        + "black level."
    )

    self.black_screen_threshold_label.setToolTip(black_threshold_tooltip)
    self.black_screen_threshold_spinbox.setToolTip(black_threshold_tooltip)

    black_entropy_threshold_tooltip = (
        "Uniformity tolerance for black screen loads. The lower the value,\n"
        + "the closer the screen needs to be to the same color for ZDCurtain\n"
        + "to recognize the load.\n\n"
        + "Set this value low to keep dark non-uniform environments, such as\n"
        + "dimly lit rooms and elevators, from being recognized as black\n"
        + "screen loads."
    )

    self.black_screen_entropy_threshold_label.setToolTip(black_entropy_threshold_tooltip)
    self.black_screen_entropy_threshold_spinbox.setToolTip(black_entropy_threshold_tooltip)

    load_confidence_threshold_tooltip = (
        "Threshold in milliseconds for ZDCurtain to recognize an area\n"
        + "load as eligible for load removal. The load must clear the\n"
        + "similarity thresholds below for at least this long in order\n"
        + "for the load to be removed.\n\n"
        + "When the load is removed, ZDCurtain will wait to unpause\n"
        + "the timer in order to cover the amount of time that elapsed\n"
        + "between when the load started and when it was detected."
    )

    self.load_confidence_threshold_label.setToolTip(load_confidence_threshold_tooltip)
    self.load_confidence_threshold_spinbox.setToolTip(load_confidence_threshold_tooltip)

    elevator_similarity_tooltip = (
        "Tolerance for elevator loads. If the similarity value exceeds\n"
        + "this value for longer than the transition load threshold,\n"
        + "an elevator load will be recognized."
    )

    self.elevator_similarity_label.setToolTip(elevator_similarity_tooltip)
    self.elevator_similarity_spinbox.setToolTip(elevator_similarity_tooltip)

    tram_similarity_tooltip = (
        "Tolerance for tram / train loads. If the similarity value exceeds\n"
        + "this value for longer than the transition load threshold,\n"
        + "a tram / train load will be recognized."
    )

    self.tram_similarity_label.setToolTip(tram_similarity_tooltip)
    self.tram_similarity_spinbox.setToolTip(tram_similarity_tooltip)

    teleportal_similarity_tooltip = (
        "Tolerance for teleportal loads. If the similarity value exceeds\n"
        + "this value for longer than the transition load threshold,\n"
        + "a teleportal load will be recognized."
    )

    self.teleportal_similarity_label.setToolTip(teleportal_similarity_tooltip)
    self.teleportal_similarity_spinbox.setToolTip(teleportal_similarity_tooltip)

    egg_similarity_tooltip = (
        "Tolerance for the Itorash capsule load. If the similarity value\n"
        + "exceeds this value for longer than the transition load\n"
        + " threshold, an Itorash capsule load will be recognized."
    )

    self.egg_similarity_label.setToolTip(egg_similarity_tooltip)
    self.egg_similarity_spinbox.setToolTip(egg_similarity_tooltip)

    end_screen_similarity_tooltip = (
        "Tolerance for the screen where Samus runs to her ship.\n"
        + "If the similarity value exceeds this value at any point\n"
        + "in the run, ZDCurtain will stop tracking loads."
    )

    self.end_screen_similarity_label.setToolTip(end_screen_similarity_tooltip)
    self.end_screen_similarity_spinbox.setToolTip(end_screen_similarity_tooltip)

    take_screenshot_hotkey_tooltip = "Takes a screenshot when pressed."

    self.take_screenshot_label.setToolTip(take_screenshot_hotkey_tooltip)
    self.take_screenshot_input.setToolTip(take_screenshot_hotkey_tooltip)
    self.set_take_screenshot_hotkey_button.setToolTip(take_screenshot_hotkey_tooltip)

    start_tracking_automatically_tooltip = (
        "If this box is checked, ZDCurtain will automatically start\n"
        + "tracking loads as soon as a capture source is loaded."
    )

    self.start_tracking_automatically_checkbox.setToolTip(start_tracking_automatically_tooltip)

    clear_previous_session_on_begin_tracking_tooltip = (
        "If this box is checked, ZDCurtain will automatically clear\n"
        + "the previous load removal session when starting a new one."
    )

    self.clear_previous_session_on_begin_tracking_checkbox.setToolTip(
        clear_previous_session_on_begin_tracking_tooltip
    )

    stream_overlay_text_color_tooltip = (
        '"Automatic" changes the text color to either black or white\n'
        + "depending on the background color of the stream overlay window.\n"
        + "If you are using the background as a color key, you should set\n"
        + "this color manually based on the background color of where you\n"
        + "place the stream overlay capture output in your streaming software."
    )

    self.stream_overlay_text_color_label.setToolTip(stream_overlay_text_color_tooltip)
    self.stream_overlay_text_color_combobox.setToolTip(stream_overlay_text_color_tooltip)

    blink_when_tracking_disabled_tooltip = (
        "If this box is checked, the ZDCurtain stream overlay will blink\n"
        + "when there is no active load removal session. This is useful\n"
        + "as a visual aid to know at a glance whether loads are being tracked."
    )

    self.blink_when_tracking_disabled_checkbox.setToolTip(blink_when_tracking_disabled_tooltip)

    stream_overlay_open_on_open_tooltip = (
        "If this box is checked, the ZDCurtain stream overlay will open\n" + "when ZDCurtain is opened."
    )

    self.open_overlay_on_open_checkbox.setToolTip(stream_overlay_open_on_open_tooltip)

    ask_to_export_data_tooltip = (
        "When to prompt for data export:\n\n"
        + "If transition loads were detected: if the session has detected at least\n"
        + "one of the four major transition loads (elevator, tram, teleportal, and\n"
        + "capsule)\n"
        + "After 10 minutes: after 10 minutes of an active load tracking session\n"
        + "Always: always prompt\n"
        + "Never: never prompt"
    )

    self.ask_to_export_data_label.setToolTip(ask_to_export_data_tooltip)
    self.ask_to_export_data_combobox.setToolTip(stream_overlay_text_color_tooltip)

    # endregion
