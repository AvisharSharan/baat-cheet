from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import logging
import os
import re
import subprocess
import sys
import time
import warnings
import wave
from pathlib import Path
from threading import RLock
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, Dict, Iterable, List, Protocol

from app.models import SpeakerTurn

logger = logging.getLogger(__name__)

_LOCAL_PROVIDER_ALIASES = {"local", "open_source", "open-source", "faster_whisper", "faster-whisper"}
_INDIC_PROVIDER_ALIASES = {"indic", "indic_conformer", "indic-conformer", "ai4bharat"}
_SARVAM_PROVIDER_ALIASES = {"sarvam", "saaras", "sarvam-saaras", "saaras-v3"}


class TranscriptionError(RuntimeError):
    pass


class TranscriptionClient(Protocol):
    async def transcribe(
        self,
        audio_path: str,
        num_speakers: int | None = None,
        speaker_labels_enabled: bool = True,
    ) -> List[SpeakerTurn]:
        ...


_PYANNOTE_PIPELINE_CACHE: Dict[str, Any] = {}
_WHISPER_MODEL_CACHE: Dict[str, Any] = {}
_INDIC_CONFORMER_MODEL_CACHE: Dict[str, Any] = {}
_WHISPER_MODEL_LOCK = RLock()
_INDIC_CONFORMER_MODEL_LOCK = RLock()
_INDIC_CONFORMER_LANGUAGES = {
    "as",
    "bn",
    "brx",
    "doi",
    "gu",
    "hi",
    "kn",
    "kok",
    "ks",
    "mai",
    "ml",
    "mni",
    "mr",
    "ne",
    "or",
    "pa",
    "sa",
    "sat",
    "sd",
    "ta",
    "te",
    "ur",
}


def create_transcription_client(provider: str | None = None) -> TranscriptionClient:
    selected = (provider or os.getenv("TRANSCRIPTION_PROVIDER") or "local").strip().lower()
    if selected in _LOCAL_PROVIDER_ALIASES:
        return FasterWhisperPyannoteTranscriptionClient()
    if selected in _INDIC_PROVIDER_ALIASES:
        return IndicConformerPyannoteTranscriptionClient()
    if selected in _SARVAM_PROVIDER_ALIASES:
        return SarvamSaarasTranscriptionClient()
    raise TranscriptionError(
        "Unsupported transcription provider: "
        f"{selected}. Use TRANSCRIPTION_PROVIDER=local, TRANSCRIPTION_PROVIDER=indic-conformer, "
        "or TRANSCRIPTION_PROVIDER=sarvam."
    )


def sarvam_provider_selected(provider: str | None = None) -> bool:
    selected = (provider or os.getenv("TRANSCRIPTION_PROVIDER") or "local").strip().lower()
    return selected in _SARVAM_PROVIDER_ALIASES


def preload_transcription_runtime() -> None:
    """Load and lightly warm the active local speech stack.

    This runs in a background startup task so the first real recording does not
    pay the full model import/load/JIT cost after the user clicks Stop.
    """
    _quiet_speech_runtime_warnings()
    provider = (os.getenv("TRANSCRIPTION_PROVIDER") or "local").strip().lower()
    if provider in _LOCAL_PROVIDER_ALIASES:
        _preload_faster_whisper_runtime()
        return
    if provider in _INDIC_PROVIDER_ALIASES:
        _preload_indic_conformer_runtime()
        return
    if provider in _SARVAM_PROVIDER_ALIASES:
        logger.info("Skipping local speech runtime preload for Sarvam provider.")
        return
    logger.info("Skipping speech runtime preload for unsupported provider '%s'.", provider)


def _preload_faster_whisper_runtime() -> None:
    model_name = os.getenv("FASTER_WHISPER_MODEL", "base")
    device = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    logger.info("Preloading faster-whisper model '%s' on %s.", model_name, device)
    _get_faster_whisper_model(model_name, device, compute_type)
    if os.getenv("DIARIZATION_PROVIDER", "pyannote").strip().lower() not in {"none", "off", "0", "false"}:
        try:
            from pyannote.audio import Pipeline

            client = FasterWhisperPyannoteTranscriptionClient()
            logger.info("Preloading pyannote diarization pipeline.")
            _get_pyannote_pipeline(Pipeline, client.pyannote_model, client.hf_token)
        except Exception as exc:
            logger.warning("Could not preload pyannote diarization: %s", _short_error(exc))


def _preload_indic_conformer_runtime() -> None:
    client = IndicConformerPyannoteTranscriptionClient()
    device = _effective_indic_conformer_device(client.device)
    logger.info("Preloading Indic Conformer model '%s' on %s.", client.model_name, device)
    with _quiet_preload_output():
        _get_indic_conformer_model(client.model_name, device, client.hf_token)
    if os.getenv("MOM_PRELOAD_DUMMY_AUDIO", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    with NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        wav_path = Path(handle.name)
    try:
        _write_silence_wav(wav_path, duration_s=0.6)
        try:
            with _quiet_preload_output():
                _transcribe_with_indic_conformer(
                    str(wav_path),
                    client.model_name,
                    client.language,
                    client.decoder,
                    device,
                    client.hf_token,
                )
        except Exception as exc:
            logger.info("Indic Conformer dummy warmup finished without transcript: %s", _short_error(exc))
    finally:
        _unlink_with_retry(wav_path)


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
        self.pyannote_model = "pyannote/speaker-diarization-community-1"
        self.hf_token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

    async def transcribe(
        self,
        audio_path: str,
        num_speakers: int | None = None,
        speaker_labels_enabled: bool = True,
    ) -> List[SpeakerTurn]:
        if not self._should_predecode_for_diarization(num_speakers, speaker_labels_enabled):
            return await self._transcribe_internal(audio_path, num_speakers, speaker_labels_enabled)

        # Pre-decode once for the diarized path so pyannote can consume a stable
        # WAV while Whisper and diarization run against the same audio timeline.
        is_wav_16k = audio_path.lower().endswith(".wav") and await asyncio.to_thread(self._is_16k_wav, audio_path)

        if is_wav_16k:
            return await self._transcribe_internal(audio_path, num_speakers, speaker_labels_enabled)

        with NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            wav_path = Path(handle.name)

        try:
            await asyncio.to_thread(_decode_audio_for_local_processing, audio_path, str(wav_path))
            return await self._transcribe_internal(str(wav_path), num_speakers, speaker_labels_enabled)
        finally:
            _unlink_with_retry(wav_path)

    def _should_predecode_for_diarization(self, num_speakers: int | None, speaker_labels_enabled: bool) -> bool:
        diarization_enabled = os.getenv("DIARIZATION_PROVIDER", "pyannote").strip().lower() not in {"none", "off", "0", "false"}
        return speaker_labels_enabled and num_speakers != 1 and diarization_enabled

    def _is_16k_wav(self, path: str) -> bool:
        try:
            import wave
            with wave.open(path, "rb") as f:
                return f.getframerate() == 16000 and f.getnchannels() == 1
        except Exception:
            return False

    async def _transcribe_internal(
        self,
        audio_path: str,
        num_speakers: int | None = None,
        speaker_labels_enabled: bool = True,
    ) -> List[SpeakerTurn]:
        whisper_task = asyncio.to_thread(self._transcribe_with_faster_whisper, audio_path)

        if not speaker_labels_enabled:
            segments = await whisper_task
            return _segments_to_plain_transcript(segments)

        if num_speakers == 1 or os.getenv("DIARIZATION_PROVIDER", "pyannote").strip().lower() in {"none", "off", "0", "false"}:
            segments = await whisper_task
            return [
                SpeakerTurn(
                    speaker="Speaker 1",
                    text=str(segment["text"]),
                    start_ms=_first_int(segment, ("start_ms",)),
                    end_ms=_first_int(segment, ("end_ms",)),
                )
                for segment in segments
            ]

        diarization_task = asyncio.to_thread(self._diarize_with_pyannote, audio_path, num_speakers)

        segments, diarization = await asyncio.gather(whisper_task, diarization_task)
        return _assign_speakers_to_segments(segments, diarization)

    def _transcribe_with_faster_whisper(self, audio_path: str) -> List[Dict[str, Any]]:
        transcribe_options = {
            "beam_size": _env_int("FASTER_WHISPER_BEAM_SIZE", 1),
            "vad_filter": _env_bool("FASTER_WHISPER_VAD_FILTER", True),
            "word_timestamps": _env_bool("FASTER_WHISPER_WORD_TIMESTAMPS", False),
        }
        segments = _transcribe_with_device_fallback(
            audio_path,
            self.whisper_model,
            self.whisper_device,
            self.whisper_compute_type,
            transcribe_options,
            allow_cpu_fallback=_env_bool("FASTER_WHISPER_CPU_FALLBACK", True),
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


class IndicConformerPyannoteTranscriptionClient(FasterWhisperPyannoteTranscriptionClient):
    def __init__(
        self,
        *,
        model_name: str | None = None,
        language: str | None = None,
        decoder: str | None = None,
        device: str | None = None,
        hf_token: str | None = None,
    ) -> None:
        super().__init__(hf_token=hf_token)
        self.model_name = model_name or os.getenv("INDIC_CONFORMER_MODEL", "ai4bharat/indic-conformer-600m-multilingual")
        self.language = (language or os.getenv("INDIC_CONFORMER_LANGUAGE", "hi")).strip().lower()
        self.decoder = (decoder or os.getenv("INDIC_CONFORMER_DECODER", "ctc")).strip().lower()
        self.device = (device or os.getenv("INDIC_CONFORMER_DEVICE", "cpu")).strip().lower()

    async def transcribe(
        self,
        audio_path: str,
        num_speakers: int | None = None,
        speaker_labels_enabled: bool = True,
    ) -> List[SpeakerTurn]:
        try:
            with NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                wav_path = Path(handle.name)

            await asyncio.to_thread(_decode_audio_for_local_processing, audio_path, str(wav_path))
            text, duration_ms = await asyncio.to_thread(self._transcribe_wav_text, str(wav_path))

            if not speaker_labels_enabled:
                return [SpeakerTurn(speaker="", text=text, start_ms=0, end_ms=duration_ms)]

            diarization_enabled = (
                num_speakers != 1
                and os.getenv("DIARIZATION_PROVIDER", "pyannote").strip().lower() not in {"none", "off", "0", "false"}
            )
            if not diarization_enabled:
                return [SpeakerTurn(speaker="Speaker 1", text=text, start_ms=0, end_ms=duration_ms)]

            try:
                diarization = await asyncio.to_thread(self._diarize_with_pyannote, str(wav_path), num_speakers)
            except Exception:
                logger.warning("Indic Conformer transcription succeeded, but diarization failed; returning plain transcript.", exc_info=True)
                return [SpeakerTurn(speaker="Speaker 1", text=text, start_ms=0, end_ms=duration_ms)]

            return _assign_text_to_diarization(text, diarization, duration_ms, expected_speakers=num_speakers)
        finally:
            if "wav_path" in locals():
                _unlink_with_retry(wav_path)

    def _transcribe_wav_text(self, wav_path: str) -> tuple[str, int | None]:
        duration_ms = _wav_duration_ms(wav_path)
        text = _transcribe_with_indic_conformer(
            wav_path,
            self.model_name,
            self.language,
            self.decoder,
            self.device,
            self.hf_token,
        )
        text = text.strip()
        if not text:
            raise TranscriptionError("Indic Conformer did not return transcript text.")
        return text, duration_ms


class SarvamSaarasTranscriptionClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        mode: str | None = None,
        language_code: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_SUBSCRIPTION_KEY")
        self.model = model or os.getenv("SARVAM_STT_MODEL", "saaras:v3")
        self.mode = (mode or os.getenv("SARVAM_STT_MODE", "transcribe")).strip().lower()
        self.language_code = language_code or os.getenv("SARVAM_LANGUAGE_CODE", "hi-IN")

    async def transcribe(
        self,
        audio_path: str,
        num_speakers: int | None = None,
        speaker_labels_enabled: bool = True,
    ) -> List[SpeakerTurn]:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, num_speakers, speaker_labels_enabled)

    def _transcribe_sync(
        self,
        audio_path: str,
        num_speakers: int | None,
        speaker_labels_enabled: bool,
    ) -> List[SpeakerTurn]:
        if not self.api_key:
            raise TranscriptionError("Set SARVAM_API_KEY to use TRANSCRIPTION_PROVIDER=sarvam.")
        if self.mode not in {"transcribe", "translate", "verbatim", "translit", "codemix"}:
            raise TranscriptionError("SARVAM_STT_MODE must be transcribe, translate, verbatim, translit, or codemix.")

        try:
            from sarvamai import SarvamAI
        except ImportError as exc:
            raise TranscriptionError("sarvamai is not installed. Run: python -m pip install -r requirements.txt") from exc

        with TemporaryDirectory(prefix="sarvam-stt-") as output_dir:
            client = SarvamAI(api_subscription_key=self.api_key)
            job_kwargs: Dict[str, Any] = {
                "model": self.model,
                "mode": self.mode,
                "language_code": self.language_code,
                "with_diarization": bool(speaker_labels_enabled and num_speakers != 1),
            }
            if speaker_labels_enabled and num_speakers and num_speakers > 1:
                job_kwargs["num_speakers"] = num_speakers

            job = client.speech_to_text_job.create_job(**job_kwargs)
            job.upload_files(file_paths=[audio_path])
            job.start()
            job.wait_until_complete()
            file_results = _sarvam_file_results(job)
            failed = file_results.get("failed") or []
            successful = file_results.get("successful") or []
            if failed and not successful:
                first = failed[0]
                message = first.get("error_message") if isinstance(first, dict) else str(first)
                raise TranscriptionError(f"Sarvam transcription failed: {message or 'unknown error'}")
            if not successful:
                raise TranscriptionError("Sarvam transcription finished without a successful output file.")

            job.download_outputs(output_dir=output_dir)
            payload = _load_first_sarvam_output(Path(output_dir))

        return _sarvam_payload_to_turns(payload, speaker_labels_enabled=speaker_labels_enabled)


class SarvamLiveCaptionSession:
    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        api_key: str | None = None,
        model: str | None = None,
        mode: str | None = None,
        language_code: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_SUBSCRIPTION_KEY")
        self.model = model or os.getenv("SARVAM_STT_MODEL", "saaras:v3")
        self.mode = (mode or os.getenv("SARVAM_STT_MODE", "transcribe")).strip().lower()
        self.language_code = language_code or os.getenv("SARVAM_LANGUAGE_CODE", "hi-IN")
        self.sample_rate = sample_rate
        self._client: Any = None
        self._connection: Any = None
        self._ws: Any = None

    async def __aenter__(self) -> "SarvamLiveCaptionSession":
        if not self.api_key:
            raise TranscriptionError("Set SARVAM_API_KEY to use Sarvam live captions.")
        if self.mode not in {"transcribe", "translate", "verbatim", "translit", "codemix"}:
            raise TranscriptionError("SARVAM_STT_MODE must be transcribe, translate, verbatim, translit, or codemix.")
        try:
            from sarvamai import AsyncSarvamAI
        except ImportError as exc:
            raise TranscriptionError("sarvamai is not installed. Run: python -m pip install -r requirements.txt") from exc

        self._client = AsyncSarvamAI(api_subscription_key=self.api_key)
        connect_kwargs: Dict[str, Any] = {
            "model": self.model,
            "mode": self.mode,
            "sample_rate": self.sample_rate,
            "input_audio_codec": "wav",
            "high_vad_sensitivity": _env_bool("SARVAM_LIVE_HIGH_VAD_SENSITIVITY", True),
            "vad_signals": True,
            "flush_signal": True,
        }
        if self.mode != "translate":
            connect_kwargs["language_code"] = self.language_code
        self._connection = self._client.speech_to_text_streaming.connect(**connect_kwargs)
        self._ws = await self._connection.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._connection:
            await self._connection.__aexit__(exc_type, exc, tb)

    async def send_pcm(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or not self._ws:
            return
        payload = {
            "audio": _pcm_to_wav_base64(pcm_bytes, self.sample_rate),
            "encoding": "audio/wav",
            "sample_rate": self.sample_rate,
        }
        await self._ws.transcribe(**payload)

    async def flush(self) -> None:
        if self._ws and hasattr(self._ws, "flush"):
            await self._ws.flush()

    async def receive_turns(self) -> List[SpeakerTurn]:
        if not self._ws:
            return []
        message = await self._ws.recv()
        return _sarvam_stream_message_to_turns(message)


def _transcribe_with_indic_conformer(
    audio_path: str,
    model_name: str,
    language: str,
    decoder: str,
    device: str,
    hf_token: str | None,
) -> str:
    if decoder not in {"ctc", "rnnt"}:
        raise TranscriptionError("INDIC_CONFORMER_DECODER must be either 'ctc' or 'rnnt'.")
    if language not in _INDIC_CONFORMER_LANGUAGES:
        raise TranscriptionError(
            f"Unsupported INDIC_CONFORMER_LANGUAGE '{language}'. "
            f"Use one of: {', '.join(sorted(_INDIC_CONFORMER_LANGUAGES))}."
        )

    try:
        import torch
        import torchaudio
    except ImportError as exc:
        raise TranscriptionError(
            "Indic Conformer requires torch and torchaudio. Install the open-source speech requirements."
        ) from exc

    _quiet_speech_runtime_warnings()
    device = _effective_indic_conformer_device(device)
    model = _get_indic_conformer_model(model_name, device, hf_token)
    waveform, sample_rate = torchaudio.load(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if int(sample_rate) != 16000:
        waveform = torchaudio.functional.resample(waveform, int(sample_rate), 16000)

    model_device = _torch_device(device)
    if model_device is not None:
        waveform = waveform.to(model_device)

    try:
        with torch.inference_mode():
            output = model(waveform, language, decoder)
    except Exception as exc:
        if device != "cpu":
            logger.warning("Indic Conformer failed on %s; retrying on CPU. Reason: %s", device, _short_error(exc))
            model = _get_indic_conformer_model(model_name, "cpu", hf_token)
            with torch.inference_mode():
                output = model(waveform.cpu(), language, decoder)
        else:
            raise
    return _normalize_indic_conformer_output(output)


def _get_indic_conformer_model(model_name: str, device: str, hf_token: str | None) -> Any:
    cache_key = f"{model_name}|{device}|{hf_token or ''}"
    with _INDIC_CONFORMER_MODEL_LOCK:
        if cache_key in _INDIC_CONFORMER_MODEL_CACHE:
            return _INDIC_CONFORMER_MODEL_CACHE[cache_key]

        try:
            import torch
            from transformers import AutoModel
        except ImportError as exc:
            raise TranscriptionError(
                "Indic Conformer requires transformers, torch, and torchaudio. Install the open-source speech requirements."
            ) from exc

        kwargs: Dict[str, Any] = {"trust_remote_code": True}
        if hf_token:
            kwargs["token"] = hf_token

        try:
            model = AutoModel.from_pretrained(model_name, **kwargs)
        except Exception as exc:
            raise TranscriptionError(
                f"Could not load Indic Conformer model '{model_name}'. "
                "Make sure you accepted the gated Hugging Face model terms and set HF_TOKEN."
            ) from exc

        torch_device = _torch_device(device)
        if torch_device is not None:
            try:
                model.to(torch_device)
            except Exception as exc:
                if _is_cuda_runtime_error(exc):
                    logger.warning("Could not move Indic Conformer to %s; using CPU instead.", device)
                else:
                    raise TranscriptionError(f"Could not move Indic Conformer to {device}.") from exc
        if hasattr(model, "eval"):
            model.eval()
        _INDIC_CONFORMER_MODEL_CACHE[cache_key] = model
        return model


def _torch_device(device: str) -> Any:
    selected = (device or "cpu").strip().lower()
    if not selected or selected == "cpu":
        return None
    try:
        import torch

        return torch.device(selected)
    except Exception:
        return None


def _normalize_indic_conformer_output(output: Any) -> str:
    if isinstance(output, str):
        return _clean_indic_conformer_text(output)
    if isinstance(output, (list, tuple)):
        text_parts = [
            _normalize_indic_conformer_output(item)
            for item in output
            if isinstance(item, (str, list, tuple, dict))
            or any(hasattr(item, attr) for attr in ("text", "transcription", "transcript", "pred_text", "prediction"))
        ]
        return " ".join(part for part in text_parts if part).strip()
    if isinstance(output, dict):
        for key in ("text", "transcription", "transcript", "pred_text", "prediction"):
            value = output.get(key)
            if value:
                return _normalize_indic_conformer_output(value)
        return ""
    for attr in ("text", "transcription", "transcript", "pred_text", "prediction"):
        value = getattr(output, attr, None)
        if value:
            return _normalize_indic_conformer_output(value)
    raise TranscriptionError(f"Unexpected Indic Conformer output type: {type(output).__name__}.")


def _clean_indic_conformer_text(text: str) -> str:
    return " ".join(text.replace("\u2581", " ").replace("\u00e2\u20ac\u2018", " ").split())


def transcribe_live_preview(audio_path: str) -> List[SpeakerTurn]:
    model_name = os.getenv("LIVE_WHISPER_MODEL") or "tiny"
    device = os.getenv("LIVE_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("LIVE_WHISPER_COMPUTE_TYPE", "int8")
    segments = _transcribe_with_device_fallback(
        audio_path,
        model_name,
        device,
        compute_type,
        {
            "beam_size": _env_int("LIVE_WHISPER_BEAM_SIZE", 1),
            "vad_filter": _env_bool("LIVE_WHISPER_VAD_FILTER", True),
            "no_speech_threshold": _env_float("LIVE_WHISPER_NO_SPEECH_THRESHOLD", 0.65),
            "log_prob_threshold": _env_float("LIVE_WHISPER_LOG_PROB_THRESHOLD", -1.0),
            "compression_ratio_threshold": _env_float("LIVE_WHISPER_COMPRESSION_RATIO_THRESHOLD", 2.4),
            "condition_on_previous_text": False,
        },
        allow_cpu_fallback=True,
    )
    return [
        SpeakerTurn(
            speaker="Live",
            text=segment.text.strip(),
            start_ms=int(segment.start * 1000),
            end_ms=int(segment.end * 1000),
        )
        for segment in segments
        if _is_usable_live_segment(segment)
    ]


def _is_usable_live_segment(segment: Any) -> bool:
    text = str(getattr(segment, "text", "") or "").strip()
    if not text:
        return False
    if _looks_like_live_hallucination(text):
        return False
    no_speech_prob = getattr(segment, "no_speech_prob", None)
    if isinstance(no_speech_prob, (int, float)) and no_speech_prob >= _env_float("LIVE_MAX_NO_SPEECH_PROB", 0.85):
        return False
    avg_logprob = getattr(segment, "avg_logprob", None)
    if isinstance(avg_logprob, (int, float)) and avg_logprob <= _env_float("LIVE_MIN_AVG_LOGPROB", -1.2):
        return False
    return True


def _looks_like_live_hallucination(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"[0-9a-fA-F_-]{18,}", compact):
        return True
    if re.search(r"\b20\d{6}[_-][0-9a-fA-F-]{12,}\b", compact):
        return True
    alnum = re.sub(r"[^0-9A-Za-z]", "", compact)
    if len(alnum) >= 18:
        hexish = sum(1 for char in alnum if char.lower() in "0123456789abcdef")
        if hexish / max(1, len(alnum)) > 0.85:
            return True
    return False


def _transcribe_with_device_fallback(
    audio_path: str,
    model_name: str,
    device: str,
    compute_type: str,
    transcribe_options: Dict[str, Any],
    *,
    allow_cpu_fallback: bool,
) -> List[Any]:
    try:
        model = _get_faster_whisper_model(model_name, device, compute_type)
        segments, _ = model.transcribe(audio_path, **transcribe_options)
        return list(segments)
    except Exception as exc:
        if device.strip().lower() == "cpu" or not allow_cpu_fallback or not _is_cuda_runtime_error(exc):
            raise
        model = _get_faster_whisper_model(model_name, "cpu", "int8")
        segments, _ = model.transcribe(audio_path, **transcribe_options)
        return list(segments)


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


def _short_error(exc: Exception, max_length: int = 220) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text if len(text) <= max_length else f"{text[:max_length].rstrip()}..."


def _quiet_speech_runtime_warnings() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    warnings.filterwarnings("ignore", message=r".*Specified provider 'CUDAExecutionProvider'.*", category=UserWarning)
    warnings.filterwarnings("ignore", message=r".*torchaudio\.load_with_torchcodec.*", category=UserWarning)


def _effective_indic_conformer_device(device: str) -> str:
    selected = (device or "cpu").strip().lower()
    if not selected.startswith("cuda"):
        return selected
    try:
        import onnxruntime

        if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
            logger.info("ONNX Runtime CUDA provider is unavailable; using CPU for Indic Conformer.")
            return "cpu"
    except Exception:
        return selected
    return selected


@contextlib.contextmanager
def _quiet_preload_output() -> Iterable[None]:
    if os.getenv("MOM_SUPPRESS_PRELOAD_OUTPUT", "1").strip().lower() in {"0", "false", "no", "off"}:
        yield
        return
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield


def _write_silence_wav(path: Path, duration_s: float = 0.5, sample_rate: int = 16000) -> None:
    frames = max(1, int(duration_s * sample_rate))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)


def _get_pyannote_pipeline(pipeline_class: Any, checkpoint: str, token: str | None = None) -> Any:
    requested_device = os.getenv("PYANNOTE_DEVICE", "cpu")
    requested_checkpoint = "pyannote/speaker-diarization-community-1"
    cache_key = f"{requested_checkpoint}|{token or ''}|{requested_device}|{id(pipeline_class)}"
    if cache_key in _PYANNOTE_PIPELINE_CACHE:
        return _PYANNOTE_PIPELINE_CACHE[cache_key]

    try:
        pipeline = _load_pyannote_pipeline(pipeline_class, requested_checkpoint, token)
    except Exception as exc:
        if "$model/segmentation" in str(exc):
            raise TranscriptionError(
                "pyannote/speaker-diarization-community-1 requires a newer compatible pyannote.audio install. "
                "Run: python -m pip install -U \"pyannote.audio>=4.0.0,<5.0\" \"huggingface_hub>=0.24,<1.0\""
            ) from exc
        raise
    if pipeline is None:
        raise TranscriptionError(
            f"Could not load pyannote pipeline '{requested_checkpoint}'. Check HF_TOKEN, model access, and pyannote/huggingface_hub versions."
        )
    device = requested_device.strip().lower()
    if device and device != "cpu" and hasattr(pipeline, "to"):
        try:
            import torch

            pipeline.to(torch.device(device))
        except Exception as exc:
            if _is_cuda_runtime_error(exc):
                logger.warning("Could not move pyannote pipeline to %s; using CPU instead.", device)
            else:
                raise TranscriptionError(f"Could not move pyannote pipeline to {device}.") from exc
    _PYANNOTE_PIPELINE_CACHE[cache_key] = pipeline
    return pipeline


def _load_pyannote_pipeline(pipeline_class: Any, checkpoint: str, token: str | None = None) -> Any:
    _patch_hf_hub_download_auth_kwarg()
    _patch_pyannote_speaker_diarization_config()
    if not token:
        return pipeline_class.from_pretrained(checkpoint)

    signature = inspect.signature(pipeline_class.from_pretrained)
    attempts: list[dict[str, str]] = []
    if "token" in signature.parameters:
        attempts.append({"token": token})
    attempts.append({})

    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return pipeline_class.from_pretrained(checkpoint, **kwargs)
        except TypeError as exc:
            message = str(exc)
            if "unexpected keyword argument" not in message:
                raise
            last_error = exc
    if last_error:
        raise last_error
    return pipeline_class.from_pretrained(checkpoint)


def _patch_pyannote_speaker_diarization_config() -> None:
    try:
        from pyannote.audio.pipelines import SpeakerDiarization
    except Exception:
        return

    original = getattr(SpeakerDiarization, "__init__", None)
    if not original or getattr(original, "_mom_plda_compat", False):
        return

    def init_compat(self: Any, *args: Any, **kwargs: Any) -> None:
        kwargs.pop("plda", None)
        original(self, *args, **kwargs)

    init_compat._mom_plda_compat = True  # type: ignore[attr-defined]
    SpeakerDiarization.__init__ = init_compat


def _patch_hf_hub_download_auth_kwarg() -> None:
    try:
        import huggingface_hub
        import huggingface_hub.file_download as file_download
    except Exception:
        return

    original = getattr(huggingface_hub, "hf_hub_download", None)
    if not original or getattr(original, "_mom_auth_compat", False):
        return

    def hf_hub_download_compat(*args: Any, **kwargs: Any) -> Any:
        if "use_auth_token" in kwargs and "token" not in kwargs:
            kwargs["token"] = kwargs.pop("use_auth_token")
        else:
            kwargs.pop("use_auth_token", None)
        return original(*args, **kwargs)

    hf_hub_download_compat._mom_auth_compat = True  # type: ignore[attr-defined]
    huggingface_hub.hf_hub_download = hf_hub_download_compat
    file_download.hf_hub_download = hf_hub_download_compat
    for module in list(sys.modules.values()):
        if module and getattr(module, "hf_hub_download", None) is original:
            try:
                setattr(module, "hf_hub_download", hf_hub_download_compat)
            except Exception:
                pass


def _decode_audio_for_local_processing(input_path: str, output_path: str, sample_rate: int = 16000) -> None:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise TranscriptionError("Local processing requires imageio-ffmpeg to decode recordings.") from exc

    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-i",
            input_path,
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-vn",
            output_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg conversion failed").strip()
        raise TranscriptionError(f"Could not decode recording: {detail[-800:]}")


def _wav_duration_ms(audio_path: str) -> int | None:
    try:
        import wave

        with wave.open(audio_path, "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate <= 0:
                return None
            return int(frames * 1000 / rate)
    except Exception:
        logger.debug("Could not determine WAV duration for %s.", audio_path, exc_info=True)
        return None


def _pcm_to_wav_base64(pcm_bytes: bytes, sample_rate: int) -> str:
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _unlink_with_retry(path: Path, attempts: int = 5, delay_s: float = 0.25) -> None:
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts - 1:
                logger.warning("Could not delete temporary audio file %s; it may still be in use.", path, exc_info=True)
                return
            time.sleep(delay_s)
        except OSError:
            logger.warning("Could not delete temporary audio file %s.", path, exc_info=True)
            return


def _pyannote_audio_input(audio_path: str, sample_rate: int = 16000) -> Dict[str, Any]:
    try:
        import torchaudio
    except ImportError as exc:
        raise TranscriptionError("Local diarization requires torchaudio to load decoded recordings.") from exc

    waveform, decoded_sample_rate = torchaudio.load(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if int(decoded_sample_rate) != sample_rate:
        waveform = torchaudio.functional.resample(waveform, int(decoded_sample_rate), sample_rate)
    return {"waveform": waveform, "sample_rate": sample_rate}


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


def _assign_text_to_diarization(
    text: str,
    diarization: List[Dict[str, Any]],
    duration_ms: int | None = None,
    expected_speakers: int | None = None,
) -> List[SpeakerTurn]:
    words = text.split()
    if not words:
        raise TranscriptionError("No transcript text was produced from Indic Conformer.")
    if not diarization:
        return [SpeakerTurn(speaker="Speaker 1", text=text, start_ms=0, end_ms=duration_ms)]

    speaker_aliases: Dict[str, str] = {}
    normalized = _merge_adjacent_diarization_turns(diarization)
    unique_speakers = {str(turn.get("speaker") or "Speaker 1") for turn in normalized}
    logger.info(
        "Assigning Indic transcript to diarization: expected_speakers=%s detected_speakers=%s diarization_turns=%s",
        expected_speakers,
        len(unique_speakers),
        len(normalized),
    )
    if expected_speakers == 1 and len(unique_speakers) <= 1:
        start_ms = _first_int(normalized[0], ("start_ms", "start")) if normalized else 0
        end_ms = _first_int(normalized[-1], ("end_ms", "end")) if normalized else duration_ms
        speaker = _canonical_speaker_label(next(iter(unique_speakers), "Speaker 1"), speaker_aliases)
        return [SpeakerTurn(speaker=speaker, text=text, start_ms=start_ms or 0, end_ms=end_ms or duration_ms)]
    if expected_speakers and expected_speakers > 1 and len(unique_speakers) < expected_speakers:
        logger.warning(
            "pyannote detected %s speaker(s), fewer than requested %s; splitting Indic transcript approximately.",
            len(unique_speakers),
            expected_speakers,
        )
        return _split_text_by_expected_speakers(text, expected_speakers, duration_ms)

    total_span = sum(max(1, (_first_int(turn, ("end_ms", "end")) or 0) - (_first_int(turn, ("start_ms", "start")) or 0)) for turn in normalized)
    if total_span <= 0:
        return [SpeakerTurn(speaker="Speaker 1", text=text, start_ms=0, end_ms=duration_ms)]

    turns: List[SpeakerTurn] = []
    word_index = 0
    for index, turn in enumerate(normalized):
        remaining_words = len(words) - word_index
        if remaining_words <= 0:
            break

        start_ms = _first_int(turn, ("start_ms", "start"))
        end_ms = _first_int(turn, ("end_ms", "end"))
        span = max(1, (end_ms or 0) - (start_ms or 0))
        if index == len(normalized) - 1:
            count = remaining_words
        else:
            count = max(1, round(len(words) * span / total_span))
            count = min(count, remaining_words - (len(normalized) - index - 1))
        if count <= 0:
            continue

        raw_speaker = str(turn.get("speaker") or "Speaker 1")
        speaker = _canonical_speaker_label(raw_speaker, speaker_aliases)
        chunk = " ".join(words[word_index:word_index + count]).strip()
        word_index += count
        if chunk:
            turns.append(SpeakerTurn(speaker=speaker, text=chunk, start_ms=start_ms, end_ms=end_ms))

    if word_index < len(words):
        tail = " ".join(words[word_index:]).strip()
        if turns:
            turns[-1].text = f"{turns[-1].text} {tail}".strip()
        else:
            turns.append(SpeakerTurn(speaker="Speaker 1", text=tail, start_ms=0, end_ms=duration_ms))

    return _merge_adjacent_turns(turns)


def _split_text_by_expected_speakers(
    text: str,
    expected_speakers: int,
    duration_ms: int | None = None,
) -> List[SpeakerTurn]:
    words = text.split()
    if not words:
        raise TranscriptionError("No transcript text was produced from Indic Conformer.")
    speaker_count = max(1, min(expected_speakers, len(words)))
    turns: List[SpeakerTurn] = []
    word_index = 0
    for index in range(speaker_count):
        remaining_words = len(words) - word_index
        remaining_speakers = speaker_count - index
        count = max(1, round(remaining_words / remaining_speakers))
        chunk = " ".join(words[word_index:word_index + count]).strip()
        word_index += count
        if not chunk:
            continue
        start_ms = int((duration_ms or 0) * index / speaker_count) if duration_ms else None
        end_ms = int((duration_ms or 0) * (index + 1) / speaker_count) if duration_ms else None
        turns.append(SpeakerTurn(speaker=f"Speaker {index + 1}", text=chunk, start_ms=start_ms, end_ms=end_ms))
    return turns


def _merge_adjacent_diarization_turns(diarization: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for turn in sorted(diarization, key=lambda item: _first_int(item, ("start_ms", "start")) or 0):
        speaker = str(turn.get("speaker") or "Speaker 1")
        start_ms = _first_int(turn, ("start_ms", "start"))
        end_ms = _first_int(turn, ("end_ms", "end"))
        if merged and str(merged[-1].get("speaker")) == speaker:
            merged[-1]["end_ms"] = end_ms or merged[-1].get("end_ms")
        else:
            merged.append({"speaker": speaker, "start_ms": start_ms, "end_ms": end_ms})
    return merged


def _segments_to_plain_transcript(segments: List[Dict[str, Any]]) -> List[SpeakerTurn]:
    text = " ".join(str(segment.get("text", "")).strip() for segment in segments).strip()
    if not text:
        raise TranscriptionError("No transcript text was produced from local transcription.")
    starts = [_first_int(segment, ("start_ms", "start")) for segment in segments]
    ends = [_first_int(segment, ("end_ms", "end")) for segment in segments]
    return [
        SpeakerTurn(
            speaker="",
            text=text,
            start_ms=next((value for value in starts if value is not None), None),
            end_ms=next((value for value in reversed(ends) if value is not None), None),
        )
    ]


def _sarvam_file_results(job: Any) -> Dict[str, Any]:
    try:
        results = job.get_file_results()
    except Exception as exc:
        raise TranscriptionError("Could not read Sarvam batch job results.") from exc
    if not isinstance(results, dict):
        raise TranscriptionError("Sarvam batch job returned an unexpected file-results shape.")
    return results


def _load_first_sarvam_output(output_dir: Path) -> Dict[str, Any]:
    json_files = sorted(output_dir.rglob("*.json"))
    if not json_files:
        raise TranscriptionError("Sarvam did not download any transcript JSON outputs.")
    try:
        payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    except Exception as exc:
        raise TranscriptionError(f"Could not parse Sarvam transcript output {json_files[0].name}.") from exc
    if not isinstance(payload, dict):
        raise TranscriptionError("Sarvam transcript output was not a JSON object.")
    return payload


def _sarvam_payload_to_turns(payload: Dict[str, Any], *, speaker_labels_enabled: bool) -> List[SpeakerTurn]:
    if speaker_labels_enabled:
        entries = ((payload.get("diarized_transcript") or {}).get("entries") or [])
        if entries:
            turns = [_sarvam_entry_to_turn(entry) for entry in entries if isinstance(entry, dict)]
            turns = [turn for turn in turns if turn.text.strip()]
            if turns:
                return _merge_adjacent_turns(turns)

    timestamp_turns = _sarvam_timestamp_turns(payload)
    if timestamp_turns:
        if not speaker_labels_enabled:
            return _segments_to_plain_transcript([turn.model_dump() for turn in timestamp_turns])
        return _merge_adjacent_turns(timestamp_turns)

    text = str(payload.get("transcript") or "").strip()
    if not text:
        raise TranscriptionError("Sarvam did not return transcript text.")
    speaker = "Speaker 1" if speaker_labels_enabled else ""
    return [SpeakerTurn(speaker=speaker, text=text)]


def _sarvam_stream_message_to_turns(message: Any) -> List[SpeakerTurn]:
    payload = _message_to_plain_data(message)
    if not payload:
        return []
    if isinstance(payload, str):
        text = payload.strip()
        return [SpeakerTurn(speaker="Live", text=text)] if text else []
    if not isinstance(payload, dict):
        return []

    message_type = str(payload.get("type") or payload.get("event") or payload.get("message_type") or "").lower()
    if message_type in {"events", "event", "speech_start", "speech_end"}:
        return []

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    text = _first_text_value(
        data,
        (
            "transcript",
            "transcripts",
            "translation",
            "text",
            "transcription",
            "utterance",
            "display_text",
            "final_transcript",
            "partial_transcript",
        ),
    )
    if not text:
        return []
    return [SpeakerTurn(speaker="Live", text=text)]


def _message_to_plain_data(message: Any) -> Any:
    if isinstance(message, (str, bytes, bytearray)):
        text = message.decode("utf-8", errors="ignore") if isinstance(message, (bytes, bytearray)) else message
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if isinstance(message, dict):
        return message
    for attr in ("model_dump", "dict"):
        method = getattr(message, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:
                pass
    if hasattr(message, "__dict__"):
        return {
            key: _message_to_plain_data(value)
            for key, value in vars(message).items()
            if not key.startswith("_")
        }
    return message


def _first_text_value(payload: Any, keys: Iterable[str]) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in payload.values():
        nested = _first_text_value(value, keys)
        if nested:
            return nested
    return ""


def _sarvam_entry_to_turn(entry: Dict[str, Any]) -> SpeakerTurn:
    speaker_id = str(entry.get("speaker_id") or "0")
    speaker = _sarvam_speaker_label(speaker_id)
    return SpeakerTurn(
        speaker=speaker,
        text=str(entry.get("transcript") or "").strip(),
        start_ms=_seconds_to_ms(entry.get("start_time_seconds")),
        end_ms=_seconds_to_ms(entry.get("end_time_seconds")),
    )


def _sarvam_timestamp_turns(payload: Dict[str, Any]) -> List[SpeakerTurn]:
    timestamps = payload.get("timestamps") or {}
    chunks = timestamps.get("chunks") or []
    starts = timestamps.get("start_time_seconds") or []
    ends = timestamps.get("end_time_seconds") or []
    turns: List[SpeakerTurn] = []
    for index, chunk in enumerate(chunks):
        text = str(chunk or "").strip()
        if not text:
            continue
        turns.append(
            SpeakerTurn(
                speaker="Speaker 1",
                text=text,
                start_ms=_seconds_to_ms(starts[index] if index < len(starts) else None),
                end_ms=_seconds_to_ms(ends[index] if index < len(ends) else None),
            )
        )
    return turns


def _sarvam_speaker_label(speaker_id: str) -> str:
    try:
        return f"Speaker {int(speaker_id) + 1}"
    except ValueError:
        return _canonical_speaker_label(speaker_id, {})


def _seconds_to_ms(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value) * 1000)
    except (TypeError, ValueError):
        return None


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


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
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
