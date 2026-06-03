from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import List

from app.models import SpeakerTurn


class TranscriptionError(RuntimeError):
    pass


class LocalWhisperTranscriptionClient:
    def __init__(
        self,
        model: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        self.model = model or os.getenv("LOCAL_WHISPER_MODEL", "small")
        self.device = device or os.getenv("LOCAL_WHISPER_DEVICE", "auto")
        self.compute_type = compute_type or os.getenv("LOCAL_WHISPER_COMPUTE_TYPE", "int8")

    async def transcribe(self, audio_path: str, num_speakers: int | None = None) -> List[SpeakerTurn]:
        del num_speakers
        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: str) -> List[SpeakerTurn]:
        try:
            whisper_model = _load_whisper_model(self.model, self.device, self.compute_type)
        except ImportError as exc:
            raise TranscriptionError("faster-whisper is not installed.") from exc

        segments, _ = whisper_model.transcribe(
            audio_path,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        )

        turns = [
            SpeakerTurn(
                speaker="Speaker 1",
                text=segment.text.strip(),
                start_ms=int(segment.start * 1000),
                end_ms=int(segment.end * 1000),
            )
            for segment in segments
            if segment.text and segment.text.strip()
        ]
        if not turns:
            raise TranscriptionError("No transcript text was found in the audio.")
        return turns


@lru_cache(maxsize=2)
def _load_whisper_model(model: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    resolved_device = _resolve_whisper_device(device)
    return WhisperModel(model, device=resolved_device, compute_type=compute_type)


def _resolve_whisper_device(device: str) -> str:
    normalized = device.strip().lower()
    if normalized != "auto":
        return normalized
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
