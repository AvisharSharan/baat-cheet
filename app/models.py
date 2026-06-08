from __future__ import annotations

from datetime import datetime, timezone
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
    name: str
    status: MeetingStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    audio_path: Optional[str] = None
    num_speakers: Optional[int] = None
    error: Optional[str] = None
    visible_in_history: bool = True
    transcript: List[SpeakerTurn] = Field(default_factory=list)
    speaker_names: Dict[str, str] = Field(default_factory=dict)
    speaker_embeddings: Dict[str, List[float]] = Field(default_factory=dict)
    voiceprint_status: str = "pending"
    voiceprint_error: Optional[str] = None
    mom_markdown: Optional[str] = None


class SpeakerUpdate(BaseModel):
    speakers: Dict[str, str]
    remember_voices: bool = False


class MeetingCreateResponse(BaseModel):
    id: str
    name: str
    status: MeetingStatus


class MeetingHistoryItem(BaseModel):
    id: str
    name: str
    status: MeetingStatus
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    speakers: List[str] = Field(default_factory=list)
    transcript_turns: int = 0
    word_count: int = 0
    mom_available: bool = False

    @classmethod
    def from_state(cls, state: "MeetingState") -> "MeetingHistoryItem":
        labels = {
            state.speaker_names.get(turn.speaker, turn.speaker)
            for turn in state.transcript
        }
        return cls(
            id=state.id,
            name=state.name,
            status=state.status,
            created_at=state.created_at,
            updated_at=state.updated_at,
            completed_at=state.completed_at,
            speakers=sorted(labels),
            transcript_turns=len(state.transcript),
            word_count=sum(len(turn.text.split()) for turn in state.transcript),
            mom_available=bool(state.mom_markdown),
        )


class MeetingStatusResponse(BaseModel):
    id: str
    name: str
    status: MeetingStatus
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    transcript: List[SpeakerTurn] = Field(default_factory=list)
    speaker_names: Dict[str, str] = Field(default_factory=dict)
    voiceprints_ready: bool = False
    voiceprint_status: str = "pending"
    voiceprint_error: Optional[str] = None
    mom_markdown: Optional[str] = None

    model_config = {"populate_by_name": True}

    @classmethod
    def from_state(cls, state: "MeetingState") -> "MeetingStatusResponse":
        """Construct a response from internal state, explicitly excluding
        server-only fields like audio_path and num_speakers."""
        return cls(
            id=state.id,
            name=state.name,
            status=state.status,
            created_at=state.created_at,
            updated_at=state.updated_at,
            completed_at=state.completed_at,
            error=state.error,
            transcript=state.transcript,
            speaker_names=state.speaker_names,
            voiceprints_ready=bool(state.speaker_embeddings),
            voiceprint_status=state.voiceprint_status,
            voiceprint_error=state.voiceprint_error,
            mom_markdown=state.mom_markdown,
        )
