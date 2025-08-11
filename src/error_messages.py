"""Error messages."""

import os
import signal
import sys
import traceback
from types import TracebackType
from typing import TYPE_CHECKING, NoReturn

from PySide6 import QtCore, QtWidgets

from utils import FROZEN, GITHUB_REPOSITORY

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain


def __exit_program():
    # stop main thread (which is probably blocked reading input) via an interrupt signal
    os.kill(os.getpid(), signal.SIGINT)
    sys.exit(1)


def set_text_message(
    message: str,
    details: str = "",
    kill_button: str = "",
    accept_button: str = "",
):
    message_box = QtWidgets.QMessageBox()
    message_box.setWindowTitle("Error")
    message_box.setTextFormat(QtCore.Qt.TextFormat.RichText)
    message_box.setText(message)
    # Button order is important for default focus
    if accept_button:
        message_box.addButton(accept_button, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    if kill_button:
        force_quit_button = message_box.addButton(
            kill_button,
            QtWidgets.QMessageBox.ButtonRole.ResetRole,
        )
        force_quit_button.clicked.connect(__exit_program)
    if details:
        message_box.setDetailedText(details)
        # Preopen the details
        for button in message_box.buttons():
            if message_box.buttonRole(button) == QtWidgets.QMessageBox.ButtonRole.ActionRole:
                button.click()
                break
    message_box.exec()


def already_open():
    set_text_message(
        "An instance of ZDCurtain is already running." + "<br/>Are you sure you want to open another one?",
        "",
        "Don't open",
        "Ignore",
    )


def invalid_settings():
    set_text_message("Invalid settings file.")


def no_settings_file_on_open():
    set_text_message(
        "No settings file found. "
        + "One can be loaded on open if placed in the same folder as the ZDCurtain executable."
    )


def too_many_settings_files_on_open():
    set_text_message(
        "Too many settings files found. "
        + "Only one can be loaded on open if placed in the same folder as the ZDCurtain executable."
    )


def region():
    set_text_message(
        "No region is selected or the Capture Region window is not open. "
        + "Select a region or load settings while the Capture Region window is open."
    )


def invalid_hotkey(hotkey_name: str):
    set_text_message(f"Invalid hotkey {hotkey_name!r}")


def exception_traceback(exception: BaseException, message: str = ""):
    if not message:
        message = (
            "ZDCurtain encountered an unhandled exception. It'll try to recover, but "
            + "it's not guaranteed to work properly after this."
            + CREATE_NEW_ISSUE_MESSAGE
        )
    set_text_message(
        message,
        "\n".join(traceback.format_exception(None, exception, exception.__traceback__)),
        "Close",
    )


def make_excepthook(zdcurtain: "ZDCurtain"):
    def excepthook(
        exception_type: type[BaseException],
        exception: BaseException,
        _traceback: TracebackType | None,
    ):
        # Catch Keyboard Interrupts for a clean close
        if exception_type is KeyboardInterrupt or isinstance(exception, KeyboardInterrupt):
            sys.exit(0)
        # HACK: Can happen when starting the region selector while capturing with WindowsGraphicsCapture # noqa: E501
        if exception_type is SystemError and str(exception) == (
            "<class 'PySide6.QtGui.QPaintEvent'> returned a result with an error set"
        ):
            return
        # Whithin LiveSplit excepthook needs to use MainWindow's signals to show errors
        zdcurtain.show_error_signal.emit(lambda: exception_traceback(exception))

    return excepthook


def handle_top_level_exceptions(exception: Exception) -> NoReturn:
    message = (
        "ZDCurtain encountered an unrecoverable exception and will probably close. "
        + CREATE_NEW_ISSUE_MESSAGE
    )
    # Print error to console if not running in executable
    if FROZEN:
        exception_traceback(exception, message)
    else:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
    sys.exit(1)


CREATE_NEW_ISSUE_MESSAGE = (
    f"Please create a new Issue at <a href='https://github.com/{GITHUB_REPOSITORY}/issues'>"
    + f"github.com/{GITHUB_REPOSITORY}/issues</a>, describe what happened, "
    + "and copy and paste the entire error message below."
)
