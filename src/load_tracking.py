import csv
import datetime
import json

from openpyxl import Workbook
from pathvalidate import sanitize_filename
from PySide6.QtWidgets import QFileDialog

from utils import LocalTime, flatten_dict, get_version


class LoadRemovalSession:
    def __init__(self):
        now = LocalTime()
        self.__loads = []
        self.sessionInfo = LoadRemovalSessionInfo(now, get_version(), self)

    def export_loads(self, data_format, filename):
        match data_format:
            case "json":
                self.__write_to_json(f"{filename}")
            case "excel":
                self.__write_to_excel(
                    f"{filename}",
                    sheet_name="Removed Loads",
                )
            case "csv":
                self.__write_to_csv(f"{filename}")
            case _:
                raise KeyError(f"{data_format!r} is not a valid export format")

    def create_load_removal_record(self, load_type, load_time_removed):
        now = LocalTime()
        self.__loads.append(LoadRemovalRecordEntry(load_type, load_time_removed, now))
        return self.__loads[-1]

    def create_lost_load_record(self, load_type, load_lost_at):
        self.__loads.append(LostLoadEntry(load_type, load_lost_at))
        return self.__loads[-1]

    def create_discarded_load_record(self, load_type, load_discarded_at, discard_type):
        self.__loads.append(DiscardedLoadEntry(load_type, load_discarded_at, discard_type))
        return self.__loads[-1]

    def get_session_started_at(self):
        return self.sessionInfo.startedAt

    def get_loads(self):
        return self.__loads

    def get_load_count(self):
        return len(self.__loads)

    def get_major_load_count(self):
        major_loads = [load for load in self.__loads if load.loadType != "black"]

        return len(major_loads)

    def get_transition_load_count(self):
        transition_loads = [load for load in self.__loads if load.loadType not in {"black", "spinner"}]

        return len(transition_loads)

    def get_load_type_count(self, load_type):
        loads = [load for load in self.__loads if load.loadType != load_type]

        return len(loads)

    def get_latest_load(self):
        if self.get_load_count() > 0:
            return self.__loads[-1]
        return None

    def get_recent_loads(self, seconds_to_look_back, *, removals_only=False):
        loads = None

        if removals_only:
            loads = [x for x in self.__loads if isinstance(x, LoadRemovalRecordEntry)]
        else:
            loads = self.__loads

        now = LocalTime().get_datetime()
        time_delta = datetime.timedelta(seconds=seconds_to_look_back * -1)
        adjusted_datetime = now + time_delta

        return [x for x in loads if x.loadRemovedAt.get_datetime() >= adjusted_datetime]

    def delete_load(self, datetime):
        if self.get_load_count() > 0:
            load_to_delete_index = next(
                (i for i, load in enumerate(self.__loads) if load.loadRemovedAt.get_datetime() == datetime),
                None,
            )

            if load_to_delete_index is not None:
                del self.__loads[load_to_delete_index]

    def __write_to_csv(self, filepath):
        field_names = [
            "loadTimeRemoved",
            "loadType",
            "wasLoadLost",
            "wasLoadDiscarded",
            "discardType",
            "eventDateTime_date",
            "eventDateTime_timestamp",
            "eventDateTime_timezone",
        ]

        session_dict = self.to_dict()
        loads = session_dict.get("loads")

        loads_as_dict = []

        if loads is not None:
            for load in loads:
                flattened_dict = flatten_dict(load)
                loads_as_dict.append(flattened_dict)

        with open(filepath, "w", newline="", encoding="utf8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=field_names)
            writer.writeheader()
            writer.writerows(loads_as_dict)

    def __write_to_excel(self, filepath, sheet_name):
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet(sheet_name)

        sheet.column_dimensions["A"].width = 19
        sheet.column_dimensions["B"].width = 10
        sheet.column_dimensions["C"].width = 14
        sheet.column_dimensions["D"].width = 19
        sheet.column_dimensions["E"].width = 12
        sheet.column_dimensions["F"].width = 31
        sheet.column_dimensions["G"].width = 16
        sheet.column_dimensions["H"].width = 22

        field_names = [
            "loadTimeRemoved",
            "loadType",
            "wasLoadLost",
            "wasLoadDiscarded",
            "discardType",
            "eventDateTime_date",
            "eventDateTime_timestamp",
            "eventDateTime_timezone",
        ]

        sheet.append([
            "Load Time Removed",
            "Load Type",
            "Was Load Lost?",
            "Was Load Discarded?",
            "Discard Type",
            "Event Date",
            "Event Timestamp",
            "Event Timezone",
        ])

        session_dict = self.to_dict()
        loads = session_dict.get("loads")

        if loads is not None:
            for load in loads:
                flattened_dict = flatten_dict(load)
                values = (flattened_dict[k] for k in field_names)
                sheet.append(values)

        workbook.save(filepath)

    def __write_to_json(self, filepath):
        with open(filepath, "w", encoding="utf-8", newline=None) as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def to_dict(self):
        return {
            "sessionInfo": self.sessionInfo.to_dict(),
            "loads": [load.to_dict() for load in self.__loads],
        }


class LostLoadEntry:
    def __init__(self, load_type, load_lost_at):
        self.loadType = load_type
        self.loadLostAt = load_lost_at

    def to_dict(self):
        return {
            "loadTimeRemoved": 0,
            "loadType": self.loadType,
            "eventDateTime": self.loadLostAt.to_dict(),
            "wasLoadLost": "yes",
            "wasLoadDiscarded": "no",
            "discardType": "",
        }

    def to_string(self):
        return (
            f'[{self.loadLostAt.date}]: WARNING: LOST load of type "{self.loadType}", check your '
            + "stream to make sure it's stable."
        )


class DiscardedLoadEntry:
    def __init__(self, load_type, load_discarded_at, discard_type):
        self.loadType = load_type
        self.loadDiscardedAt = load_discarded_at
        self.discardType = discard_type

    def to_dict(self):
        return {
            "loadTimeRemoved": 0,
            "loadType": self.loadType,
            "eventDateTime": self.loadDiscardedAt.to_dict(),
            "wasLoadLost": "no",
            "wasLoadDiscarded": "yes",
            "discardType": self.discardType,
        }

    def to_string(self):
        return (
            f"[{self.loadDiscardedAt.date}]: ZDCurtain discarded erroneous load of type "
            + f'"{self.loadType}", reasoning used: "{self.discardType}"'
        )


class LoadRemovalRecordEntry:
    def __init__(self, load_type, load_time_removed, load_removed_at):
        self.loadType = load_type
        self.loadTimeRemoved = load_time_removed
        self.loadRemovedAt = load_removed_at

    def to_dict(self):
        return {
            "loadTimeRemoved": self.loadTimeRemoved,
            "loadType": self.loadType,
            "eventDateTime": self.loadRemovedAt.to_dict(),
            "wasLoadLost": "no",
            "wasLoadDiscarded": "no",
            "discardType": "",
        }

    def to_string(self):
        return (
            f'[{self.loadRemovedAt.date}]: removed load type "{self.loadType}"'
            + f", duration {self.loadTimeRemoved:.3f}ms"
        )


class LoadRemovalSessionInfo:
    def __init__(
        self,
        started_at: LocalTime,
        created_with_version: str,
        _load_removal_session_ref: LoadRemovalSession,
    ):
        self.startedAt = started_at
        self.createdWithVersion = created_with_version
        self.loadRemovalSession = _load_removal_session_ref

    def to_dict(self):
        return {
            "startedAt": self.startedAt.to_dict(),
            "createdWithVersion": self.createdWithVersion,
            "majorLoadCount": self.loadRemovalSession.get_major_load_count(),
            "loadCount": self.loadRemovalSession.get_load_count(),
        }


def export_tracked_loads(load_removal_session):
    filename = sanitize_filename(f"load-removal-session_{load_removal_session.sessionInfo.startedAt.date}")
    selected_file_path, selected_filter = QFileDialog.getSaveFileName(
        filter="JSON (*.json);;Excel Document (*.xlsx);;CSV UTF-8 (comma delimited) (*.csv)", dir=filename
    )

    data_format = None

    match selected_filter:
        case "JSON (*.json)":
            data_format = "json"
        case "Excel Document (*.xlsx)":
            data_format = "excel"
        case "CSV UTF-8 (comma delimited) (*.csv)":
            data_format = "csv"

    if selected_file_path:
        load_removal_session.export_loads(data_format, selected_file_path)
