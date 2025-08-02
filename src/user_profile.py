from typing import TYPE_CHECKING, NoReturn, TypedDict, override
from warnings import deprecated

from capture_method import CAPTURE_METHODS, CaptureMethodEnum, Region, change_capture_method

if TYPE_CHECKING:
    from ZDCurtain import ZDCurtain


class UserProfileDict(TypedDict):
    fps_limit: int
    live_capture_region: bool
    capture_method: str | CaptureMethodEnum
    capture_device_id: int
    capture_device_name: str
    captured_window_title: str
    pause_hotkey: str
    start_tracking_automatically: bool
    black_threshold: float
    similarity_algorithm_elevator: str
    similarity_algorithm_tram: str
    similarity_algorithm_teleportal: str
    similarity_algorithm_egg: str
    similarity_algorithm_end_screen: str
    similarity_use_normalized_capture_elevator: bool
    similarity_use_normalized_capture_tram: bool
    similarity_use_normalized_capture_teleportal: bool
    similarity_use_normalized_capture_egg: bool
    similarity_use_normalized_capture_end_screen: bool
    similarity_threshold_elevator: int
    similarity_threshold_tram: int
    similarity_threshold_teleportal: int
    similarity_threshold_egg: int
    similarity_threshold_end_screen: int
    load_confidence_threshold_ms: int
    capture_region: Region

    @override
    @deprecated("Use `copy.deepcopy` instead")
    def copy() -> NoReturn:
        return super().copy()  # pyright: ignore[reportGeneralTypeIssues]


DEFAULT_PROFILE = UserProfileDict(
    fps_limit=30,
    live_capture_region=True,
    capture_method=CAPTURE_METHODS.get_method_by_index(0),
    capture_device_id=0,
    capture_device_name="",
    captured_window_title="",
    pause_hotkey="",
    start_tracking_automatically=True,
    black_threshold=0.5,
    similarity_algorithm_elevator="histogram",
    similarity_algorithm_tram="l2norm",
    similarity_algorithm_teleportal="l2norm",
    similarity_algorithm_egg="l2norm",
    similarity_algorithm_end_screen="l2norm",
    similarity_use_normalized_capture_elevator=True,
    similarity_use_normalized_capture_tram=False,
    similarity_use_normalized_capture_teleportal=False,
    similarity_use_normalized_capture_egg=False,
    similarity_use_normalized_capture_end_screen=False,
    similarity_threshold_elevator=90,
    similarity_threshold_tram=87,
    similarity_threshold_teleportal=89,
    similarity_threshold_egg=90,
    similarity_threshold_end_screen=98,
    load_confidence_threshold_ms=500,
    capture_region=Region(x=0, y=0, width=1920, height=1080),
)


def load_settings_on_open(zdcurtain: "ZDCurtain"):
    # TODO: replace with https://github.com/Toufool/AutoSplit/blob/main/src/user_profile.py#L205
    change_capture_method(CAPTURE_METHODS.get_method_by_index(0), zdcurtain)
