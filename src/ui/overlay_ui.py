from typing import TYPE_CHECKING, cast, override

from gen import overlay as overlay_ui
from PySide6 import QtCore, QtWidgets
from vcolorpicker import ColorPicker

from utils import INVALID_COLOR, create_icon, to_whole_css_rgb, use_black_or_white_text

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain


class __OverlayWidget(QtWidgets.QWidget, overlay_ui.Ui_OverlayWidget):
    """Quick-look at load status."""

    def __init__(self, zdcurtain: "ZDCurtain"):
        super().__init__()
        self.setupUi(self)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self._zdcurtain_ref = zdcurtain
        self.__bind_icons()
        self.__change_icon()
        self.__set_initial_color()
        self._zdcurtain_ref.update_load_time_removed(self.loads_removed_time_label)

        self._zdcurtain_ref.after_changing_icon_signal.connect(self.__change_icon)
        self._zdcurtain_ref.after_load_time_removed_changed_signal.connect(
            lambda: self._zdcurtain_ref.update_load_time_removed(self.loads_removed_time_label)
        )

        self.show()

    def __bind_icons(self):
        create_icon(self.black_screen_load_icon, self._zdcurtain_ref.loading_icon_grayed)
        create_icon(self.elevator_tracking_icon, self._zdcurtain_ref.elevator_icon)
        create_icon(self.tram_tracking_icon, self._zdcurtain_ref.tram_icon)
        create_icon(self.teleportal_tracking_icon, self._zdcurtain_ref.teleportal_icon)
        create_icon(self.egg_tracking_icon, self._zdcurtain_ref.capsule_icon)

    def __set_initial_color(self):
        initial_color: tuple

        if self._zdcurtain_ref.settings_dict["overlay_color_key_rgb"] is INVALID_COLOR:
            initial_color = (
                self.palette().window().color().red(),
                self.palette().window().color().green(),
                self.palette().window().color().blue(),
            )
        else:
            initial_color = tuple(self._zdcurtain_ref.settings_dict["overlay_color_key_rgb"])

        self.__set_text_color(initial_color)

        self.__set_window_color(initial_color)

    def __set_window_color(self, color):
        r, g, b = color
        self.setStyleSheet("#OverlayWidget { background-color: " + to_whole_css_rgb((r, g, b)) + "; }")

    def __set_text_color(self, color):
        text_color: tuple

        match self._zdcurtain_ref.settings_dict["stream_overlay_text_color"]:
            case "Automatic":
                text_color = use_black_or_white_text(color)
            case "Black":
                text_color = (0, 0, 0)
            case "White":
                text_color = (255, 255, 255)
            case _:
                text_color = (0, 255, 0)

        r, g, b = text_color
        self.loads_removed_time_label.setStyleSheet("color: " + to_whole_css_rgb((r, g, b)) + ";")

    @override
    def mousePressEvent(self, event):
        color: tuple
        last_color: tuple = tuple(self._zdcurtain_ref.settings_dict["overlay_color_key_rgb"])

        color_picker = ColorPicker(alwaysOnTop=True)

        color = color_picker.getColor(last_color) if last_color != INVALID_COLOR else color_picker.getColor()

        self._zdcurtain_ref.settings_dict["overlay_color_key_rgb"] = color
        self.__set_window_color(color)
        self.__set_text_color(color)

    def __change_icon(self):
        match self._zdcurtain_ref.active_load_type:
            case "black":
                create_icon(self.black_screen_load_icon, self._zdcurtain_ref.loading_icon)
            case "elevator":
                create_icon(self.elevator_tracking_icon, self._zdcurtain_ref.loading_icon)
            case "tram":
                create_icon(self.tram_tracking_icon, self._zdcurtain_ref.loading_icon)
            case "teleportal":
                create_icon(self.teleportal_tracking_icon, self._zdcurtain_ref.loading_icon)
            case "egg":
                create_icon(self.egg_tracking_icon, self._zdcurtain_ref.loading_icon)
            case "spinner":
                create_icon(self.black_screen_load_icon, self._zdcurtain_ref.loading_icon)
            case _:
                self.__bind_icons()


def open_overlay(zdcurtain: "ZDCurtain"):
    if not zdcurtain.OverlayWidget or cast(QtWidgets.QWidget, zdcurtain.OverlayWidget).isHidden():
        zdcurtain.OverlayWidget = __OverlayWidget(zdcurtain)
