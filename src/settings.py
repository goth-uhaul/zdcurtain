from functools import partial
from typing import TYPE_CHECKING, Any, cast

from gen import settings as settings_ui
from PySide6 import QtWidgets

import user_profile
from capture_method import (
    CAPTURE_METHODS,
    CameraInfo,
    CaptureMethodEnum,
    change_capture_method,
    get_all_video_capture_devices,
)
from hotkeys import HOTKEYS, set_hotkey
from user_profile import DEFAULT_PROFILE
from utils import ONE_SECOND, fire_and_forget

if TYPE_CHECKING:
    from ZDCurtain import ZDCurtain


class __SettingsWidget(QtWidgets.QWidget, settings_ui.Ui_SettingsWidget):
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
        self.capture_method_combobox.setToolTip(
            "\n\n".join(
                f"{method.name} :\n{method.description}" for method in capture_method_values
            )
        )
        # endregion

        self.__setup_bindings()

        self.show()

    def __update_default_threshold(self, key: str, value: Any):
        match key:
            case "black_threshold":
                self.__set_value("black_threshold", value)
            case "load_confidence_threshold":
                self.__set_value("load_confidence_threshold_ms", value)
            case "similarity_threshold_elevator":
                self.__set_value("similarity_threshold_elevator", value)
            case "similarity_threshold_tram":
                self.__set_value("similarity_threshold_tram", value)
            case "similarity_threshold_teleportal":
                self.__set_value("similarity_threshold_teleportal", value)
            case "similarity_threshold_egg":
                self.__set_value("similarity_threshold_egg", value)

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
                self.get_capture_device_index(
                    self._zdcurtain_ref.settings_dict["capture_device_id"]
                )
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
        if (
            self._zdcurtain_ref.settings_dict["capture_method"]
            == CaptureMethodEnum.VIDEO_CAPTURE_DEVICE
        ):
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

    def __setup_bindings(self):
        # Hotkey initial values and bindings
        for hotkey in HOTKEYS:
            hotkey_input: QtWidgets.QLineEdit = getattr(self, f"{hotkey}_input")
            set_hotkey_hotkey_button: QtWidgets.QPushButton = getattr(
                self,
                f"set_{hotkey}_hotkey_button",
            )
            hotkey_input.setText(self._zdcurtain_ref.settings_dict.get(f"{hotkey}_hotkey", ""))

            set_hotkey_hotkey_button.clicked.connect(
                partial(set_hotkey, self._zdcurtain_ref, hotkey=hotkey)
            )

        # region Set initial values
        # Capture Settings
        self.fps_limit_spinbox.setValue(self._zdcurtain_ref.settings_dict["fps_limit"])
        self.live_capture_region_checkbox.setChecked(
            self._zdcurtain_ref.settings_dict["live_capture_region"]
        )
        self.capture_method_combobox.setCurrentIndex(
            CAPTURE_METHODS.get_index(self._zdcurtain_ref.settings_dict["capture_method"])
        )

        # Image Analysis Settings
        self.black_threshold_spinbox.setValue(self._zdcurtain_ref.settings_dict["black_threshold"])
        self.load_confidence_threshold_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["load_confidence_threshold_ms"]
        )
        self.elevator_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_elevator"]
        )
        self.tram_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_tram"]
        )
        self.teleportal_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_teleportal"]
        )
        self.egg_similarity_spinbox.setValue(
            self._zdcurtain_ref.settings_dict["similarity_threshold_egg"]
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
        self.black_threshold_spinbox.valueChanged.connect(
            lambda: self.__update_default_threshold(
                "black_threshold", self.black_threshold_spinbox.value()
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

        self.start_tracking_automatically_checkbox.stateChanged.connect(
            lambda: self.__set_value(
                "start_tracking_automatically",
                self.start_tracking_automatically_checkbox.isChecked(),
            )
        )
        # endregion


def open_settings(zdcurtain: "ZDCurtain"):
    if not zdcurtain.SettingsWidget or cast(QtWidgets.QWidget, zdcurtain.SettingsWidget).isHidden():
        zdcurtain.SettingsWidget = __SettingsWidget(zdcurtain)


def get_default_settings_from_ui(zdcurtain: "ZDCurtain"):
    temp_dialog = QtWidgets.QWidget()
    default_settings_dialog = settings_ui.Ui_SettingsWidget()
    default_settings_dialog.setupUi(temp_dialog)
    default_settings: user_profile.UserProfileDict = {
        "fps_limit": default_settings_dialog.fps_limit_spinbox.value(),
        "live_capture_region": default_settings_dialog.live_capture_region_checkbox.isChecked(),
        "capture_method": CAPTURE_METHODS.get_method_by_index(
            default_settings_dialog.capture_method_combobox.currentIndex()
        ),
        "capture_device_id": default_settings_dialog.capture_device_combobox.currentIndex(),
        "capture_device_name": "",
        "captured_window_title": "",
        "pause_hotkey": default_settings_dialog.pause_input.text(),
        "start_tracking_automatically": default_settings_dialog.start_tracking_automatically_checkbox.isChecked(),
        "black_threshold": default_settings_dialog.black_threshold_spinbox.value(),
        "similarity_algorithm_elevator": DEFAULT_PROFILE["similarity_algorithm_elevator"],
        "similarity_algorithm_tram": DEFAULT_PROFILE["similarity_algorithm_tram"],
        "similarity_algorithm_teleportal": DEFAULT_PROFILE["similarity_algorithm_teleportal"],
        "similarity_algorithm_egg": DEFAULT_PROFILE["similarity_algorithm_egg"],
        "similarity_algorithm_end_screen": DEFAULT_PROFILE["similarity_algorithm_end_screen"],
        "similarity_use_normalized_capture_elevator": DEFAULT_PROFILE[
            "similarity_use_normalized_capture_elevator"
        ],
        "similarity_use_normalized_capture_tram": DEFAULT_PROFILE[
            "similarity_use_normalized_capture_tram"
        ],
        "similarity_use_normalized_capture_teleportal": DEFAULT_PROFILE[
            "similarity_use_normalized_capture_teleportal"
        ],
        "similarity_use_normalized_capture_egg": DEFAULT_PROFILE[
            "similarity_use_normalized_capture_egg"
        ],
        "similarity_use_normalized_capture_end_screen": DEFAULT_PROFILE[
            "similarity_use_normalized_capture_end_screen"
        ],
        "similarity_threshold_elevator": default_settings_dialog.elevator_similarity_spinbox.value(),
        "similarity_threshold_tram": default_settings_dialog.tram_similarity_spinbox.value(),
        "similarity_threshold_teleportal": default_settings_dialog.teleportal_similarity_spinbox.value(),
        "similarity_threshold_egg": default_settings_dialog.egg_similarity_spinbox.value(),
        "similarity_threshold_end_screen": default_settings_dialog.end_screen_similarity_spinbox.value(),
        "load_confidence_threshold_ms": default_settings_dialog.load_confidence_threshold_spinbox.value(),
        "capture_region": DEFAULT_PROFILE["capture_region"],
    }
    del temp_dialog
    return default_settings
