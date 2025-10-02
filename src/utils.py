import asyncio
import logging
import os
import subprocess  # noqa: S404 no new processes are spawned
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from math import sqrt
from pathlib import Path
from platform import version
from threading import Thread
from typing import TYPE_CHECKING, Any, TypeGuard, TypeVar

import cv2
import numpy as np
from cv2.typing import MatLike
from dateutil.tz import tzlocal
from gen.build_vars import ZDCURTAIN_BUILD_NUMBER, ZDCURTAIN_GITHUB_REPOSITORY
from pathvalidate import sanitize_filename
from PySide6 import QtGui
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes
    from _ctypes import COMError  # noqa: PLC2701 # comtypes is untyped
    from enum import IntEnum

    import win32gui
    import win32ui
    from pygrabber.dshow_graph import FilterGraph

    type STARTUPINFO = subprocess.STARTUPINFO
else:
    type STARTUPINFO = None


if TYPE_CHECKING:
    from _typeshed import StrPath

    # Source does not exist, keep this under TYPE_CHECKING
    from _win32typing import PyCDC  # pyright: ignore[reportMissingModuleSource]

T = TypeVar("T")


class ImageShape(IntEnum):
    Y = 0
    X = 1
    Channels = 2


class ColorChannel(IntEnum):
    Blue = 0
    Green = 1
    Red = 2
    Alpha = 3


class LocalTime:
    def __init__(self, timestamp=None):
        timezone_local = tzlocal()
        datetime_local = (
            datetime.fromtimestamp(timestamp, tz=timezone_local)
            if timestamp
            else datetime.now(timezone_local)
        )

        self.timestamp = datetime_local.timestamp()
        self.date = datetime_local.isoformat()
        self.timeZone = timezone_local.tzname(datetime_local)

    def get_datetime(self):
        return datetime.fromisoformat(self.date)

    def to_dict(self):
        return {"date": self.date, "timestamp": self.timestamp, "timezone": self.timeZone}


def resource_path(relative_path: "StrPath"):
    """
    Get absolute path to resource, from the root of the repository.
    Works both frozen and unfrozen.
    """
    base_path = getattr(sys, "_MEIPASS", Path(__file__).parent.parent)
    return os.path.join(base_path, relative_path)


# Note: maybe reorganize capture_method module to have
# different helper modules and a methods submodule
def get_input_device_resolution(index: int) -> tuple[int, int] | None:
    if sys.platform != "win32":
        return (0, 0)
    filter_graph = FilterGraph()
    try:
        filter_graph.add_video_input_device(index)
    # This can happen with virtual cameras throwing errors.
    # For example since OBS 29.1 updated FFMPEG breaking VirtualCam 3.0
    # https://github.com/Toufool/AutoSplit/issues/238
    except COMError:
        return None

    try:
        resolution = filter_graph.get_input_device().get_current_format()
    # For unknown reasons, some devices can raise "ValueError: NULL pointer access".
    # For instance, Oh_DeeR's AVerMedia HD Capture C985 Bus 12
    except ValueError:
        return None
    finally:
        filter_graph.remove_filters()
    return resolution


def get_window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    if sys.platform != "win32":
        raise OSError

    extended_frame_bounds = ctypes.wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd,
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(extended_frame_bounds),
        ctypes.sizeof(extended_frame_bounds),
    )

    window_rect = win32gui.GetWindowRect(hwnd)
    window_left_bounds = extended_frame_bounds.left - window_rect[0]
    window_top_bounds = extended_frame_bounds.top - window_rect[1]
    window_width = extended_frame_bounds.right - extended_frame_bounds.left
    window_height = extended_frame_bounds.bottom - extended_frame_bounds.top
    return window_left_bounds, window_top_bounds, window_width, window_height


def ms_to_ns(ms):
    return ms * 1000000


def ns_to_ms(ns):
    return ns / 1000000


def ms_to_msms(ms):
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)

    return (minutes, seconds, milliseconds)


def decimal(value: float):
    # Using ljust instead of :2f because of python float rounding errors
    return f"{int(value * 100) / 100}".ljust(4, "0")


def is_digit(value: str | int | None):
    """Checks if `value` is a single-digit string from 0-9."""
    if value is None:
        return False
    try:
        return 0 <= int(value) <= 9
    except (ValueError, TypeError):
        return False


def is_valid_image(image: MatLike | None) -> TypeGuard[MatLike]:
    return image is not None and bool(image.size)


def is_valid_hwnd(hwnd: int):
    """
    Validate the hwnd points to a valid window
    and not the desktop or whatever window obtained with `""`.
    """
    if not hwnd:
        return False
    if sys.platform == "win32":
        return bool(win32gui.IsWindow(hwnd) and win32gui.GetWindowText(hwnd))
    return True


def first(iterable: Iterable[T]) -> T:
    """@return: The first element of a collection. Dictionaries will return the first key."""
    return next(iter(iterable))


def try_delete_dc(dc: "PyCDC"):
    if sys.platform != "win32":
        raise OSError
    try:
        dc.DeleteDC()
    except win32ui.error:
        pass


def get_or_create_eventloop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return asyncio.get_event_loop()


def fire_and_forget(func: Callable[..., Any]):
    """
    Runs synchronous function asynchronously without waiting for a response.

    Uses threads on Windows because
    ~~`RuntimeError: There is no current event loop in thread 'MainThread'`~~
    maybe asyncio has issues. Unsure. See alpha.5 and https://github.com/Avasam/AutoSplit/issues/36

    Uses asyncio on Linux because of a `Segmentation fault (core dumped)`
    """

    def wrapped(*args: Any, **kwargs: Any):
        # win32
        thread = Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
        return thread
        # macos stub
        # linux stub

    return wrapped


def list_processes():
    if sys.platform == "win32":
        return [
            # The first row is the process name
            line.split()[0]
            for line in subprocess.run(
                "C:/Windows/System32/tasklist.exe", check=False, text=True, stdout=subprocess.PIPE
            ).stdout.splitlines()[3:]  # Skip the table header lines
            if line
        ]

    return subprocess.check_output(
        ("ps", "-eo", "comm"),
        text=True,
    ).splitlines()[1:]  # Skip the header line


def imread(filename: str, flags: int = cv2.IMREAD_COLOR_RGB):
    return cv2.imdecode(np.fromfile(filename, dtype=np.uint8), flags)


def imwrite(filename: str, img: MatLike, params: Sequence[int] = ()):
    success, encoded_img = cv2.imencode(os.path.splitext(filename)[1], img, params)
    if not success:
        raise OSError(f"cv2 could not write to path {filename}")
    encoded_img.tofile(filename)


def get_widget_position(widget: QWidget) -> tuple[int, int]:
    geometry = widget.geometry()
    return geometry.x(), geometry.y()


def move_widget(widget: QWidget, x: int, y: int):
    widget.move(x, y)


def get_version():
    return ZDCURTAIN_VERSION


def get_sanitized_filename(unsanitary_filename: str):
    return sanitize_filename(unsanitary_filename)


def is_window_focused(name):
    focused_window = QApplication.activeWindow()

    if focused_window is not None:
        return focused_window.objectName() == name

    return False


def create_icon(qlabel: QLabel, image: MatLike | None):
    if not is_valid_image(image):
        # Clear current pixmap if no image. But don't clear text
        if not qlabel.text():
            qlabel.clear()
    else:
        height, width, channels = image.shape

        if channels == BGRA_CHANNEL_COUNT:
            image_format = QtGui.QImage.Format.Format_RGBA8888
        else:
            image_format = QtGui.QImage.Format.Format_BGR888

        qimage = QtGui.QImage(image.data, width, height, width * channels, image_format)
        qlabel.setPixmap(QtGui.QPixmap(qimage))


def debug_log(message):
    logger = logging.getLogger(__name__)
    logger.debug(message)


def create_yes_no_dialog(
    title: str,
    text: str,
    yes_method: Callable | None,
    no_method: Callable | None,
    *,
    default_to_no: bool = True,
):
    dialog = QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(text)
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

    if default_to_no:
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
    else:
        dialog.setDefaultButton(QMessageBox.StandardButton.Yes)

    decision = dialog.exec()

    if decision == QMessageBox.StandardButton.Yes and yes_method is not None:
        yes_method()
    elif decision == QMessageBox.StandardButton.No and no_method is not None:
        no_method()


def rgba_to_bgra(rgba):
    r, g, b, a = rgba
    return (b, g, r, a)


def bgr_to_rgb(bgra):
    b, g, r, a = bgra
    return (r, g, b, a)


def to_whole_css_rgb(rgb):
    r, g, b = rgb
    return f"rgb({round(r)},{round(g)},{round(b)})"  # needs to adhere to CSS 2.1


def use_black_or_white_text(rgb):
    cutoff = 132  # values between 128 and 145 will work
    return (0, 0, 0) if weighted_distance_in_3d(rgb) > cutoff else (255, 255, 255)


def weighted_distance_in_3d(rgb):
    """W3C-compliant formula to determine whether to use black or white text on a solid color background."""
    r, g, b = rgb
    return sqrt(pow(r, 2) * 0.241 + pow(g, 2) * 0.691 + pow(b, 2) * 0.068)


def check_if_image_has_transparency(image: MatLike):
    # Check if there's a transparency channel (4th channel)
    # and if at least one pixel is transparent (< 255)
    if image.shape[ImageShape.Channels] != BGRA_CHANNEL_COUNT:
        return False
    mean: float = image[:, :, ColorChannel.Alpha].mean()
    if mean == 0:
        # Non-transparent images code path is usually faster and simpler, so let's return that
        return False
        # TODO: error message if all pixels are transparent
        # (the image appears as all black in windows,
        # so it's not obvious for the user what they did wrong)

    return mean != MAXBYTE


def flatten_dict(d, parent_key="", sep="_"):
    """Convert nested dictionary to flat structure."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


DWMWA_EXTENDED_FRAME_BOUNDS = 9
MAXBYTE = 255
ONE_SECOND = 1000
"""1000 milliseconds in 1 second"""
ONE_DREAD_FRAME_MS = 1 / 60 * ONE_SECOND
"""16.67... milliseconds in one frame of Metroid Dread"""
DREAD_MAX_DELTA_MS = ONE_DREAD_FRAME_MS * 6
"""Dread Delta Time Cap"""
BGR_CHANNEL_COUNT = 3
"""How many channels in a BGR image"""
BGRA_CHANNEL_COUNT = 4
"""How many channels in a BGRA image"""
INVALID_COLOR = (-1, -1, -1)
"""NoneType is not serializable in tomli-w"""
BLACKOUT_SIDE_LENGTH = 8
"""Length of the bottom corner blackout squares"""

# Environment specifics
WINDOWS_BUILD_NUMBER = int(version().split(".")[-1]) if sys.platform == "win32" else -1
FIRST_WIN_11_BUILD = 22000
WGC_MIN_BUILD = 17134
FROZEN = hasattr(sys, "frozen")
working_directory = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))

# Shared strings
with open(resource_path("pyproject.toml"), mode="rb") as pyproject:
    # Check `excludeBuildNumber` during workflow dispatch build generate a clean version number
    ZDCURTAIN_VERSION: str = tomllib.load(pyproject)["project"]["version"] + (
        f"-{ZDCURTAIN_BUILD_NUMBER}" if ZDCURTAIN_BUILD_NUMBER else ""
    )

GITHUB_REPOSITORY = ZDCURTAIN_GITHUB_REPOSITORY
