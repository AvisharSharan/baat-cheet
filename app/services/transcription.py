from __future__ import annotations

import asyncio
import inspect
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import RLock
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Iterable, List, Protocol

from app.models import SpeakerTurn

logger = logging.getLogger(__name__)


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
    if selected in {"local", "open_source", "open-source", "faster_whisper", "faster-whisper"}:
        return FasterWhisperPyannoteTranscriptionClient()
    if selected in {"indic", "indic_conformer", "indic-conformer", "ai4bharat"}:
        return IndicConformerPyannoteTranscriptionClient()
    raise TranscriptionError(
        "Unsupported transcription provider: "
        f"{selected}. Use TRANSCRIPTION_PROVIDER=local or TRANSCRIPTION_PROVIDER=indic-conformer."
    )


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
            logger.warning("Indic Conformer failed on %s; retrying on CPU.", device, exc_info=True)
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
            "vad_filter": _env_bool("LIVE_WHISPER_VAD_FILTER", False),
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
        if getattr(segment, "text", "").strip()
    ]


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
