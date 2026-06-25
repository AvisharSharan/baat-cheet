from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


from pydantic import BaseModel, Field


class MeetingStatus(str, Enum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    TRANSLATING = "translating"
    GENERATING = "generating"
    READY = "ready"
    CANCELED = "canceled"
    FAILED = "failed"


class SpeakerTurn(BaseModel):
    speaker: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


class MeetingState(BaseModel):
    id: str
    name: str
    status: MeetingStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    audio_path: str | None = None
    num_speakers: int | None = None
    speaker_labels_enabled: bool = True
    error: str | None = None
    visible_in_history: bool = True
    transcript: list[SpeakerTurn] = Field(default_factory=list)
    speaker_names: dict[str, str] = Field(default_factory=dict)
    speaker_embeddings: dict[str, list[float]] = Field(default_factory=dict)
    voiceprint_status: str = "pending"
    voiceprint_error: str | None = None
    mom_markdown: str | None = None


class SpeakerUpdate(BaseModel):
    speakers: dict[str, str]
    remember_voices: bool = False


class TranscriptUpdate(BaseModel):
    index: int
    text: str


class MomGenerateRequest(BaseModel):
    mom_type: str = "auto"


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
    completed_at: datetime | None = None
    speakers: list[str] = Field(default_factory=list)
    transcript_turns: int = 0
    word_count: int = 0
    mom_available: bool = False
    speaker_labels_enabled: bool = True

    @classmethod
    def from_state(cls, state: "MeetingState") -> "MeetingHistoryItem":
        labels = set()
        if state.speaker_labels_enabled:
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
            speaker_labels_enabled=state.speaker_labels_enabled,
        )


class MeetingStatusResponse(BaseModel):
    id: str
    name: str
    status: MeetingStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    transcript: list[SpeakerTurn] = Field(default_factory=list)
    speaker_names: dict[str, str] = Field(default_factory=dict)
    speaker_labels_enabled: bool = True
    voiceprints_ready: bool = False
    voiceprint_status: str = "pending"
    voiceprint_error: str | None = None
    mom_markdown: str | None = None

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
            speaker_labels_enabled=state.speaker_labels_enabled,
            voiceprints_ready=bool(state.speaker_embeddings),
            voiceprint_status=state.voiceprint_status,
            voiceprint_error=state.voiceprint_error,
            mom_markdown=state.mom_markdown,
        )


class SettingsResponse(BaseModel):
    mom_provider: str = "ollama"
    ollama_base_url: str = ""
    ollama_model: str = ""
    hosted_api_url: str = ""
    hosted_api_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    hosted_api_configured: bool = False
    mom_max_tokens: str = "1200"
    ollama_num_ctx: str = "32768"
    ollama_num_gpu: str = "0"
    transcription_provider: str = "local"
    whisper_model: str = "base"
    whisper_device: str = "cuda"
    live_whisper_model: str = "base"
    indic_conformer_model: str = "ai4bharat/indic-conformer-600m-multilingual"
    indic_conformer_language: str = "hi"
    indic_conformer_decoder: str = "ctc"
    indic_conformer_device: str = "cuda"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_stt_mode: str = "transcribe"
    sarvam_language_code: str = "hi-IN"
    diarization_provider: str = "pyannote"
    voiceprinting_enabled: str = "1"


class SettingsUpdateRequest(BaseModel):
    mom_provider: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    hosted_api_url: str | None = None
    hosted_api_model: str | None = None
    hosted_api_key: str | None = None
    mom_max_tokens: str | None = None
    ollama_num_ctx: str | None = None
    ollama_num_gpu: str | None = None
    transcription_provider: str | None = None
    whisper_model: str | None = None
    whisper_device: str | None = None
    live_whisper_model: str | None = None
    indic_conformer_model: str | None = None
    indic_conformer_language: str | None = None
    indic_conformer_decoder: str | None = None
    indic_conformer_device: str | None = None
    sarvam_stt_model: str | None = None
    sarvam_stt_mode: str | None = None
    sarvam_language_code: str | None = None
    diarization_provider: str | None = None
    voiceprinting_enabled: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
