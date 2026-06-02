from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Dict

from .models import MeetingState


class MeetingStore:
    def __init__(self) -> None:
        self._meetings: Dict[str, MeetingState] = {}
        self._lock = RLock()

    def add(self, meeting: MeetingState) -> None:
        with self._lock:
            self._meetings[meeting.id] = meeting

    def get(self, meeting_id: str) -> MeetingState:
        with self._lock:
            meeting = self._meetings.get(meeting_id)
            if meeting is None:
                raise KeyError(meeting_id)
            return meeting

    def update(self, meeting: MeetingState) -> None:
        with self._lock:
            if meeting.id not in self._meetings:
                raise KeyError(meeting.id)
            self._meetings[meeting.id] = meeting


def delete_temp_file(path: str | None) -> None:
    if not path:
        return
    target = Path(path)
    if target.exists() and target.is_file():
        target.unlink()
