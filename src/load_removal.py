#!/usr/bin/python3
from time import perf_counter_ns
from typing import TYPE_CHECKING

from frame_analysis import calculate_frame_luminance, get_comparison_method_by_name
from hotkeys import send_command
from utils import DREAD_MAX_DELTA_MS, create_icon, is_valid_image, ms_to_ns, ns_to_ms

if TYPE_CHECKING:
    from ui.zdcurtain_ui import ZDCurtain


def perform_load_removal_logic(_zdcurtain_ref: "ZDCurtain"):
    if is_end_screen(_zdcurtain_ref, _zdcurtain_ref.similarity_to_end_screen, 98):
        # stop tracking
        _zdcurtain_ref.end_tracking()

    if not _zdcurtain_ref.is_tracking:
        return

    check_load_cooldown(_zdcurtain_ref)

    if (
        _zdcurtain_ref.black_level < _zdcurtain_ref.settings_dict["black_threshold"]
        and _zdcurtain_ref.blacklevel_entropy < _zdcurtain_ref.settings_dict["black_entropy_threshold"]
        and not _zdcurtain_ref.in_black_screen
    ):
        _zdcurtain_ref.in_black_screen = True
        _zdcurtain_ref.black_screen_detected_at_timestamp = perf_counter_ns()

    if (
        _zdcurtain_ref.black_level >= _zdcurtain_ref.settings_dict["black_threshold"]
        or _zdcurtain_ref.blacklevel_entropy >= _zdcurtain_ref.settings_dict["black_entropy_threshold"]
    ) and _zdcurtain_ref.in_black_screen:
        _zdcurtain_ref.black_screen_over_detected_at_timestamp = perf_counter_ns()
        _zdcurtain_ref.in_black_screen = False

    if (
        _zdcurtain_ref.in_black_screen
        and _zdcurtain_ref.active_load_type == "none"
        and not _zdcurtain_ref.load_cooldown_is_active
        and perf_counter_ns() - _zdcurtain_ref.black_screen_detected_at_timestamp
        > ms_to_ns(DREAD_MAX_DELTA_MS)
    ):
        _zdcurtain_ref.confirmed_load_detected_at_timestamp = perf_counter_ns()
        _zdcurtain_ref.active_load_type = "black"

    if _zdcurtain_ref.active_load_type in {"none", "black"} and not _zdcurtain_ref.load_cooldown_is_active:
        if check_load_confidence(
            _zdcurtain_ref,
            _zdcurtain_ref.similarity_to_elevator,
            _zdcurtain_ref.settings_dict["similarity_threshold_elevator"],
        ):
            _zdcurtain_ref.active_load_type = "elevator"
            create_icon(_zdcurtain_ref.elevator_tracking_icon, _zdcurtain_ref.loading_icon)

        if check_load_confidence(
            _zdcurtain_ref,
            _zdcurtain_ref.similarity_to_tram,
            _zdcurtain_ref.settings_dict["similarity_threshold_tram"],
        ):
            _zdcurtain_ref.active_load_type = "tram"
            create_icon(_zdcurtain_ref.tram_tracking_icon, _zdcurtain_ref.loading_icon)

        if check_load_confidence(
            _zdcurtain_ref,
            _zdcurtain_ref.similarity_to_teleportal,
            _zdcurtain_ref.settings_dict["similarity_threshold_teleportal"],
        ):
            _zdcurtain_ref.active_load_type = "teleportal"
            create_icon(_zdcurtain_ref.teleportal_tracking_icon, _zdcurtain_ref.loading_icon)

        if check_load_confidence(
            _zdcurtain_ref,
            _zdcurtain_ref.similarity_to_egg,
            _zdcurtain_ref.settings_dict["similarity_threshold_egg"],
        ):
            _zdcurtain_ref.active_load_type = "egg"
            create_icon(_zdcurtain_ref.egg_tracking_icon, _zdcurtain_ref.loading_icon)

    if not _zdcurtain_ref.is_load_being_removed and _zdcurtain_ref.active_load_type != "none":
        send_command(_zdcurtain_ref, "pause")
        _zdcurtain_ref.is_load_being_removed = True
        _zdcurtain_ref.captured_window_title_before_load = _zdcurtain_ref.settings_dict[
            "captured_window_title"
        ]

        if _zdcurtain_ref.active_load_type != "black":
            _zdcurtain_ref.set_middle_of_load_dependencies_enabled(should_be_enabled=False)

    check_if_load_ending(_zdcurtain_ref)


def check_load_confidence(_zdcurtain_ref: "ZDCurtain", similarity, threshold):
    if similarity > threshold and _zdcurtain_ref.active_load_type == "none":
        if _zdcurtain_ref.potential_load_detected_at_timestamp == 0:
            _zdcurtain_ref.potential_load_detected_at_timestamp = perf_counter_ns()

        if perf_counter_ns() - _zdcurtain_ref.potential_load_detected_at_timestamp > ms_to_ns(
            _zdcurtain_ref.settings_dict["load_confidence_threshold_ms"]
        ):
            _zdcurtain_ref.confirmed_load_detected_at_timestamp = perf_counter_ns()

            _zdcurtain_ref.load_confidence_delta = (
                _zdcurtain_ref.confirmed_load_detected_at_timestamp
                - _zdcurtain_ref.black_screen_detected_at_timestamp
            )

            return True

    return False


def is_end_screen(_zdcurtain_ref: "ZDCurtain", similarity, threshold):
    return similarity > threshold and _zdcurtain_ref.active_load_type == "none"


def check_load_cooldown(_zdcurtain_ref: "ZDCurtain"):
    if (
        _zdcurtain_ref.load_cooldown_type != "none"
        and perf_counter_ns()
        > _zdcurtain_ref.load_cooldown_timestamp
        + ms_to_ns(_zdcurtain_ref.settings_dict[f"load_cooldown_{_zdcurtain_ref.load_cooldown_type}_ms"])
    ):
        _zdcurtain_ref.load_cooldown_timestamp = 0
        _zdcurtain_ref.load_cooldown_type = "none"
        _zdcurtain_ref.load_cooldown_is_active = False
        _zdcurtain_ref.analysis_load_cooldown_label.setText("")


def check_if_load_ending(_zdcurtain_ref: "ZDCurtain"):
    if _zdcurtain_ref.load_removal_session is None:
        return

    if (
        _zdcurtain_ref.black_screen_over_detected_at_timestamp
        > _zdcurtain_ref.confirmed_load_detected_at_timestamp
        and _zdcurtain_ref.is_load_being_removed
    ):
        if _zdcurtain_ref.active_load_type not in {"none", "black"}:  # noqa: SIM102 need _zdcurtain_ref.active_load_type
            if (
                _zdcurtain_ref.load_cooldown_type == "none"
                and _zdcurtain_ref.settings_dict[f"load_cooldown_{_zdcurtain_ref.active_load_type}_ms"] > 0
            ):
                _zdcurtain_ref.load_cooldown_type = _zdcurtain_ref.active_load_type
                _zdcurtain_ref.load_cooldown_timestamp = perf_counter_ns()
                _zdcurtain_ref.load_cooldown_is_active = True
                _zdcurtain_ref.analysis_load_cooldown_label.setText(" Load Cooldown Active")

        if (
            perf_counter_ns() - _zdcurtain_ref.black_screen_over_detected_at_timestamp
            > _zdcurtain_ref.load_confidence_delta
        ):
            _zdcurtain_ref.single_load_time_removed_ms = ns_to_ms(
                _zdcurtain_ref.load_confidence_delta
                + (
                    _zdcurtain_ref.black_screen_over_detected_at_timestamp
                    - _zdcurtain_ref.confirmed_load_detected_at_timestamp
                )
            )

            send_command(_zdcurtain_ref, "pause")

            _zdcurtain_ref.load_time_removed_ms += _zdcurtain_ref.single_load_time_removed_ms

            load_record = _zdcurtain_ref.load_removal_session.create_load_removal_record(
                _zdcurtain_ref.active_load_type, _zdcurtain_ref.single_load_time_removed_ms
            )

            _zdcurtain_ref.previous_loads_list.insertItem(0, load_record.to_string())

            end_tracking_load(_zdcurtain_ref)


def end_tracking_load(_zdcurtain_ref: "ZDCurtain"):
    if _zdcurtain_ref.active_load_type != "black":
        _zdcurtain_ref.set_middle_of_load_dependencies_enabled(should_be_enabled=True)

    _zdcurtain_ref.active_load_type = "none"
    _zdcurtain_ref.load_confidence_delta = 0
    _zdcurtain_ref.potential_load_detected_at_timestamp = 0
    _zdcurtain_ref.confirmed_load_detected_at_timestamp = 0
    _zdcurtain_ref.reset_icons()
    _zdcurtain_ref.is_load_being_removed = False
    _zdcurtain_ref.captured_window_title_before_load = ""


def perform_black_level_analysis(_zdcurtain_ref: "ZDCurtain"):
    if not is_valid_image(_zdcurtain_ref.capture_view_raw):
        return

    average_luminance, image_entropy = calculate_frame_luminance(_zdcurtain_ref.capture_view_resized_cropped)

    _zdcurtain_ref.average_luminance = average_luminance
    _zdcurtain_ref.black_level = average_luminance / 255.0 * 100
    _zdcurtain_ref.blacklevel_entropy = image_entropy


def perform_similarity_analysis(_zdcurtain_ref: "ZDCurtain"):
    if not is_valid_image(_zdcurtain_ref.capture_view_raw):
        return

    comparison_method_to_use = get_comparison_method_by_name(
        _zdcurtain_ref.settings_dict["similarity_algorithm_elevator"]
    )

    capture_type_to_use = _zdcurtain_ref.get_capture_view_by_name(
        _zdcurtain_ref.settings_dict["capture_view_elevator"]
    )

    _zdcurtain_ref.similarity_to_elevator = (
        max(
            comparison_method_to_use(
                capture_type_to_use,
                _zdcurtain_ref.comparison_elevator_power.image_data,
            ),
            comparison_method_to_use(
                capture_type_to_use,
                _zdcurtain_ref.comparison_elevator_varia.image_data,
            ),
            comparison_method_to_use(
                capture_type_to_use,
                _zdcurtain_ref.comparison_elevator_gravity.image_data,
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        _zdcurtain_ref.settings_dict["similarity_algorithm_tram"]
    )

    capture_type_to_use = _zdcurtain_ref.get_capture_view_by_name(
        _zdcurtain_ref.settings_dict["capture_view_tram"]
    )

    _zdcurtain_ref.similarity_to_tram = (
        max(
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_train_left_power.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_train_left_varia.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_train_left_gravity.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_train_right_power.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_train_right_varia.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_train_right_gravity.image_data
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        _zdcurtain_ref.settings_dict["similarity_algorithm_teleportal"]
    )

    capture_type_to_use = _zdcurtain_ref.get_capture_view_by_name(
        _zdcurtain_ref.settings_dict["capture_view_teleportal"]
    )

    _zdcurtain_ref.similarity_to_teleportal = (
        max(
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_teleport_power.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_teleport_varia.image_data
            ),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_teleport_gravity.image_data
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        _zdcurtain_ref.settings_dict["similarity_algorithm_egg"]
    )

    capture_type_to_use = _zdcurtain_ref.get_capture_view_by_name(
        _zdcurtain_ref.settings_dict["capture_view_egg"]
    )

    _zdcurtain_ref.similarity_to_egg = (
        max(
            comparison_method_to_use(capture_type_to_use, _zdcurtain_ref.comparison_capsule_power.image_data),
            comparison_method_to_use(capture_type_to_use, _zdcurtain_ref.comparison_capsule_varia.image_data),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_capsule_gravity.image_data
            ),
        )
        * 100
    )

    _zdcurtain_ref.similarity_to_elevator_max = max(
        _zdcurtain_ref.similarity_to_elevator_max, _zdcurtain_ref.similarity_to_elevator
    )
    _zdcurtain_ref.similarity_to_tram_max = max(
        _zdcurtain_ref.similarity_to_tram_max, _zdcurtain_ref.similarity_to_tram
    )
    _zdcurtain_ref.similarity_to_teleportal_max = max(
        _zdcurtain_ref.similarity_to_teleportal_max, _zdcurtain_ref.similarity_to_teleportal
    )
    _zdcurtain_ref.similarity_to_egg_max = max(
        _zdcurtain_ref.similarity_to_egg_max, _zdcurtain_ref.similarity_to_egg
    )

    _zdcurtain_ref.similarity_to_egg = (
        max(
            comparison_method_to_use(capture_type_to_use, _zdcurtain_ref.comparison_capsule_power.image_data),
            comparison_method_to_use(capture_type_to_use, _zdcurtain_ref.comparison_capsule_varia.image_data),
            comparison_method_to_use(
                capture_type_to_use, _zdcurtain_ref.comparison_capsule_gravity.image_data
            ),
        )
        * 100
    )

    comparison_method_to_use = get_comparison_method_by_name(
        _zdcurtain_ref.settings_dict["similarity_algorithm_end_screen"]
    )

    capture_type_to_use = _zdcurtain_ref.get_capture_view_by_name(
        _zdcurtain_ref.settings_dict["capture_view_end_screen"]
    )

    _zdcurtain_ref.similarity_to_end_screen = (
        comparison_method_to_use(capture_type_to_use, _zdcurtain_ref.comparison_end_screen.image_data) * 100
    )

    _zdcurtain_ref.similarity_to_end_screen_max = max(
        _zdcurtain_ref.similarity_to_end_screen_max, _zdcurtain_ref.similarity_to_end_screen
    )
