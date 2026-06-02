from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MeetingStatus(str, Enum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class SpeakerTurn(BaseModel):
    speaker: str
    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None


class MeetingState(BaseModel):
    id: str
    status: MeetingStatus
    audio_path: Optional[str] = None
    num_speakers: Optional[int] = None
    error: Optional[str] = None
    transcript: List[SpeakerTurn] = Field(default_factory=list)
    speaker_names: Dict[str, str] = Field(default_factory=dict)
    mom_markdown: Optional[str] = None


class SpeakerUpdate(BaseModel):
    speakers: Dict[str, str]


class MeetingCreateResponse(BaseModel):
    id: str
    status: MeetingStatus


class MeetingStatusResponse(BaseModel):
    id: str
    status: MeetingStatus
    error: Optional[str] = None
    transcript: List[SpeakerTurn] = Field(default_factory=list)
    speaker_names: Dict[str, str] = Field(default_factory=dict)
    mom_markdown: Optional[str] = None
