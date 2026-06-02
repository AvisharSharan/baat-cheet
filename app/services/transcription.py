from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.models import SpeakerTurn


class TranscriptionError(RuntimeError):
    pass


class SarvamTranscriptionClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("SARVAM_API_KEY")
        if not self.api_key:
            raise TranscriptionError("SARVAM_API_KEY is not configured.")

    async def transcribe(self, audio_path: str, num_speakers: int | None = None) -> List[SpeakerTurn]:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, num_speakers)

    def _transcribe_sync(self, audio_path: str, num_speakers: int | None = None) -> List[SpeakerTurn]:
        try:
            from sarvamai import SarvamAI
        except ImportError as exc:
            raise TranscriptionError("sarvamai package is not installed.") from exc

        client = SarvamAI(api_subscription_key=self.api_key)
        job_options = {
            "language_code": "unknown",
            "mode": "transcribe",
            "model": "saaras:v3",
            "with_diarization": True,
        }
        if num_speakers is not None:
            job_options["num_speakers"] = num_speakers
        job = client.speech_to_text_job.create_job(**job_options)
        job.upload_files(file_paths=[audio_path])
        job.start()
        job.wait_until_complete()

        file_results = job.get_file_results()
        failed = file_results.get("failed", [])
        successful = file_results.get("successful", [])
        if failed and not successful:
            errors = "; ".join(f"{item.get('file_name', 'audio')}: {item.get('error_message', 'unknown error')}" for item in failed)
            raise TranscriptionError(f"Sarvam batch transcription failed: {errors}")
        if not successful:
            raise TranscriptionError("Sarvam batch transcription completed without successful file results.")

        output_dir = Path(audio_path).with_suffix("")
        output_dir = output_dir.parent / f"{output_dir.name}_sarvam"
        output_dir.mkdir(parents=True, exist_ok=True)
        job.download_outputs(output_dir=str(output_dir))

        payloads = []
        for path in output_dir.rglob("*.json"):
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        if not payloads:
            raise TranscriptionError("Sarvam completed without JSON transcript output.")

        return normalize_sarvam_output(payloads)


def normalize_sarvam_output(payload: Any) -> List[SpeakerTurn]:
    records = _flatten_records(payload)
    turns: List[SpeakerTurn] = []
    speaker_aliases: Dict[str, str] = {}

    for record in records:
        text = _first_string(record, ("transcript", "text", "sentence", "utterance"))
        if not text:
            continue
        speaker = _speaker_label(record, speaker_aliases)
        if not speaker:
            speaker = "Speaker 1"

        turns.append(
            SpeakerTurn(
                speaker=speaker,
                text=text.strip(),
                start_ms=_timestamp_ms(record, ("start_ms", "start_time_ms", "start_time_seconds", "start")),
                end_ms=_timestamp_ms(record, ("end_ms", "end_time_ms", "end_time_seconds", "end")),
            )
        )

    if not turns:
        raise TranscriptionError("No speaker transcript turns were found in Sarvam output.")

    return _merge_adjacent_turns(turns)


def _flatten_records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        diarized = value.get("diarized_transcript")
        if isinstance(diarized, dict) and isinstance(diarized.get("entries"), list):
            return _flatten_records(diarized["entries"])

        for key in ("diarized_transcript", "speaker_transcript", "transcript", "utterances", "segments", "results"):
            child = value.get(key)
            if isinstance(child, list):
                return _flatten_records(child)
        if any(key in value for key in ("text", "transcript", "utterance", "sentence")):
            return [value]
        records: List[Dict[str, Any]] = []
        for child in value.values():
            records.extend(_flatten_records(child))
        return records

    if isinstance(value, list):
        records = []
        for item in value:
            records.extend(_flatten_records(item))
        return records

    return []


def _first_string(record: Dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and key.startswith("speaker"):
            return str(value).strip()
    return None


def _speaker_label(record: Dict[str, Any], speaker_aliases: Dict[str, str]) -> str | None:
    value = _first_string(record, ("speaker", "speaker_id", "speaker_label", "diarized_speaker"))
    if value is None:
        return None
    if value.lower().startswith("speaker"):
        return value
    if value not in speaker_aliases:
        speaker_aliases[value] = f"Speaker {len(speaker_aliases) + 1}"
    return speaker_aliases[value]


def _timestamp_ms(record: Dict[str, Any], keys: Iterable[str]) -> int | None:
    for key in keys:
        value = _first_number(record.get(key))
        if value is None:
            continue
        if key.endswith("_seconds") or key in {"start", "end"} and value < 1000:
            return int(value * 1000)
        return int(value)
    return None


def _first_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


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
