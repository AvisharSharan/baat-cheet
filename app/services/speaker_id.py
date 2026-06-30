from __future__ import annotations
from app.utils import env_int, unlink_with_retry

import asyncio
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Iterable

from app.models import SpeakerTurn


class SpeakerIdentificationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeakerMatch:
    label: str
    score: float


class VoiceProfileStore:
    def __init__(self, path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parents[2] / "data" / "speaker_profiles.json"
        self.path = Path(path or os.getenv("VOICE_PROFILE_STORE_PATH") or default_path)
        self._lock = RLock()

    def load(self) -> dict[str, list[float]]:
        with self._lock:
            if not self.path.exists():
                return {}
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {}
            profiles = payload.get("profiles", payload)
            if not isinstance(profiles, dict):
                return {}
            return {
                str(label): [float(value) for value in embedding]
                for label, embedding in profiles.items()
                if isinstance(embedding, list) and embedding
            }

    def save(self, profiles: dict[str, list[float]]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "profiles": {label: _normalize_vector(embedding) for label, embedding in sorted(profiles.items())},
            }
            with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                temp_path = Path(handle.name)
            temp_path.replace(self.path)

    def upsert_many(self, labeled_embeddings: dict[str, list[float]]) -> None:
        cleaned = {
            label.strip(): _normalize_vector(embedding)
            for label, embedding in labeled_embeddings.items()
            if label.strip() and embedding
        }
        if not cleaned:
            return
        profiles = self.load()
        for label, embedding in cleaned.items():
            existing = profiles.get(label)
            profiles[label] = _mean_vectors([existing, embedding]) if existing else embedding
        self.save(profiles)


class SpeakerIdentifier:
    def __init__(
        self,
        profile_store: VoiceProfileStore | None = None,
        *,
        threshold: float | None = None,
        min_segment_ms: int | None = None,
        max_seconds_per_speaker: float | None = None,
    ) -> None:
        self.profile_store = profile_store or VoiceProfileStore()
        self.threshold = threshold if threshold is not None else _env_float("VOICE_MATCH_THRESHOLD", 0.68)
        self.min_segment_ms = min_segment_ms if min_segment_ms is not None else env_int("VOICE_MIN_SEGMENT_MS", 900)
        self.max_seconds_per_speaker = (
            max_seconds_per_speaker if max_seconds_per_speaker is not None else _env_float("VOICE_MAX_SECONDS_PER_SPEAKER", 12.0)
        )

    async def extract_speaker_embeddings(self, audio_path: str, transcript: list[SpeakerTurn]) -> dict[str, list[float]]:
        return await asyncio.to_thread(self._extract_speaker_embeddings_sync, audio_path, transcript)

    def _extract_speaker_embeddings_sync(self, audio_path: str, transcript: list[SpeakerTurn]) -> dict[str, list[float]]:
        if not voiceprinting_enabled():
            raise SpeakerIdentificationUnavailable("Voiceprinting is disabled. Set VOICEPRINTING_ENABLED=1 to enable it.")
        if voiceprinting_worker_enabled():
            return self._extract_speaker_embeddings_worker(audio_path, transcript)

        return self._extract_speaker_embeddings_direct(audio_path, transcript)

    def _extract_speaker_embeddings_direct(self, audio_path: str, transcript: list[SpeakerTurn]) -> dict[str, list[float]]:
        turns_by_speaker = _group_usable_turns(transcript, self.min_segment_ms)
        if not turns_by_speaker:
            return {}

        backend = _EmbeddingBackend.load()
        waveform, sample_rate = backend.load_audio(audio_path)
        speaker_embeddings: dict[str, list[float]] = {}
        for speaker, turns in turns_by_speaker.items():
            segment = _collect_speaker_audio(waveform, sample_rate, turns, self.max_seconds_per_speaker)
            if segment is None:
                continue
            speaker_embeddings[speaker] = backend.embed(segment, sample_rate)
        return speaker_embeddings

    def _extract_speaker_embeddings_worker(self, audio_path: str, transcript: list[SpeakerTurn]) -> dict[str, list[float]]:
        repo_root = Path(__file__).resolve().parents[2]
        timeout_s = _env_float("VOICEPRINTING_WORKER_TIMEOUT_S", 180.0)
        env = os.environ.copy()
        env["VOICEPRINTING_ENABLED"] = "1"
        env["VOICEPRINTING_USE_WORKER"] = "0"
        env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("MKL_NUM_THREADS", "1")
        env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

        with NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([turn.model_dump(mode="json") for turn in transcript], handle)
            transcript_path = Path(handle.name)
        with NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            output_path = Path(handle.name)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.services.voiceprint_worker",
                    "--audio",
                    audio_path,
                    "--transcript",
                    str(transcript_path),
                    "--output",
                    str(output_path),
                    "--min-segment-ms",
                    str(self.min_segment_ms),
                    "--max-seconds-per-speaker",
                    str(self.max_seconds_per_speaker),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        finally:
            transcript_path.unlink(missing_ok=True)

        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            detail = (result.stderr or result.stdout or "voiceprint worker failed").strip()
            raise SpeakerIdentificationUnavailable(f"Voiceprint worker failed: {detail[-1000:]}")

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SpeakerIdentificationUnavailable("Voiceprint worker returned invalid JSON.") from exc
        finally:
            output_path.unlink(missing_ok=True)
        if not isinstance(payload, dict):
            raise SpeakerIdentificationUnavailable("Voiceprint worker returned an invalid payload.")
        return {
            str(speaker): [float(value) for value in embedding]
            for speaker, embedding in payload.items()
            if isinstance(embedding, list) and embedding
        }

    def label_speakers(self, speaker_embeddings: dict[str, list[float]], fallback_labels: Iterable[str]) -> dict[str, str]:
        profiles = self.profile_store.load()
        labels: dict[str, str] = {}
        for speaker in fallback_labels:
            match = self.match(speaker_embeddings.get(speaker), profiles)
            labels[speaker] = match.label if match else speaker
        return labels

    def best_match_scores(self, speaker_embeddings: dict[str, list[float]]) -> dict[str, float]:
        profiles = self.profile_store.load()
        return {
            speaker: round(match.score, 3)
            for speaker, embedding in speaker_embeddings.items()
            if (match := self._best_match(embedding, profiles)) is not None
        }

    def match(self, embedding: list[float] | None, profiles: dict[str, list[float]] | None = None) -> SpeakerMatch | None:
        best = self._best_match(embedding, profiles)
        if best and best.score >= self.threshold:
            return best
        return None

    def _best_match(self, embedding: list[float] | None, profiles: dict[str, list[float]] | None = None) -> SpeakerMatch | None:
        if not embedding:
            return None
        candidates = profiles if profiles is not None else self.profile_store.load()
        best: SpeakerMatch | None = None
        for label, profile_embedding in candidates.items():
            score = _cosine_similarity(embedding, profile_embedding)
            if best is None or score > best.score:
                best = SpeakerMatch(label=label, score=score)
        return best

    def remember_labels(self, speaker_embeddings: dict[str, list[float]], speaker_names: dict[str, str]) -> None:
        labeled_embeddings = {
            label: speaker_embeddings[speaker]
            for speaker, label in speaker_names.items()
            if speaker in speaker_embeddings and label and label.strip() and label.strip() != speaker
        }
        self.profile_store.upsert_many(labeled_embeddings)



class _EmbeddingBackend:
    _instance: "_EmbeddingBackend | None" = None

    @classmethod
    def load(cls) -> "_EmbeddingBackend":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Release the cached model instance (e.g. during hot-reload in development)."""
        cls._instance = None

    def __init__(self) -> None:
        try:
            import torch
            import torchaudio
            from speechbrain.utils.fetching import LocalStrategy
            try:
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError:
                from speechbrain.pretrained import EncoderClassifier
        except ImportError as exc:
            raise SpeakerIdentificationUnavailable(
                "Voiceprinting requires optional packages: torch, torchaudio, and speechbrain."
            ) from exc

        self.torch = torch
        self.torchaudio = torchaudio
        self.device = _normalize_speechbrain_device(
            os.getenv("VOICE_EMBEDDING_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.classifier = EncoderClassifier.from_hparams(
            source=os.getenv("VOICE_EMBEDDING_MODEL", "speechbrain/spkrec-ecapa-voxceleb"),
            savedir=os.getenv("VOICE_EMBEDDING_MODEL_DIR", "pretrained_models/spkrec-ecapa-voxceleb"),
            run_opts={"device": self.device},
            local_strategy=LocalStrategy.COPY,
        )

    def load_audio(self, audio_path: str):
        try:
            waveform, sample_rate = self.torchaudio.load(audio_path)
        except Exception:
            waveform, sample_rate = self._load_audio_via_ffmpeg(audio_path)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        return waveform.squeeze(0), int(sample_rate)

    def _load_audio_via_ffmpeg(self, audio_path: str):
        try:
            import imageio_ffmpeg
        except ImportError as exc:
            raise SpeakerIdentificationUnavailable(
                "Voiceprinting could not decode the recording. Install imageio-ffmpeg or provide WAV audio."
            ) from exc

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        with NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            wav_path = Path(handle.name)
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    audio_path,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-vn",
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "ffmpeg conversion failed").strip()
                raise SpeakerIdentificationUnavailable(f"Voiceprinting could not decode the recording: {detail[-800:]}")
            return self.torchaudio.load(str(wav_path))
        finally:
            unlink_with_retry(wav_path)

    def embed(self, waveform, sample_rate: int) -> list[float]:
        if sample_rate != 16000:
            waveform = self.torchaudio.functional.resample(waveform, sample_rate, 16000)
        with self.torch.no_grad():
            embedding = self.classifier.encode_batch(waveform.to(self.device).unsqueeze(0)).squeeze()
        return _normalize_vector([float(value) for value in embedding.detach().cpu().tolist()])


def _normalize_speechbrain_device(device: str) -> str:
    selected = (device or "cpu").strip()
    return "cuda:0" if selected.lower() == "cuda" else selected


def _group_usable_turns(transcript: list[SpeakerTurn], min_segment_ms: int) -> dict[str, list[SpeakerTurn]]:
    grouped: dict[str, list[SpeakerTurn]] = {}
    for turn in transcript:
        if turn.start_ms is None or turn.end_ms is None:
            continue
        if turn.end_ms - turn.start_ms < min_segment_ms:
            continue
        grouped.setdefault(turn.speaker, []).append(turn)
    return grouped


def _collect_speaker_audio(waveform, sample_rate: int, turns: list[SpeakerTurn], max_seconds: float):
    torch = _EmbeddingBackend.load().torch
    segments = []
    total_samples = 0
    max_samples = int(max_seconds * sample_rate)
    for turn in turns:
        start = max(0, int((turn.start_ms or 0) * sample_rate / 1000))
        end = min(int((turn.end_ms or 0) * sample_rate / 1000), waveform.shape[-1])
        if end <= start:
            continue
        segment = waveform[start:end]
        remaining = max_samples - total_samples
        if remaining <= 0:
            break
        if segment.shape[-1] > remaining:
            segment = segment[:remaining]
        segments.append(segment)
        total_samples += int(segment.shape[-1])
    if not segments:
        return None
    return torch.cat(segments)


def _mean_vectors(vectors: Iterable[list[float] | None]) -> list[float]:
    usable = [vector for vector in vectors if vector]
    if not usable:
        return []
    width = len(usable[0])
    totals = [0.0] * width
    count = 0
    for vector in usable:
        if len(vector) != width:
            continue
        count += 1
        for index, value in enumerate(vector):
            totals[index] += float(value)
    if count == 0:
        return []
    return _normalize_vector([value / count for value in totals])


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [float(value / norm) for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """Dot product of two pre-normalized unit vectors equals cosine similarity.

    All embeddings are normalized before being stored (via _normalize_vector in
    embed() and upsert_many()), so calling _normalize_vector again here is
    redundant work on every profile comparison.  A plain dot product is correct
    and faster.
    """
    if not left or not right or len(left) != len(right):
        return -1.0
    return sum(a * b for a, b in zip(left, right))



def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default



def voiceprinting_enabled() -> bool:
    return os.getenv("VOICEPRINTING_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def voiceprinting_worker_enabled() -> bool:
    return os.getenv("VOICEPRINTING_USE_WORKER", "0").strip().lower() not in {"0", "false", "no", "off"}


def preload_voiceprinting_runtime() -> None:
    if not voiceprinting_enabled() or voiceprinting_worker_enabled():
        return
    _EmbeddingBackend.load()
