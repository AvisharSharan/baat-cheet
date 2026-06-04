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
    speaker_embeddings: Dict[str, List[float]] = Field(default_factory=dict)
    voiceprint_status: str = "pending"
    voiceprint_error: Optional[str] = None
    mom_markdown: Optional[str] = None


class SpeakerUpdate(BaseModel):
    speakers: Dict[str, str]
    remember_voices: bool = False


class MeetingCreateResponse(BaseModel):
    id: str
    status: MeetingStatus


class MeetingStatusResponse(BaseModel):
    id: str
    status: MeetingStatus
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
            status=state.status,
            error=state.error,
            transcript=state.transcript,
            speaker_names=state.speaker_names,
            voiceprints_ready=bool(state.speaker_embeddings),
            voiceprint_status=state.voiceprint_status,
            voiceprint_error=state.voiceprint_error,
            mom_markdown=state.mom_markdown,
        )
