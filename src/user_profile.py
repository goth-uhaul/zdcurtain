from typing import NoReturn, TypedDict, override
from warnings import deprecated

from capture_method import CAPTURE_METHODS, CaptureMethodEnum, Region


class UserProfileDict(TypedDict):
    fps_limit: int
    live_capture_region: bool
    capture_method: str | CaptureMethodEnum
    capture_device_id: int
    capture_device_name: str
    captured_window_title: str
    capture_region: Region

    @override
    @deprecated("Use `copy.deepcopy` instead")
    def copy() -> NoReturn:
        return super().copy()  # pyright: ignore[reportGeneralTypeIssues]


DEFAULT_PROFILE = UserProfileDict(
    fps_limit=60,
    live_capture_region=True,
    capture_method=CAPTURE_METHODS.get_method_by_index(2),
    capture_device_id=0,
    capture_device_name="",
    captured_window_title="",
    capture_region=Region(x=0, y=0, width=1, height=1),
)
