from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from typing import AsyncIterator

from app.models import SpeakerTurn


class LiveTranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveTranscriptEvent:
    type: str
    text: str | None = None
    event: str | None = None


class SarvamLiveTranscriptionClient:
    def __init__(
        self,
        api_key: str | None = None,
        language_code: str | None = None,
        sample_rate: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("SARVAM_API_KEY")
        self.language_code = language_code or os.getenv("SARVAM_STREAM_LANGUAGE_CODE", "unknown")
        self.sample_rate = sample_rate or _env_int("SARVAM_STREAM_SAMPLE_RATE", 16000)
        self.model = os.getenv("SARVAM_STREAM_MODEL", "saaras:v3")
        self.mode = os.getenv("SARVAM_STREAM_MODE", "transcribe")
        if not self.api_key:
            raise LiveTranscriptionError("SARVAM_API_KEY is not configured.")

    async def stream(self, audio_chunks: AsyncIterator[bytes]) -> AsyncIterator[LiveTranscriptEvent]:
        try:
            from sarvamai import AsyncSarvamAI
        except ImportError as exc:
            raise LiveTranscriptionError("sarvamai package is not installed.") from exc

        client = AsyncSarvamAI(api_subscription_key=self.api_key)
        async with client.speech_to_text_streaming.connect(
            model=self.model,
            mode=self.mode,
            language_code=self.language_code,
            sample_rate=str(self.sample_rate),
            input_audio_codec="pcm_s16le",
            high_vad_sensitivity="true",
            vad_signals="true",
            flush_signal="true",
        ) as sarvam_ws:
            output_queue: asyncio.Queue[LiveTranscriptEvent | Exception | None] = asyncio.Queue()

            async def send_audio() -> None:
                try:
                    async for chunk in audio_chunks:
                        if not chunk:
                            continue
                        encoded = base64.b64encode(chunk).decode("ascii")
                        await sarvam_ws.transcribe(
                            audio=encoded,
                            encoding="audio/wav",
                            sample_rate=self.sample_rate,
                        )
                    await sarvam_ws.flush()
                except Exception as exc:
                    await output_queue.put(exc)

            async def receive_events() -> None:
                try:
                    async for message in sarvam_ws:
                        event = _normalize_sarvam_message(message)
                        if event:
                            await output_queue.put(event)
                except Exception as exc:
                    await output_queue.put(exc)
                finally:
                    await output_queue.put(None)

            sender = asyncio.create_task(send_audio())
            receiver = asyncio.create_task(receive_events())
            try:
                while True:
                    item = await output_queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    yield item
            finally:
                sender.cancel()
                receiver.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)


def live_event_to_turn(event: LiveTranscriptEvent, index: int) -> SpeakerTurn:
    return SpeakerTurn(
        speaker="Live",
        text=event.text or "",
        start_ms=None,
        end_ms=None,
    )


def _normalize_sarvam_message(message) -> LiveTranscriptEvent | None:
    message_type = getattr(message, "type", None)
    data = getattr(message, "data", None)
    if message_type == "data":
        text = getattr(data, "transcript", None)
        if text and text.strip():
            return LiveTranscriptEvent(type="transcript", text=text.strip())
    if message_type == "events":
        signal = getattr(data, "signal_type", None) or getattr(data, "event_type", None)
        return LiveTranscriptEvent(type="event", event=str(signal or "speech"))
    if message_type == "error":
        error = getattr(data, "error", None) or "Sarvam streaming transcription failed."
        raise LiveTranscriptionError(str(error))
    return None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise LiveTranscriptionError(f"{name} must be an integer.") from exc
