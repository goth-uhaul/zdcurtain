import json

import pandas as pd
from pathvalidate import sanitize_filename
from PySide6.QtWidgets import QFileDialog

from utils import LocalTime, get_version


class LoadRemovalSession:
    def __init__(self):
        now = LocalTime()
        self.loads = []
        self.sessionInfo = LoadRemovalSessionInfo(now, get_version(), 0)

    def export_loads(self, data_format, filename):
        self.sessionInfo.set_load_count(len(self.loads))

        match data_format:
            case "json":
                self.__write_to_json(f"{filename}")
            case "excel":
                self.__write_to_excel(
                    f"{filename}",
                    sheet_name="Removed Loads",
                )
            case _:
                raise KeyError(f"{data_format!r} is not a valid export format")

    def create_load_removal_record(self, load_type, load_time_removed):
        now = LocalTime()
        self.loads.append(LoadRemovalRecordEntry(load_type, load_time_removed, now))
        return self.loads[len(self.loads) - 1]

    def __write_to_excel(self, filepath, sheet_name):
        df = pd.json_normalize(self.to_dict(), ["loads"])
        return df.to_excel(filepath, sheet_name, index=False)

    def __write_to_json(self, filepath):
        with open(filepath, "w", encoding="utf-8", newline=None) as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def to_dict(self):
        return {
            "sessionInfo": self.sessionInfo.to_dict(),
            "loads": [load.to_dict() for load in self.loads],
        }


class LoadRemovalRecordEntry:
    def __init__(self, load_type, load_time_removed, load_removed_at):
        self.loadType = load_type
        self.loadTimeRemoved = load_time_removed
        self.loadRemovedAt = load_removed_at

    def to_dict(self):
        return {
            "loadTimeRemoved": self.loadTimeRemoved,
            "loadType": self.loadType,
            "loadRemovedAt": self.loadRemovedAt.to_dict(),
        }

    def to_string(self):
        return (
            f'[{self.loadRemovedAt.date}]: removed load type "{self.loadType}"'
            + f", duration {self.loadTimeRemoved:.3f}ms"
        )


class LoadRemovalSessionInfo:
    def __init__(self, started_at, created_with_version, load_count):
        self.startedAt = started_at
        self.createdWithVersion = created_with_version
        self.loadCount = load_count

    def set_load_count(self, load_count):
        self.loadCount = load_count

    def to_dict(self):
        return {
            "startedAt": self.startedAt.to_dict(),
            "createdWithVersion": self.createdWithVersion,
            "loadCount": self.loadCount,
        }


def export_tracked_loads(load_removal_session):
    filename = sanitize_filename(f"load-removal-session_{load_removal_session.sessionInfo.startedAt.date}")
    selected_file_path, selected_filter = QFileDialog.getSaveFileName(
        filter="JSON (*.json);;Excel Document (*.xlsx)", dir=filename
    )

    data_format = None

    match selected_filter:
        case "JSON (*.json)":
            data_format = "json"
        case "Excel Document (*.xlsx)":
            data_format = "excel"

    if selected_file_path:
        load_removal_session.export_loads(data_format, selected_file_path)
