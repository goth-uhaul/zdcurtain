import asyncio
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from functools import partial
from pathlib import Path
from platform import version
from threading import Thread
from typing import TYPE_CHECKING, Any, TypeGuard, TypeVar

import cv2
import numpy as np
from cv2.typing import MatLike
from gen.build_vars import ZDCURTAIN_BUILD_NUMBER, ZDCURTAIN_GITHUB_REPOSITORY

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


def try_input_device_access():
    """Same as `make_uinput` in `keyboard/_nixcommon.py`."""
    if sys.platform != "linux":
        return


def fire_and_forget(func: Callable[..., Any]):
    """
    Runs synchronous function asynchronously without waiting for a response.

    Uses threads on Windows because
    ~~`RuntimeError: There is no current event loop in thread 'MainThread'`~~
    maybe asyncio has issues. Unsure. See alpha.5 and https://github.com/Avasam/AutoSplit/issues/36

    Uses asyncio on Linux because of a `Segmentation fault (core dumped)`
    """

    def wrapped(*args: Any, **kwargs: Any):
        if sys.platform == "win32":
            thread = Thread(target=func, args=args, kwargs=kwargs)
            thread.start()
            return thread
        return get_or_create_eventloop().run_in_executor(None, partial(func, *args, **kwargs))

    return wrapped


def list_processes():
    if sys.platform == "win32":
        return [
            # The first row is the process name
            line.split()[0]
            for line in subprocess.check_output(
                "C:/Windows/System32/tasklist.exe", text=True
            ).splitlines()[3:]  # Skip the table header lines
            if line
        ]

    return subprocess.check_output(
        ("ps", "-eo", "comm"),
        text=True,
    ).splitlines()[1:]  # Skip the header line


def imread(filename: str, flags: int = cv2.IMREAD_COLOR):
    return cv2.imdecode(np.fromfile(filename, dtype=np.uint8), flags)


def imwrite(filename: str, img: MatLike, params: Sequence[int] = ()):
    success, encoded_img = cv2.imencode(os.path.splitext(filename)[1], img, params)
    if not success:
        raise OSError(f"cv2 could not write to path {filename}")
    encoded_img.tofile(filename)


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


DWMWA_EXTENDED_FRAME_BOUNDS = 9
MAXBYTE = 255
ONE_SECOND = 1000
"""1000 milliseconds in 1 second"""
ONE_DREAD_FRAME = 1 / 60
"""16.67... milliseconds in one frame of Metroid Dread"""
BGR_CHANNEL_COUNT = 3
"""How many channels in a BGR image"""
BGRA_CHANNEL_COUNT = 4
"""How many channels in a BGRA image"""

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
