#!/usr/bin/python3
import sys

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

import signal

from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QApplication

import error_messages
from ui.zdcurtain_ui import ZDCurtain
from utils import FROZEN, list_processes


def main():
    # Best to call setStyle before the QApplication constructor
    # https://doc.qt.io/qt-6/qapplication.html#setStyle-1
    QApplication.setStyle("fusion")
    # Call to QApplication outside the try-except so we can show error messages
    app = QApplication(sys.argv)
    try:
        app.setWindowIcon(QtGui.QIcon(":/resources/icon.ico"))

        if is_already_open():
            error_messages.already_open()

        ZDCurtain()

        if not FROZEN:
            # Kickoff the event loop every so often so we can handle KeyboardInterrupt (^C)
            timer = QtCore.QTimer()
            timer.timeout.connect(lambda: None)
            timer.start(500)

        exit_code = app.exec()
    except Exception as exception:  # noqa: BLE001 # We really want to catch everything here
        error_messages.handle_top_level_exceptions(exception)

    # Catch Keyboard Interrupts for a clean close
    signal.signal(signal.SIGINT, lambda code, _: sys.exit(code))

    sys.exit(exit_code)


def is_already_open():
    # When running directly in Python, any ZDCurtain process means it's already open
    # When bundled, we must ignore itself and the splash screen
    max_processes = 3 if FROZEN else 1
    process_name = "ZDCurtain.exe" if sys.platform == "win32" else "ZDCurtain.elf"
    return list_processes().count(process_name) >= max_processes


if __name__ == "__main__":
    main()
