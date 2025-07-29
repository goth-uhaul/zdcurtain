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
    black_threshold: int
    similarity_algorithm_elevator: str
    similarity_algorithm_tram: str
    similarity_algorithm_teleportal: str
    similarity_algorithm_egg: str
    similarity_threshold_elevator: int
    similarity_threshold_tram: int
    similarity_threshold_teleportal: int
    similarity_threshold_egg: int
    pause_hotkey: str

    @override
    @deprecated("Use `copy.deepcopy` instead")
    def copy() -> NoReturn:
        return super().copy()  # pyright: ignore[reportGeneralTypeIssues]


DEFAULT_PROFILE = UserProfileDict(
    fps_limit=30,
    live_capture_region=True,
    capture_method=CAPTURE_METHODS.get_method_by_index(2),
    capture_device_id=0,
    capture_device_name="",
    captured_window_title="",
    capture_region=Region(x=0, y=0, width=1, height=1),
    black_threshold=1,
    similarity_algorithm_elevator="histogram",
    similarity_algorithm_tram="l2norm",
    similarity_algorithm_teleportal="l2norm",
    similarity_algorithm_egg="histogram",
    similarity_threshold_elevator=90,
    similarity_threshold_tram=87,
    similarity_threshold_teleportal=89,
    similarity_threshold_egg=90,
    pause_hotkey="",
)
