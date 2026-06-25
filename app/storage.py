from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


from .models import MeetingState

logger = logging.getLogger(__name__)


class MeetingStore:
    def __init__(self, path: str | Path | None = None) -> None:
        default_path = Path(os.getenv("MOM_MEETINGS_PATH", "data/meetings.json"))
        self._path = Path(path) if path is not None else default_path
        self._meetings: dict[str, MeetingState] = {}
        self._lock = RLock()
        self._load()

    def add(self, meeting: MeetingState) -> None:
        with self._lock:
            # Store a copy so external mutations don't silently bypass update().
            self._meetings[meeting.id] = meeting.model_copy(deep=True)
            self._save()

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
            self._save()

    def delete(self, meeting_id: str) -> MeetingState:
        with self._lock:
            meeting = self._meetings.pop(meeting_id, None)
            if meeting is None:
                raise KeyError(meeting_id)
            self._save()
            return meeting.model_copy(deep=True)

    def clear(self) -> list[MeetingState]:
        with self._lock:
            meetings = [meeting.model_copy(deep=True) for meeting in self._meetings.values()]
            self._meetings.clear()
            self._save()
            return meetings

    def list(self) -> list[MeetingState]:
        with self._lock:
            meetings = [
                meeting.model_copy(deep=True)
                for meeting in self._meetings.values()
                if meeting.visible_in_history
            ]
        return sorted(meetings, key=lambda meeting: meeting.updated_at, reverse=True)

    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                return
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                meetings = payload.get("meetings", payload)
                self._meetings = {
                    meeting.id: meeting
                    for meeting in (MeetingState.model_validate(item) for item in meetings)
                }
            except Exception:
                logger.warning("Could not load meeting history from %s", self._path, exc_info=True)
                self._meetings = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meetings": [
                meeting.model_dump(mode="json")
                for meeting in sorted(self._meetings.values(), key=lambda item: item.updated_at, reverse=True)
            ]
        }
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self._path)


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
