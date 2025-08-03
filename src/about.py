from typing import TYPE_CHECKING, cast

from gen import about
from PySide6 import QtWidgets

from utils import ZDCURTAIN_VERSION

if TYPE_CHECKING:
    from ZDCurtain import ZDCurtain


class __AboutWidget(QtWidgets.QWidget, about.Ui_AboutZDCurtainWidget):
    """About Window."""

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.created_by_label.setOpenExternalLinks(True)
        self.version_label.setText(f"v. {ZDCURTAIN_VERSION}")
        self.show()


def open_about(zdcurtain: "ZDCurtain"):
    if not zdcurtain.AboutWidget or cast(QtWidgets.QWidget, zdcurtain.AboutWidget).isHidden():
        zdcurtain.AboutWidget = __AboutWidget()
