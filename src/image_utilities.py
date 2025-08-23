#!/usr/bin/python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# !/usr/bin/python3
import cv2

from utils import BGR_CHANNEL_COUNT, FROZEN, ImageShape, imread, imwrite, resource_path
from ZDImage import ZDImage

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain

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


from cv2.typing import MatLike
from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QLabel

from utils import BGRA_CHANNEL_COUNT, is_valid_image

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


def load_images(_zdcurtain_ref):
    _zdcurtain_ref.elevator_icon = read_image("res/icons/elevator_icon.png")
    _zdcurtain_ref.tram_icon = read_image("res/icons/tram_icon.png")
    _zdcurtain_ref.teleportal_icon = read_image("res/icons/teleportal_icon.png")
    _zdcurtain_ref.capsule_icon = read_image("res/icons/capsule_icon.png")
    _zdcurtain_ref.gunship_icon = read_image("res/icons/gunship_icon_small.png")
    _zdcurtain_ref.elevator_icon_tentative = read_image("res/icons/elevator_tentative_icon.png")
    _zdcurtain_ref.tram_icon_tentative = read_image("res/icons/tram_tentative_icon.png")
    _zdcurtain_ref.teleportal_icon_tentative = read_image("res/icons/teleportal_tentative_icon.png")
    _zdcurtain_ref.capsule_icon_tentative = read_image("res/icons/capsule_tentative_icon.png")
    _zdcurtain_ref.gunship_icon = read_image("res/icons/gunship_icon_small.png")
    _zdcurtain_ref.loading_icon = read_image("res/icons/loading_icon.png")
    _zdcurtain_ref.loading_icon_grayed = read_image("res/icons/loading_icon_grayed.png")


def load_comparison_images(_zdcurtain_ref):
    file_path = Path.cwd() / "comparison" if FROZEN else Path.cwd() / "res" / "comparison"
    _zdcurtain_ref.comparison_capsule_gravity = read_and_format_zdimage(
        f"{file_path}{os.sep}capsule_gravity.png"
    )
    _zdcurtain_ref.comparison_capsule_power = read_and_format_zdimage(f"{file_path}{os.sep}capsule_power.png")
    _zdcurtain_ref.comparison_capsule_varia = read_and_format_zdimage(f"{file_path}{os.sep}capsule_varia.png")
    _zdcurtain_ref.comparison_elevator_gravity = read_and_format_zdimage(
        f"{file_path}{os.sep}elevator_gravity.png"
    )
    _zdcurtain_ref.comparison_elevator_power = read_and_format_zdimage(
        f"{file_path}{os.sep}elevator_power.png"
    )
    _zdcurtain_ref.comparison_elevator_varia = read_and_format_zdimage(
        f"{file_path}{os.sep}elevator_varia.png"
    )
    _zdcurtain_ref.comparison_teleport_gravity = read_and_format_zdimage(
        f"{file_path}{os.sep}teleport_gravity.png"
    )
    _zdcurtain_ref.comparison_teleport_power = read_and_format_zdimage(
        f"{file_path}{os.sep}teleport_power.png"
    )
    _zdcurtain_ref.comparison_teleport_varia = read_and_format_zdimage(
        f"{file_path}{os.sep}teleport_varia.png"
    )
    _zdcurtain_ref.comparison_train_left_gravity = read_and_format_zdimage(
        f"{file_path}{os.sep}train_left_gravity.png"
    )
    _zdcurtain_ref.comparison_train_left_power = read_and_format_zdimage(
        f"{file_path}{os.sep}train_left_power.png"
    )
    _zdcurtain_ref.comparison_train_left_varia = read_and_format_zdimage(
        f"{file_path}{os.sep}train_left_varia.png"
    )
    _zdcurtain_ref.comparison_train_right_gravity = read_and_format_zdimage(
        f"{file_path}{os.sep}train_right_gravity.png"
    )
    _zdcurtain_ref.comparison_train_right_power = read_and_format_zdimage(
        f"{file_path}{os.sep}train_right_power.png"
    )
    _zdcurtain_ref.comparison_train_right_varia = read_and_format_zdimage(
        f"{file_path}{os.sep}train_right_varia.png"
    )
    _zdcurtain_ref.comparison_end_screen = read_and_format_zdimage(f"{file_path}{os.sep}end_screen.png")
    _zdcurtain_ref.comparison_game_over_screen = read_and_format_zdimage(
        f"{file_path}{os.sep}game_over_mask.png"
    )
    _zdcurtain_ref.comparison_loading_widget = read_and_format_zdimage(f"{file_path}{os.sep}loading.png")


def read_image(filename):
    image = imread(resource_path(filename), cv2.IMREAD_UNCHANGED)

    if image.shape[ImageShape.Channels] == BGR_CHANNEL_COUNT:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGRA)
    else:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA)

    return image


def read_and_format_zdimage(filename):
    return ZDImage(filename)


def take_screenshot(directory, filename, capture):
    imwrite(
        f"{directory}/{filename}.png",
        capture,
    )


def get_loading_icon(_zdcurtain_ref: ZDCurtain, *, load_type, get_potential_load_icon):
    match load_type:
        case "elevator":
            return (
                _zdcurtain_ref.elevator_icon_tentative
                if get_potential_load_icon
                else _zdcurtain_ref.elevator_icon
            )
        case "tram":
            return _zdcurtain_ref.tram_icon_tentative if get_potential_load_icon else _zdcurtain_ref.tram_icon
        case "teleportal":
            return (
                _zdcurtain_ref.teleportal_icon_tentative
                if get_potential_load_icon
                else _zdcurtain_ref.teleportal_icon
            )
        case "egg":
            return (
                _zdcurtain_ref.capsule_icon_tentative
                if get_potential_load_icon
                else _zdcurtain_ref.capsule_icon
            )


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
