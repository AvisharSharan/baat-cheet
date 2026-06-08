from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Dict, List

from .models import MeetingState

logger = logging.getLogger(__name__)


class MeetingStore:
    def __init__(self) -> None:
        self._meetings: Dict[str, MeetingState] = {}
        self._lock = RLock()

    def add(self, meeting: MeetingState) -> None:
        with self._lock:
            # Store a copy so external mutations don't silently bypass update().
            self._meetings[meeting.id] = meeting.model_copy(deep=True)

    def get(self, meeting_id: str) -> MeetingState:
        with self._lock:
            meeting = self._meetings.get(meeting_id)
            if meeting is None:
                raise KeyError(meeting_id)
            # Return a copy: callers may mutate freely; changes only take effect
            # when they call update(), which prevents silent concurrent clobbers.
            return meeting.model_copy(deep=True)

    def update(self, meeting: MeetingState) -> None:
        with self._lock:
            if meeting.id not in self._meetings:
                raise KeyError(meeting.id)
            meeting.updated_at = datetime.now(timezone.utc)
            self._meetings[meeting.id] = meeting.model_copy(deep=True)

    def list(self) -> List[MeetingState]:
        with self._lock:
            meetings = [
                meeting.model_copy(deep=True)
                for meeting in self._meetings.values()
                if meeting.visible_in_history
            ]
        return sorted(meetings, key=lambda meeting: meeting.updated_at, reverse=True)


def delete_temp_file(path: str | None) -> None:
    if not path:
        return
    target = Path(path)
    if not target.exists():
        return
    if not target.is_file():
        logger.warning("delete_temp_file: path exists but is not a file, skipping: %s", path)
        return
    try:
        target.unlink()
    except OSError:
        logger.warning("delete_temp_file: could not delete %s", path, exc_info=True)
