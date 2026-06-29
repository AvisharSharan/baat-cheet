from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass

from app.models import SpeakerTurn
from app.services.mom import MomGenerationClient


class TranslationError(RuntimeError):
    pass


TRANSLATION_SYSTEM_PROMPT = """You are a precise Hindi-English translator.
Translate every supplied text completely and faithfully. Do not summarize, omit, censor, explain, or add facts.
Preserve names, numbers, and meaning. Return only the requested JSON."""


@dataclass(frozen=True)
class _Piece:
    id: str
    turn_index: int
    text: str


class TranscriptTranslationClient:
    def __init__(self, ai_client: MomGenerationClient | None = None) -> None:
        self.ai = ai_client or MomGenerationClient()
        self.chunk_chars = max(500, _env_int("TRANSLATION_CHUNK_CHARS", 5000))
        self.max_tokens = max(512, _env_int("TRANSLATION_MAX_TOKENS", 4096))
        self.retries = max(0, _env_int("TRANSLATION_VALIDATION_RETRIES", 2))

    async def translate(self, transcript: list[SpeakerTurn]) -> tuple[list[SpeakerTurn], str]:
        if not transcript or not any(turn.text.strip() for turn in transcript):
            raise TranslationError("No transcript is available to translate.")

        source_language, target_language = await self._detect_languages(transcript)
        pieces = self._make_pieces(transcript)
        translated_by_id: dict[str, str] = {}

        for chunk in self._chunks(pieces):
            translated_by_id.update(
                await self._translate_chunk(chunk, source_language, target_language)
            )

        translated_turns: list[SpeakerTurn] = []
        for turn_index, turn in enumerate(transcript):
            turn_pieces = [piece for piece in pieces if piece.turn_index == turn_index]
            text = " ".join(translated_by_id[piece.id].strip() for piece in turn_pieces).strip()
            if not text:
                raise TranslationError(f"Translation was incomplete at transcript turn {turn_index + 1}.")
            translated_turns.append(
                SpeakerTurn(
                    speaker=turn.speaker,
                    text=text,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                )
            )

        if len(translated_turns) != len(transcript):
            raise TranslationError("Translation was incomplete and was not saved.")
        return translated_turns, target_language

    async def _detect_languages(self, transcript: list[SpeakerTurn]) -> tuple[str, str]:
        sample = _representative_sample(transcript, 6000)
        prompt = f"""Determine whether the dominant language in this transcript is Hindi or English.
Hindi may be written in Devanagari or Roman script. If mixed, choose the dominant language.
Reply with exactly one word: HINDI or ENGLISH.

Transcript sample:
{sample}"""
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                result = await self.ai.complete(
                    prompt,
                    system_prompt="You identify the dominant language of meeting transcripts.",
                    max_tokens=16,
                )
                languages = set(re.findall(r"\b(HINDI|ENGLISH)\b", result.upper()))
                if languages == {"HINDI"}:
                    return "Hindi", "English"
                if languages == {"ENGLISH"}:
                    return "English", "Hindi"
                raise TranslationError("The AI model did not identify the transcript as Hindi or English.")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
        raise TranslationError(f"Could not detect transcript language: {last_error}")

    def _make_pieces(self, transcript: list[SpeakerTurn]) -> list[_Piece]:
        pieces: list[_Piece] = []
        max_piece_chars = max(250, self.chunk_chars - 500)
        for turn_index, turn in enumerate(transcript):
            fragments = _split_text(turn.text.strip(), max_piece_chars)
            for part_index, fragment in enumerate(fragments):
                pieces.append(_Piece(f"{turn_index}:{part_index}", turn_index, fragment))
        return pieces

    def _chunks(self, pieces: list[_Piece]) -> list[list[_Piece]]:
        chunks: list[list[_Piece]] = []
        current: list[_Piece] = []
        current_chars = 0
        for piece in pieces:
            estimated_chars = len(piece.text) + len(piece.id) + 40
            if current and current_chars + estimated_chars > self.chunk_chars:
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(piece)
            current_chars += estimated_chars
        if current:
            chunks.append(current)
        return chunks

    async def _translate_chunk(
        self,
        chunk: list[_Piece],
        source_language: str,
        target_language: str,
    ) -> dict[str, str]:
        payload = [{"id": piece.id, "text": piece.text} for piece in chunk]
        expected_ids = {piece.id for piece in chunk}
        prompt = f"""Translate every item from {source_language} to {target_language}.
Return only a JSON array with exactly the same number of items and exactly this schema:
[{{"id":"unchanged input id","text":"complete translation"}}]
Keep each id unchanged. Do not merge, skip, reorder, summarize, or truncate any item.

Input JSON:
{json.dumps(payload, ensure_ascii=False)}"""

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                content = await self.ai.complete(
                    prompt,
                    system_prompt=TRANSLATION_SYSTEM_PROMPT,
                    max_tokens=self.max_tokens,
                )
                result = _parse_translation_json(content)
                actual_ids = set(result)
                if actual_ids != expected_ids:
                    missing = sorted(expected_ids - actual_ids)
                    extra = sorted(actual_ids - expected_ids)
                    raise TranslationError(f"Chunk validation failed; missing={missing}, extra={extra}.")
                if any(not result[item_id].strip() for item_id in expected_ids):
                    raise TranslationError("Chunk validation found an empty translation.")
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
        raise TranslationError(f"A transcript chunk could not be translated completely: {last_error}")


def _parse_translation_json(content: str) -> dict[str, str]:
    start = content.find("[")
    end = content.rfind("]")
    if start < 0 or end < start:
        raise TranslationError("The model returned invalid translation JSON.")
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise TranslationError("The model returned truncated or invalid translation JSON.") from exc
    if not isinstance(data, list):
        raise TranslationError("The model returned an invalid translation list.")

    result: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
            raise TranslationError("The model returned an invalid translation item.")
        if item["id"] in result:
            raise TranslationError(f"The model duplicated translation id {item['id']}.")
        result[item["id"]] = item["text"]
    return result


def _split_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    fragments: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        boundary = remaining.rfind(" ", 0, max_chars + 1)
        if boundary < max_chars // 2:
            boundary = max_chars
        fragments.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        fragments.append(remaining)
    return fragments


def _representative_sample(transcript: list[SpeakerTurn], max_chars: int) -> str:
    text = "\n".join(turn.text.strip() for turn in transcript if turn.text.strip())
    if len(text) <= max_chars:
        return text
    section = max_chars // 3
    middle_start = max(0, (len(text) - section) // 2)
    return "\n".join((text[:section], text[middle_start : middle_start + section], text[-section:]))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise TranslationError(f"{name} must be an integer.") from exc
