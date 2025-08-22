#!/usr/bin/python3
from time import perf_counter_ns
from typing import TYPE_CHECKING

import error_messages
from frame_analysis import calculate_frame_luminance, get_comparison_method_by_name
from utils import DREAD_MAX_DELTA_MS, LocalTime, create_icon, debug_log, is_valid_image, ms_to_ns, ns_to_ms

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain

GAMEOVER_FEATURE_SIMILARITY_THRESHOLD = 50
LOADING_WIDGET_SIMILARITY_THRESHOLD = 10


def perform_load_removal_logic(_zdcurtain_ref: "ZDCurtain"):
    if is_end_screen(_zdcurtain_ref, _zdcurtain_ref.similarity_to_end_screen, 98):
        # stop tracking
        _zdcurtain_ref.end_tracking()

    if not _zdcurtain_ref.is_tracking or _zdcurtain_ref.load_removal_session is None:
        return

    __check_load_cooldown(_zdcurtain_ref)
    __check_black_screen_markers(_zdcurtain_ref)
    __check_load_blocking_logic(_zdcurtain_ref)
    __check_for_active_loads(_zdcurtain_ref)
    __check_if_load_ending(_zdcurtain_ref)


def is_end_screen(_zdcurtain_ref: "ZDCurtain", similarity, threshold):
    return similarity > threshold and _zdcurtain_ref.active_load_type == "none"


def end_tracking_load(_zdcurtain_ref: "ZDCurtain", *, due_to_error=True):
    if _zdcurtain_ref.active_load_type != "black":
        _zdcurtain_ref.set_middle_of_load_dependencies_enabled(should_be_enabled=True)

    _zdcurtain_ref.potential_load_type = "none"
    _zdcurtain_ref.active_load_type = "none"
    _zdcurtain_ref.load_confidence_delta = 0
    _zdcurtain_ref.potential_load_detected_at_timestamp = 0
    _zdcurtain_ref.confirmed_load_detected_at_timestamp = 0
    _zdcurtain_ref.reset_icons()
    _zdcurtain_ref.after_changing_icon_signal.emit()
    _zdcurtain_ref.after_load_time_removed_changed_signal.emit()
    _zdcurtain_ref.is_load_being_removed = False

    if due_to_error:
        _zdcurtain_ref.should_block_load_detection = False
        _zdcurtain_ref.captured_window_title_before_load = ""


def perform_black_level_analysis(_zdcurtain_ref: "ZDCurtain"):
    if not is_valid_image(_zdcurtain_ref.capture_view_raw):
        return

    # full black
    average_luminance, image_entropy = calculate_frame_luminance(_zdcurtain_ref.capture_view_resized)

    _zdcurtain_ref.average_luminance = average_luminance
    _zdcurtain_ref.full_black_level = average_luminance / 255.0 * 100
    _zdcurtain_ref.full_shannon_entropy = image_entropy

    # slice black
    average_luminance, image_entropy = calculate_frame_luminance(_zdcurtain_ref.capture_view_resized_cropped)
    _zdcurtain_ref.slice_black_level = average_luminance / 255.0 * 100
    _zdcurtain_ref.slice_shannon_entropy = image_entropy


def perform_similarity_analysis(_zdcurtain_ref: "ZDCurtain"):
    if not is_valid_image(_zdcurtain_ref.capture_view_raw):
        return

    zd = _zdcurtain_ref
    zdsettings = _zdcurtain_ref.settings_dict

    images = [
        zd.comparison_elevator_power.image_data,
        zd.comparison_elevator_varia.image_data,
        zd.comparison_elevator_gravity.image_data,
    ]

    zd.similarity_to_elevator = (
        __perform_similarity_analysis_for_images(
            zdsettings["similarity_algorithm_elevator"],
            zd.get_capture_view_by_name(zdsettings["capture_view_elevator"]),
            images,
        )
        * 100
    )

    images = [
        zd.comparison_train_left_power.image_data,
        zd.comparison_train_left_varia.image_data,
        zd.comparison_train_left_gravity.image_data,
        zd.comparison_train_right_power.image_data,
        zd.comparison_train_right_varia.image_data,
        zd.comparison_train_right_gravity.image_data,
    ]

    zd.similarity_to_tram = (
        __perform_similarity_analysis_for_images(
            zdsettings["similarity_algorithm_tram"],
            zd.get_capture_view_by_name(zdsettings["capture_view_tram"]),
            images,
        )
        * 100
    )

    images = [
        zd.comparison_teleport_power.image_data,
        zd.comparison_teleport_varia.image_data,
        zd.comparison_teleport_gravity.image_data,
    ]

    zd.similarity_to_teleportal = (
        __perform_similarity_analysis_for_images(
            zdsettings["similarity_algorithm_teleportal"],
            zd.get_capture_view_by_name(zdsettings["capture_view_teleportal"]),
            images,
        )
        * 100
    )

    images = [
        zd.comparison_capsule_power.image_data,
        zd.comparison_capsule_varia.image_data,
        zd.comparison_capsule_gravity.image_data,
    ]

    zd.similarity_to_egg = (
        __perform_similarity_analysis_for_images(
            zdsettings["similarity_algorithm_egg"],
            zd.get_capture_view_by_name(zdsettings["capture_view_egg"]),
            images,
        )
        * 100
    )

    images = [
        zd.comparison_capsule_power.image_data,
        zd.comparison_capsule_varia.image_data,
        zd.comparison_capsule_gravity.image_data,
    ]

    zd.similarity_to_egg = (
        __perform_similarity_analysis_for_images(
            zdsettings["similarity_algorithm_egg"],
            zd.get_capture_view_by_name(zdsettings["capture_view_egg"]),
            images,
        )
        * 100
    )

    images = [
        zd.comparison_end_screen.image_data,
    ]

    zd.similarity_to_end_screen = (
        __perform_similarity_analysis_for_images(
            zdsettings["similarity_algorithm_end_screen"],
            zd.get_capture_view_by_name(zdsettings["capture_view_end_screen"]),
            images,
        )
        * 100
    )

    if zd.in_black_slice and zd.active_load_type != "spinner":
        capture_type_to_use = zd.get_capture_view_by_name("standard_resized")

        images = [
            zd.comparison_loading_widget.image_data,
        ]

        zd.similarity_to_loading_widget = int(
            __perform_similarity_analysis_for_images(
                "orb_bf",
                capture_type_to_use,
                images,
                options={
                    "nfeatures": 10000,
                    "passing_ratio": 0.5,
                },
            )
        )
    else:
        zd.similarity_to_loading_widget = 0

    capture_type_to_use = zd.get_capture_view_by_name("standard_resized")

    images = [
        zd.comparison_game_over_screen.image_data,
    ]

    zd.similarity_to_game_over_screen = int(
        __perform_similarity_analysis_for_images(
            "orb_flann",
            capture_type_to_use,
            images,
            options={
                "nfeatures": 500,
                "passing_ratio": 0.5,
            },
        )
    )

    __set_local_extremes(_zdcurtain_ref)


def mark_load_as_lost(_zdcurtain_ref: "ZDCurtain"):
    if _zdcurtain_ref.load_removal_session is None:
        return

    if _zdcurtain_ref.is_load_being_removed:
        load_lost_at = LocalTime()

        _ = _zdcurtain_ref.load_removal_session.create_lost_load_record(
            _zdcurtain_ref.active_load_type, load_lost_at
        )

        _zdcurtain_ref.after_load_list_changed_signal.emit()

        _zdcurtain_ref.show_error_signal.emit(
            lambda: error_messages.capture_stream_lost_during_load(load_lost_at)
        )

        end_tracking_load(_zdcurtain_ref)


def mark_load_as_discarded(_zdcurtain_ref: "ZDCurtain", discard_type):
    if _zdcurtain_ref.load_removal_session is None:
        return

    if _zdcurtain_ref.is_load_being_removed:
        load_discarded_at = LocalTime()

        _ = _zdcurtain_ref.load_removal_session.create_discarded_load_record(
            _zdcurtain_ref.active_load_type, load_discarded_at, discard_type
        )

        _zdcurtain_ref.after_load_list_changed_signal.emit()

        end_tracking_load(_zdcurtain_ref, due_to_error=False)


def __perform_similarity_analysis_for_images(comparison_method_name, capture, image_list, *, options=None):
    comparison_method_to_use = get_comparison_method_by_name(comparison_method_name)

    highest_value = 0.0

    for i in image_list:
        value = comparison_method_to_use(capture, i, options=options)

        highest_value = max(highest_value, value)

    return highest_value


def __check_black_screen_markers(_zdcurtain_ref: "ZDCurtain"):
    if (
        _zdcurtain_ref.full_black_level < _zdcurtain_ref.settings_dict["black_threshold"]
        and _zdcurtain_ref.full_shannon_entropy < _zdcurtain_ref.settings_dict["black_entropy_threshold"]
        and not _zdcurtain_ref.in_black_screen
    ):
        _zdcurtain_ref.in_black_screen = True
        _zdcurtain_ref.full_black_detected_at_timestamp = perf_counter_ns()
        debug_log(f"Entered full black at timestamp {_zdcurtain_ref.full_black_detected_at_timestamp}")

    if (
        _zdcurtain_ref.full_black_level >= _zdcurtain_ref.settings_dict["black_threshold"]
        or _zdcurtain_ref.full_shannon_entropy >= _zdcurtain_ref.settings_dict["black_entropy_threshold"]
    ) and _zdcurtain_ref.in_black_screen:
        _zdcurtain_ref.full_black_over_detected_at_timestamp = perf_counter_ns()
        _zdcurtain_ref.in_black_screen = False
        debug_log(f"Left full black at timestamp {_zdcurtain_ref.full_black_over_detected_at_timestamp}")

    if (
        _zdcurtain_ref.slice_black_level < _zdcurtain_ref.settings_dict["black_threshold"]
        and _zdcurtain_ref.slice_shannon_entropy < _zdcurtain_ref.settings_dict["black_entropy_threshold"]
        and not _zdcurtain_ref.in_black_slice
    ):
        _zdcurtain_ref.slice_black_detected_at_timestamp = perf_counter_ns()
        _zdcurtain_ref.in_black_slice = True
        debug_log(f"Entered slice black at timestamp {_zdcurtain_ref.slice_black_detected_at_timestamp}")

    if (
        _zdcurtain_ref.slice_black_level >= _zdcurtain_ref.settings_dict["black_threshold"]
        or _zdcurtain_ref.slice_shannon_entropy >= _zdcurtain_ref.settings_dict["black_entropy_threshold"]
    ) and _zdcurtain_ref.in_black_slice:
        _zdcurtain_ref.slice_black_over_detected_at_timestamp = perf_counter_ns()
        _zdcurtain_ref.in_black_slice = False
        debug_log(f"Left slice black at timestamp {_zdcurtain_ref.slice_black_over_detected_at_timestamp}")


def __check_load_blocking_logic(_zdcurtain_ref: "ZDCurtain"):
    if (
        _zdcurtain_ref.similarity_to_game_over_screen >= GAMEOVER_FEATURE_SIMILARITY_THRESHOLD
        and not _zdcurtain_ref.in_game_over_screen
    ):
        _zdcurtain_ref.in_game_over_screen = True
        _zdcurtain_ref.should_block_load_detection = True
        debug_log(f"Entered gameover at timestamp {perf_counter_ns()}")
    elif (
        _zdcurtain_ref.similarity_to_game_over_screen < GAMEOVER_FEATURE_SIMILARITY_THRESHOLD
        and _zdcurtain_ref.in_game_over_screen
    ):
        _zdcurtain_ref.in_game_over_screen = False
        _zdcurtain_ref.should_block_load_detection = False
        debug_log(f"Left gameover at timestamp {perf_counter_ns()}")


def __set_local_extremes(_zdcurtain_ref: "ZDCurtain"):
    zd = _zdcurtain_ref
    zd.similarity_to_elevator_max = max(zd.similarity_to_elevator, zd.similarity_to_elevator_max)
    zd.similarity_to_tram_max = max(zd.similarity_to_tram, zd.similarity_to_tram_max)
    zd.similarity_to_teleportal_max = max(zd.similarity_to_teleportal, zd.similarity_to_teleportal_max)
    zd.similarity_to_egg_max = max(zd.similarity_to_egg, zd.similarity_to_egg_max)
    zd.similarity_to_end_screen_max = max(zd.similarity_to_end_screen, zd.similarity_to_end_screen_max)
    zd.similarity_to_game_over_screen_max = max(
        zd.similarity_to_game_over_screen, zd.similarity_to_game_over_screen_max
    )
    zd.similarity_to_loading_widget_max = max(
        zd.similarity_to_loading_widget, zd.similarity_to_loading_widget_max
    )

    zd.similarity_to_end_screen_max = max(zd.similarity_to_end_screen_max, zd.similarity_to_end_screen)
    zd.full_shannon_entropy_min = min(zd.full_shannon_entropy, zd.full_shannon_entropy_min)
    zd.slice_shannon_entropy_min = min(zd.slice_shannon_entropy, zd.slice_shannon_entropy_min)


def __check_for_active_loads(_zdcurtain_ref: "ZDCurtain"):
    if (
        _zdcurtain_ref.in_black_screen
        and _zdcurtain_ref.active_load_type in "none"
        and not _zdcurtain_ref.load_cooldown_is_active
        and not _zdcurtain_ref.should_block_load_detection
        and perf_counter_ns() - _zdcurtain_ref.full_black_detected_at_timestamp > ms_to_ns(DREAD_MAX_DELTA_MS)
    ):
        _zdcurtain_ref.confirmed_load_detected_at_timestamp = perf_counter_ns()
        _zdcurtain_ref.active_load_type = "black"
        create_icon(_zdcurtain_ref.black_screen_load_icon, _zdcurtain_ref.loading_icon)
        _zdcurtain_ref.after_changing_icon_signal.emit()
        debug_log(f"Detected black load at {_zdcurtain_ref.confirmed_load_detected_at_timestamp}")

    label = None

    if (
        _zdcurtain_ref.active_load_type in {"none", "black"}
        and not _zdcurtain_ref.load_cooldown_is_active
        and not _zdcurtain_ref.should_block_load_detection
        and not _zdcurtain_ref.in_game_over_screen
    ):
        if __check_load_confidence(
            _zdcurtain_ref,
            "elevator",
            _zdcurtain_ref.similarity_to_elevator,
            _zdcurtain_ref.settings_dict["similarity_threshold_elevator"],
        ):
            _zdcurtain_ref.active_load_type = "elevator"
            label = _zdcurtain_ref.elevator_tracking_icon

        if __check_load_confidence(
            _zdcurtain_ref,
            "tram",
            _zdcurtain_ref.similarity_to_tram,
            _zdcurtain_ref.settings_dict["similarity_threshold_tram"],
        ):
            _zdcurtain_ref.active_load_type = "tram"
            label = _zdcurtain_ref.tram_tracking_icon

        if __check_load_confidence(
            _zdcurtain_ref,
            "teleportal",
            _zdcurtain_ref.similarity_to_teleportal,
            _zdcurtain_ref.settings_dict["similarity_threshold_teleportal"],
        ):
            _zdcurtain_ref.active_load_type = "teleportal"
            label = _zdcurtain_ref.teleportal_tracking_icon

        if __check_load_confidence(
            _zdcurtain_ref,
            "egg",
            _zdcurtain_ref.similarity_to_egg,
            _zdcurtain_ref.settings_dict["similarity_threshold_egg"],
        ):
            _zdcurtain_ref.active_load_type = "egg"
            label = _zdcurtain_ref.egg_tracking_icon

        if __check_load_confidence(
            _zdcurtain_ref,
            "spinner",
            _zdcurtain_ref.similarity_to_loading_widget,
            LOADING_WIDGET_SIMILARITY_THRESHOLD,
        ):
            _zdcurtain_ref.active_load_type = "spinner"
            label = _zdcurtain_ref.black_screen_load_icon

        if not _zdcurtain_ref.is_load_being_removed and _zdcurtain_ref.active_load_type != "none":
            _zdcurtain_ref.is_load_being_removed = True
            _zdcurtain_ref.captured_window_title_before_load = _zdcurtain_ref.settings_dict[
                "captured_window_title"
            ]

            if _zdcurtain_ref.active_load_type != "black" and label is not None:
                create_icon(
                    label,
                    _zdcurtain_ref.loading_icon,
                )
                _zdcurtain_ref.after_changing_icon_signal.emit()
                _zdcurtain_ref.set_middle_of_load_dependencies_enabled(should_be_enabled=False)
                debug_log(
                    f'Detected "{_zdcurtain_ref.active_load_type}" load at '
                    + f"{_zdcurtain_ref.confirmed_load_detected_at_timestamp}"
                )
                debug_log(f"Expected delta: {ns_to_ms(_zdcurtain_ref.load_confidence_delta)}ms")
        elif _zdcurtain_ref.active_load_type == "none":
            match _zdcurtain_ref.potential_load_type:
                case "elevator":
                    create_icon(
                        _zdcurtain_ref.elevator_tracking_icon,
                        _zdcurtain_ref.elevator_icon_tentative,
                    )
                    _zdcurtain_ref.after_changing_icon_signal.emit()
                case "tram":
                    create_icon(
                        _zdcurtain_ref.tram_tracking_icon,
                        _zdcurtain_ref.tram_icon_tentative,
                    )
                    _zdcurtain_ref.after_changing_icon_signal.emit()
                case "teleportal":
                    create_icon(
                        _zdcurtain_ref.teleportal_tracking_icon,
                        _zdcurtain_ref.teleportal_icon_tentative,
                    )
                    _zdcurtain_ref.after_changing_icon_signal.emit()
                case "egg":
                    create_icon(
                        _zdcurtain_ref.egg_tracking_icon,
                        _zdcurtain_ref.capsule_icon_tentative,
                    )
                    _zdcurtain_ref.after_changing_icon_signal.emit()
                case "none":
                    _zdcurtain_ref.reset_icons()


def __check_load_confidence(
    _zdcurtain_ref: "ZDCurtain", load_type, similarity, threshold, *, use_slice_black=True
):
    if similarity > threshold and _zdcurtain_ref.active_load_type == "none":
        if _zdcurtain_ref.potential_load_detected_at_timestamp == 0:
            _zdcurtain_ref.potential_load_detected_at_timestamp = perf_counter_ns()
            _zdcurtain_ref.potential_load_type = load_type

        if (
            perf_counter_ns() - _zdcurtain_ref.potential_load_detected_at_timestamp
            > ms_to_ns(_zdcurtain_ref.settings_dict["load_confidence_threshold_ms"])
            or load_type == "spinner"
        ):
            _zdcurtain_ref.confirmed_load_detected_at_timestamp = perf_counter_ns()

            black_screen_detection_timestamp = (
                _zdcurtain_ref.slice_black_detected_at_timestamp
                if use_slice_black
                else _zdcurtain_ref.full_black_detected_at_timestamp
            )

            _zdcurtain_ref.load_confidence_delta = (
                _zdcurtain_ref.confirmed_load_detected_at_timestamp - black_screen_detection_timestamp
            )

            return True
    elif (
        similarity <= threshold
        and _zdcurtain_ref.active_load_type == "none"
        and _zdcurtain_ref.potential_load_type == load_type
    ):
        _zdcurtain_ref.potential_load_type = "none"

    return False


def __check_load_cooldown(_zdcurtain_ref: "ZDCurtain"):
    if (
        _zdcurtain_ref.load_cooldown_type != "none"
        and perf_counter_ns()
        > _zdcurtain_ref.load_cooldown_timestamp
        + ms_to_ns(_zdcurtain_ref.settings_dict[f"load_cooldown_{_zdcurtain_ref.load_cooldown_type}_ms"])
    ):
        _zdcurtain_ref.load_cooldown_timestamp = 0
        _zdcurtain_ref.load_cooldown_type = "none"
        _zdcurtain_ref.load_cooldown_is_active = False


def __check_if_load_ending(_zdcurtain_ref: "ZDCurtain"):
    if _zdcurtain_ref.load_removal_session is None:
        return

    black_screen_over_detection_timestamp = (
        _zdcurtain_ref.slice_black_over_detected_at_timestamp
        if _zdcurtain_ref.active_load_type == "spinner"
        else _zdcurtain_ref.full_black_over_detected_at_timestamp
    )

    if (
        black_screen_over_detection_timestamp > _zdcurtain_ref.confirmed_load_detected_at_timestamp
        and _zdcurtain_ref.is_load_being_removed
        and not _zdcurtain_ref.should_block_load_detection
    ):
        if _zdcurtain_ref.active_load_type not in {"none", "black"}:  # noqa: SIM102 need _zdcurtain_ref.active_load_type
            if (
                _zdcurtain_ref.load_cooldown_type == "none"
                and _zdcurtain_ref.settings_dict[f"load_cooldown_{_zdcurtain_ref.active_load_type}_ms"] > 0
            ):
                _zdcurtain_ref.load_cooldown_type = _zdcurtain_ref.active_load_type
                _zdcurtain_ref.load_cooldown_timestamp = perf_counter_ns()
                _zdcurtain_ref.load_cooldown_is_active = True

        if perf_counter_ns() - black_screen_over_detection_timestamp > _zdcurtain_ref.load_confidence_delta:
            _zdcurtain_ref.single_load_time_removed_ms = ns_to_ms(
                _zdcurtain_ref.load_confidence_delta
                + (
                    black_screen_over_detection_timestamp
                    - _zdcurtain_ref.confirmed_load_detected_at_timestamp
                )
            )

            debug_log(
                f'Detected "{_zdcurtain_ref.active_load_type}" load at '
                + f"{_zdcurtain_ref.confirmed_load_detected_at_timestamp}"
            )

            _zdcurtain_ref.load_time_removed_ms += _zdcurtain_ref.single_load_time_removed_ms

            _ = _zdcurtain_ref.load_removal_session.create_load_removal_record(
                _zdcurtain_ref.active_load_type, _zdcurtain_ref.single_load_time_removed_ms
            )

            _zdcurtain_ref.after_load_list_changed_signal.emit()

            end_tracking_load(_zdcurtain_ref)
