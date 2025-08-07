import os
import tomllib
from copy import deepcopy
from typing import TYPE_CHECKING, NoReturn, TypedDict, cast, override
from warnings import deprecated

import tomli_w
from PySide6 import QtWidgets

import error_messages
import settings
from capture_method import CAPTURE_METHODS, CaptureMethodEnum, Region, change_capture_method
from hotkeys import HOTKEYS, Hotkey, remove_all_hotkeys, set_hotkey
from utils import working_directory

if TYPE_CHECKING:
    from ZDCurtain import ZDCurtain


class UserProfileDict(TypedDict):
    fps_limit: int
    live_capture_region: bool
    capture_method: str | CaptureMethodEnum
    capture_device_id: int
    capture_device_name: str
    captured_window_title: str
    pause_hotkey: str
    start_tracking_automatically: bool
    black_threshold: float
    similarity_algorithm_elevator: str
    similarity_algorithm_tram: str
    similarity_algorithm_teleportal: str
    similarity_algorithm_egg: str
    similarity_algorithm_end_screen: str
    similarity_use_normalized_capture_elevator: bool
    similarity_use_normalized_capture_tram: bool
    similarity_use_normalized_capture_teleportal: bool
    similarity_use_normalized_capture_egg: bool
    similarity_use_normalized_capture_end_screen: bool
    similarity_threshold_elevator: int
    similarity_threshold_tram: int
    similarity_threshold_teleportal: int
    similarity_threshold_egg: int
    similarity_threshold_end_screen: int
    load_cooldown_elevator_ms: int
    load_cooldown_tram_ms: int
    load_cooldown_teleportal_ms: int
    load_cooldown_egg_ms: int
    load_confidence_threshold_ms: int
    capture_region: Region

    @override
    @deprecated("Use `copy.deepcopy` instead")
    def copy() -> NoReturn:
        return super().copy()  # pyright: ignore[reportGeneralTypeIssues]


DEFAULT_PROFILE = UserProfileDict(
    fps_limit=30,
    live_capture_region=True,
    capture_method=CAPTURE_METHODS.get_method_by_index(0),
    capture_device_id=0,
    capture_device_name="",
    captured_window_title="",
    pause_hotkey="",
    start_tracking_automatically=True,
    black_threshold=0.5,
    similarity_algorithm_elevator="histogram",
    similarity_algorithm_tram="l2norm",
    similarity_algorithm_teleportal="l2norm",
    similarity_algorithm_egg="l2norm",
    similarity_algorithm_end_screen="l2norm",
    similarity_use_normalized_capture_elevator=True,
    similarity_use_normalized_capture_tram=False,
    similarity_use_normalized_capture_teleportal=False,
    similarity_use_normalized_capture_egg=False,
    similarity_use_normalized_capture_end_screen=False,
    similarity_threshold_elevator=90,
    similarity_threshold_tram=87,
    similarity_threshold_teleportal=89,
    similarity_threshold_egg=90,
    similarity_threshold_end_screen=98,
    load_cooldown_elevator_ms=0,
    load_cooldown_tram_ms=0,
    load_cooldown_teleportal_ms=0,
    load_cooldown_egg_ms=3000,
    load_confidence_threshold_ms=500,
    capture_region=Region(x=0, y=0, width=1, height=1),
)


def have_settings_changed(zdcurtain: "ZDCurtain"):
    return zdcurtain.settings_dict != zdcurtain.last_saved_settings


def save_settings(zdcurtain: "ZDCurtain"):
    """@return: The save settings filepath. Or None if "Save Settings As" is cancelled."""
    return (
        __save_settings_to_file(zdcurtain, zdcurtain.last_successfully_loaded_settings_file_path)
        if zdcurtain.last_successfully_loaded_settings_file_path
        else save_settings_as(zdcurtain)
    )


def save_settings_as(zdcurtain: "ZDCurtain"):
    """@return: The save settings filepath selected. Empty if cancelled."""
    # User picks save destination
    save_settings_file_path = QtWidgets.QFileDialog.getSaveFileName(
        zdcurtain,
        "Save Settings As",
        zdcurtain.last_successfully_loaded_settings_file_path
        or os.path.join(working_directory, "settings.toml"),
        "TOML (*.toml)",
    )[0]

    # If user cancels save destination window, don't save settings
    if not save_settings_file_path:
        return ""

    return __save_settings_to_file(zdcurtain, save_settings_file_path)


def __save_settings_to_file(zdcurtain: "ZDCurtain", save_settings_file_path: str):
    # Save settings to a .toml file
    with open(save_settings_file_path, "wb") as file:
        tomli_w.dump(zdcurtain.settings_dict, file)
    zdcurtain.last_saved_settings = deepcopy(zdcurtain.settings_dict)
    zdcurtain.last_successfully_loaded_settings_file_path = save_settings_file_path
    return save_settings_file_path


def __load_settings_from_file(zdcurtain: "ZDCurtain", load_settings_file_path: str):
    # Allow seamlessly reloading the entire settings widget
    settings_widget_was_open = False
    settings_widget = cast(QtWidgets.QWidget | None, zdcurtain.SettingsWidget)
    if settings_widget:
        settings_widget_was_open = settings_widget.isVisible()
        settings_widget.close()

    try:
        with open(load_settings_file_path, mode="rb") as file:
            # Casting here just so we can build an actual UserProfileDict once we're done validating
            # Fallback to default settings if some are missing from the file.
            # This happens when new settings are added.
            loaded_settings = DEFAULT_PROFILE | cast(UserProfileDict, tomllib.load(file))

        # TODO: Data Validation / fallbacks ?
        zdcurtain.settings_dict = UserProfileDict(**loaded_settings)
        zdcurtain.last_saved_settings = deepcopy(zdcurtain.settings_dict)

        if zdcurtain.settings_dict["start_tracking_automatically"]:
            zdcurtain.begin_tracking()

    except (FileNotFoundError, MemoryError, TypeError, tomllib.TOMLDecodeError):
        zdcurtain.show_error_signal.emit(error_messages.invalid_settings)
        return False

    remove_all_hotkeys()
    for hotkey, hotkey_name in ((hotkey, f"{hotkey}_hotkey") for hotkey in HOTKEYS):
        hotkey_value = zdcurtain.settings_dict.get(hotkey_name)
        if hotkey_value:
            # cast caused by a regression in pyright 1.1.365
            set_hotkey(zdcurtain, cast(Hotkey, hotkey), hotkey_value)

    change_capture_method(
        cast(CaptureMethodEnum, zdcurtain.settings_dict["capture_method"]),
        zdcurtain,
    )

    if zdcurtain.settings_dict["capture_method"] != CaptureMethodEnum.VIDEO_CAPTURE_DEVICE:
        zdcurtain.capture_method.recover_window(zdcurtain.settings_dict["captured_window_title"])
    if not zdcurtain.capture_method.check_selected_region_exists():
        zdcurtain.live_image.setText(
            "Reload settings after opening"
            + f"\n{zdcurtain.settings_dict['captured_window_title']!r}"
            + "\nto automatically load Capture Region"
        )

    if settings_widget_was_open:
        settings.open_settings(zdcurtain)

    return True


def load_settings(zdcurtain: "ZDCurtain", from_path: str = ""):
    load_settings_file_path = (
        from_path
        or QtWidgets.QFileDialog.getOpenFileName(
            zdcurtain,
            "Load Profile",
            os.path.join(working_directory, "settings.toml"),
            "TOML (*.toml)",
        )[0]
    )
    if not (
        load_settings_file_path  # fmt: skip
        and __load_settings_from_file(zdcurtain, load_settings_file_path)
    ):
        return

    zdcurtain.last_successfully_loaded_settings_file_path = load_settings_file_path


def load_settings_on_open(zdcurtain: "ZDCurtain"):
    settings_files = [
        file  # fmt: skip
        for file in os.listdir(working_directory)
        if file.endswith(".toml")
    ]

    # Find all .tomls in ZDCurtain folder, error if there is not exactly 1
    error = None
    if len(settings_files) < 1:
        error = error_messages.no_settings_file_on_open
    elif len(settings_files) > 1:
        error = error_messages.too_many_settings_files_on_open
    if error:
        change_capture_method(CAPTURE_METHODS.get_method_by_index(0), zdcurtain)
        error()
        return

    load_settings(zdcurtain, os.path.join(working_directory, settings_files[0]))
