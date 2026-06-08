from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
from pathlib import Path
from threading import RLock
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Iterable, List, Protocol

from app.models import SpeakerTurn


class TranscriptionError(RuntimeError):
    pass


class TranscriptionClient(Protocol):
    async def transcribe(self, audio_path: str, num_speakers: int | None = None) -> List[SpeakerTurn]:
        ...


_PYANNOTE_PIPELINE_CACHE: Dict[str, Any] = {}
_WHISPER_MODEL_CACHE: Dict[str, Any] = {}
_WHISPER_MODEL_LOCK = RLock()


def create_transcription_client(provider: str | None = None) -> TranscriptionClient:
    selected = (provider or os.getenv("TRANSCRIPTION_PROVIDER") or "local").strip().lower()
    if selected in {"local", "open_source", "open-source", "faster_whisper", "faster-whisper"}:
        return FasterWhisperPyannoteTranscriptionClient()
    raise TranscriptionError(f"Unsupported transcription provider: {selected}. Use TRANSCRIPTION_PROVIDER=local.")


class FasterWhisperPyannoteTranscriptionClient:
    def __init__(
        self,
        *,
        whisper_model: str | None = None,
        whisper_device: str | None = None,
        whisper_compute_type: str | None = None,
        pyannote_model: str | None = None,
        hf_token: str | None = None,
    ) -> None:
        self.whisper_model = whisper_model or os.getenv("FASTER_WHISPER_MODEL", "base")
        self.whisper_device = whisper_device or os.getenv("FASTER_WHISPER_DEVICE", "cpu")
        self.whisper_compute_type = whisper_compute_type or os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
        self.pyannote_model = pyannote_model or os.getenv("PYANNOTE_DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")
        self.hf_token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

    async def transcribe(self, audio_path: str, num_speakers: int | None = None) -> List[SpeakerTurn]:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, num_speakers)

    def _transcribe_sync(self, audio_path: str, num_speakers: int | None = None) -> List[SpeakerTurn]:
        segments = self._transcribe_with_faster_whisper(audio_path)
        if num_speakers == 1 or os.getenv("DIARIZATION_PROVIDER", "pyannote").strip().lower() in {"none", "off", "0", "false"}:
            return [
                SpeakerTurn(
                    speaker="Speaker 1",
                    text=str(segment["text"]),
                    start_ms=_first_int(segment, ("start_ms",)),
                    end_ms=_first_int(segment, ("end_ms",)),
                )
                for segment in segments
            ]
        diarization = self._diarize_with_pyannote(audio_path, num_speakers)
        return _assign_speakers_to_segments(segments, diarization)

    def _transcribe_with_faster_whisper(self, audio_path: str) -> List[Dict[str, Any]]:
        model = _get_faster_whisper_model(
            self.whisper_model,
            self.whisper_device,
            self.whisper_compute_type,
        )
        segments, _ = model.transcribe(
            audio_path,
            beam_size=_env_int("FASTER_WHISPER_BEAM_SIZE", 1),
            vad_filter=_env_bool("FASTER_WHISPER_VAD_FILTER", True),
            word_timestamps=_env_bool("FASTER_WHISPER_WORD_TIMESTAMPS", False),
        )
        records = [
            {
                "text": segment.text.strip(),
                "start_ms": int(segment.start * 1000),
                "end_ms": int(segment.end * 1000),
            }
            for segment in segments
            if getattr(segment, "text", "").strip()
        ]
        if not records:
            raise TranscriptionError("faster-whisper did not return any transcript segments.")
        return records

    def _diarize_with_pyannote(self, audio_path: str, num_speakers: int | None = None) -> List[Dict[str, Any]]:
        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise TranscriptionError(
                "pyannote.audio is not installed. Install the open-source speech requirements to use TRANSCRIPTION_PROVIDER=local."
            ) from exc

        pipeline = _get_pyannote_pipeline(Pipeline, self.pyannote_model, self.hf_token)
        kwargs: Dict[str, Any] = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers
        audio_input = _pyannote_audio_input(audio_path)
        try:
            output = pipeline(audio_input, **kwargs)
        except TypeError:
            output = pipeline(audio_input)

        speaker_diarization = getattr(output, "speaker_diarization", output)
        diarization = []
        for item in speaker_diarization:
            turn, _, speaker = item if len(item) == 3 else (item[0], None, item[1])
            diarization.append(
                {
                    "speaker": str(speaker),
                    "start_ms": int(float(turn.start) * 1000),
                    "end_ms": int(float(turn.end) * 1000),
                }
            )
        if not diarization:
            raise TranscriptionError("pyannote diarization did not return any speaker segments.")
        return diarization


def transcribe_live_preview(audio_path: str) -> List[SpeakerTurn]:
    model_name = os.getenv("LIVE_WHISPER_MODEL") or "tiny"
    device = os.getenv("LIVE_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("LIVE_WHISPER_COMPUTE_TYPE", "int8")
    try:
        model = _get_faster_whisper_model(model_name, device, compute_type)
    except TranscriptionError:
        if device.strip().lower() == "cpu":
            raise
        model = _get_faster_whisper_model(model_name, "cpu", "int8")
    segments, _ = model.transcribe(
        audio_path,
        beam_size=_env_int("LIVE_WHISPER_BEAM_SIZE", 1),
        vad_filter=_env_bool("LIVE_WHISPER_VAD_FILTER", False),
        condition_on_previous_text=False,
    )
    return [
        SpeakerTurn(
            speaker="Live",
            text=segment.text.strip(),
            start_ms=int(segment.start * 1000),
            end_ms=int(segment.end * 1000),
        )
        for segment in segments
        if getattr(segment, "text", "").strip()
    ]


def _get_faster_whisper_model(model_name: str, device: str, compute_type: str) -> Any:
    cache_key = f"{model_name}|{device}|{compute_type}"
    with _WHISPER_MODEL_LOCK:
        if cache_key in _WHISPER_MODEL_CACHE:
            return _WHISPER_MODEL_CACHE[cache_key]

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper is not installed. Install the open-source speech requirements to use TRANSCRIPTION_PROVIDER=local."
            ) from exc

        try:
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as exc:
            if device.strip().lower() != "cpu" and _is_cuda_runtime_error(exc):
                raise TranscriptionError(
                    "CUDA runtime libraries are missing for faster-whisper. Install CUDA/cuBLAS/cuDNN or set "
                    "FASTER_WHISPER_DEVICE=cpu. Live captions can use CPU with LIVE_WHISPER_DEVICE=cpu."
                ) from exc
            raise
        _WHISPER_MODEL_CACHE[cache_key] = model
        return model


def _is_cuda_runtime_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in ("cublas", "cudnn", "cuda", "cublas64_12.dll"))


def _get_pyannote_pipeline(pipeline_class: Any, checkpoint: str, token: str | None = None) -> Any:
    cache_key = f"{checkpoint}|{token or ''}|{id(pipeline_class)}"
    if cache_key in _PYANNOTE_PIPELINE_CACHE:
        return _PYANNOTE_PIPELINE_CACHE[cache_key]

    kwargs = {}
    token_arg = _pyannote_token_arg(pipeline_class)
    if token and token_arg:
        kwargs[token_arg] = token
    pipeline = pipeline_class.from_pretrained(checkpoint, **kwargs)
    device = os.getenv("PYANNOTE_DEVICE")
    if device and hasattr(pipeline, "to"):
        try:
            import torch

            pipeline.to(torch.device(device))
        except Exception as exc:
            raise TranscriptionError(f"Could not move pyannote pipeline to {device}.") from exc
    _PYANNOTE_PIPELINE_CACHE[cache_key] = pipeline
    return pipeline


def _pyannote_token_arg(pipeline_class: Any) -> str | None:
    signature = inspect.signature(pipeline_class.from_pretrained)
    if "token" in signature.parameters:
        return "token"
    if "use_auth_token" in signature.parameters:
        return "use_auth_token"
    return None


def _pyannote_audio_input(audio_path: str, sample_rate: int = 16000) -> Dict[str, Any]:
    try:
        import imageio_ffmpeg
        import torchaudio
    except ImportError as exc:
        raise TranscriptionError(
            "Local diarization requires imageio-ffmpeg and torchaudio to decode recordings for pyannote."
        ) from exc

    with NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        wav_path = Path(handle.name)

    try:
        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                audio_path,
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-vn",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "ffmpeg conversion failed").strip()
            raise TranscriptionError(f"Could not decode recording for diarization: {detail[-800:]}")

        waveform, decoded_sample_rate = torchaudio.load(str(wav_path))
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if int(decoded_sample_rate) != sample_rate:
            waveform = torchaudio.functional.resample(waveform, int(decoded_sample_rate), sample_rate)
        return {"waveform": waveform, "sample_rate": sample_rate}
    finally:
        wav_path.unlink(missing_ok=True)


def _assign_speakers_to_segments(
    segments: List[Dict[str, Any]],
    diarization: List[Dict[str, Any]],
) -> List[SpeakerTurn]:
    speaker_aliases: Dict[str, str] = {}
    turns: List[SpeakerTurn] = []
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start_ms = _first_int(segment, ("start_ms", "start"))
        end_ms = _first_int(segment, ("end_ms", "end"))
        raw_speaker = _best_overlap_speaker(start_ms, end_ms, diarization) or "Speaker 1"
        speaker = _canonical_speaker_label(raw_speaker, speaker_aliases)
        turns.append(SpeakerTurn(speaker=speaker, text=text, start_ms=start_ms, end_ms=end_ms))

    if not turns:
        raise TranscriptionError("No speaker transcript turns were produced from local transcription.")
    return _merge_adjacent_turns(turns)


def _best_overlap_speaker(start_ms: int | None, end_ms: int | None, diarization: List[Dict[str, Any]]) -> str | None:
    if start_ms is None or end_ms is None or end_ms <= start_ms:
        return str(diarization[0]["speaker"]) if diarization else None

    best_speaker = None
    best_overlap = 0
    for turn in diarization:
        diar_start = _first_int(turn, ("start_ms", "start")) or 0
        diar_end = _first_int(turn, ("end_ms", "end")) or diar_start
        overlap = max(0, min(end_ms, diar_end) - max(start_ms, diar_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(turn.get("speaker") or "")
    return best_speaker or None


def _canonical_speaker_label(raw_speaker: str, speaker_aliases: Dict[str, str]) -> str:
    if raw_speaker.lower().startswith("speaker "):
        return raw_speaker
    if raw_speaker not in speaker_aliases:
        speaker_aliases[raw_speaker] = f"Speaker {len(speaker_aliases) + 1}"
    return speaker_aliases[raw_speaker]


def _first_int(record: Dict[str, Any], keys: Iterable[str]) -> int | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value))
            except ValueError:
                continue
    return None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _merge_adjacent_turns(turns: List[SpeakerTurn]) -> List[SpeakerTurn]:
    merged: List[SpeakerTurn] = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker:
            previous = merged[-1]
            previous.text = f"{previous.text} {turn.text}".strip()
            previous.end_ms = turn.end_ms or previous.end_ms
        else:
            merged.append(turn)
    return merged
