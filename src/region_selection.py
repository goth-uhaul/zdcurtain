import sys
from math import ceil
from typing import TYPE_CHECKING, override

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

import error_messages
from capture_method import Region
from utils import get_window_bounds, is_valid_hwnd

if sys.platform == "win32":
    import win32api
    import win32gui
    from win32con import SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain


def select_window(zdcurtain: "ZDCurtain"):
    # Create a screen selector widget
    selector = SelectWindowWidget()

    # Need to wait until the user has selected a region using the widget before moving on with
    # selecting the window settings
    while not selector.isHidden():
        QTest.qWait(1)
    selection = selector.selection
    del selector
    if selection is None:
        return  # No selection done

    window = get_top_window_at(selection["x"], selection["y"])
    if not window:
        error_messages.region()
        return
    hwnd = window.getHandle()
    window_text = window.title
    if not is_valid_hwnd(hwnd) or not window_text:
        error_messages.region()
        return

    zdcurtain.hwnd = hwnd
    zdcurtain.settings_dict["captured_window_title"] = window_text
    zdcurtain.capture_method.reinitialize()

    if sys.platform == "win32":
        # Exlude the borders and titlebar from the window selection. To only get the client area.
        _, __, window_width, window_height = get_window_bounds(hwnd)
        _, __, client_width, client_height = win32gui.GetClientRect(hwnd)
        border_width = ceil((window_width - client_width) / 2)
        titlebar_with_border_height = window_height - client_height - border_width
    else:
        data = window._xWin.get_geometry()._data  # pyright:ignore[reportPrivateUsage] # noqa: SLF001
        client_height = data["height"]
        client_width = data["width"]
        border_width = data["border_width"]
        titlebar_with_border_height = border_width

    __set_region_values(
        zdcurtain,
        x=border_width,
        y=titlebar_with_border_height,
        width=client_width,
        height=client_height - border_width * 2,
    )

    zdcurtain.capture_state_changed_signal.emit()


def __set_region_values(zdcurtain: "ZDCurtain", x: int, y: int, width: int, height: int):
    zdcurtain.settings_dict["capture_region"]["x"] = x
    zdcurtain.settings_dict["capture_region"]["y"] = y
    zdcurtain.settings_dict["capture_region"]["width"] = width
    zdcurtain.settings_dict["capture_region"]["height"] = height


class BaseSelectWidget(QtWidgets.QWidget):
    selection: Region | None = None

    def __init__(self):
        super().__init__()
        # We need to pull the monitor information to correctly draw
        # the geometry covering all portions of the user's screen.
        # These parameters create the bounding box with left, top, width, and height
        if sys.platform == "win32":
            x = win32api.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = win32api.GetSystemMetrics(SM_YVIRTUALSCREEN)
            width = win32api.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            height = win32api.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        self.setGeometry(x, y, width, height)
        self.setFixedSize(width, height)  # Prevent move/resizing on Linux
        self.setWindowTitle(type(self).__name__)
        self.setWindowOpacity(0.5)
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
        self.show()

    @override
    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.close()


class SelectWindowWidget(BaseSelectWidget):
    """Widget to select a window and obtain its bounds."""

    @override
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        x = int(event.position().x()) + self.geometry().x()
        y = int(event.position().y()) + self.geometry().y()
        self.selection = Region(x=x, y=y, width=0, height=0)
        self.close()
