from __future__ import annotations

import asyncio
import os
from typing import Dict, List

import httpx

from app.models import SpeakerTurn


class MomGenerationError(RuntimeError):
    pass


class MomGenerationClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.provider = os.getenv("MOM_PROVIDER", "ollama").strip().lower()
        self.api_key = api_key or os.getenv("MOM_API_KEY") or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")
        self.model = model or _mom_model(self.provider)
        self.base_url = (base_url or _mom_base_url(self.provider)).rstrip("/")
        self.max_tokens = _env_int("MOM_MAX_TOKENS", _env_int("HF_MOM_MAX_TOKENS", 1200))
        self.timeout_s = _env_int("MOM_TIMEOUT_S", _env_int("HF_MOM_TIMEOUT_S", 240))
        self.retries = _env_int("MOM_RETRIES", _env_int("HF_MOM_RETRIES", 2))
        if self.provider not in {"ollama", "huggingface", "openai-compatible"}:
            raise MomGenerationError("MOM_PROVIDER must be one of: ollama, huggingface, openai-compatible.")
        if self.provider in {"huggingface", "openai-compatible"} and not self.api_key:
            raise MomGenerationError("MOM_API_KEY or HF_TOKEN is not configured.")

    async def generate(self, transcript: List[SpeakerTurn], speaker_names: Dict[str, str]) -> str:
        prompt = build_mom_prompt(transcript, speaker_names)
        response = await self._post_chat(prompt)
        if response.status_code >= 400:
            detail = _response_error_detail(response)
            raise MomGenerationError(f"{self.provider} MoM generation failed with status {response.status_code}: {detail}")

        data = response.json()
        if self.provider == "ollama":
            try:
                return data["message"]["content"].strip()
            except (KeyError, TypeError) as exc:
                raise MomGenerationError("Ollama response did not include generated MoM content.") from exc

        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise MomGenerationError("Chat completion response did not include generated MoM content.") from exc

    async def _post_chat(self, prompt: str) -> httpx.Response:
        payload = self._payload(prompt)
        url = f"{self.base_url}/api/chat" if self.provider == "ollama" else f"{self.base_url}/chat/completions"
        headers = {}
        if self.provider != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_response = None
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            for attempt in range(self.retries + 1):
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code not in {502, 503, 504}:
                    return response
                last_response = response
                if attempt < self.retries:  # only sleep between attempts, not after the last one
                    await asyncio.sleep(2 ** (attempt + 1))
        return last_response

    def _payload(self, prompt: str) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        if self.provider == "ollama":
            options = {
                "temperature": 0.1,
                "num_ctx": _env_int("OLLAMA_NUM_CTX", 8192),
                "num_predict": self.max_tokens,
            }
            num_gpu = os.getenv("OLLAMA_NUM_GPU")
            if num_gpu is not None:
                options["num_gpu"] = _env_int("OLLAMA_NUM_GPU", 0)
            return {
                "model": self.model,
                "stream": False,
                "options": options,
                "messages": messages,
            }
        return {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }


HuggingFaceGemmaMomClient = MomGenerationClient


SYSTEM_PROMPT = """\
You are a precise business analyst who writes Minutes of Meeting (MoM) documents.

Factual constraints — never violate these:
- Use only information explicitly stated in the transcript. Do not infer, extrapolate, or assume.
- Do not convert a discussion point into a decision unless a speaker explicitly signals agreement or a conclusion (e.g. "we agreed", "let's go with", "decided").
- Do not create an action item unless a speaker explicitly commits someone to a task.
- If a field or section has no evidence in the transcript, write "Not stated" — never leave it blank.

Style constraints — never violate these:
- Write in plain Markdown: headings and unordered lists only, plus one table for action items.
- No bold, italic, underline, or any other inline Markdown styling.
- No HTML, blockquotes, horizontal rules, or decorative separators.
- Unordered list bullets must use "- " exactly; never use "*" or "+".
- One sentence per bullet. Use past tense for observations; use imperative for action items.
- Reproduce speaker names exactly as they appear in the transcript — do not paraphrase or abbreviate them.
- Do not repeat the same fact across multiple sections.\
"""


def build_mom_prompt(transcript: List[SpeakerTurn], speaker_names: Dict[str, str]) -> str:
    lines = []
    for turn in sorted(transcript, key=lambda item: (item.start_ms is None, item.start_ms if item.start_ms is not None else 0)):
        speaker = speaker_names.get(turn.speaker, turn.speaker)
        lines.append(f"{speaker}: {turn.text}")

    transcript_text = "\n".join(lines)
    return f"""\
The transcript below has already been sorted chronologically and speaker labels have been \
resolved to full names. Diarization may contain short overlapping fragments or incomplete \
sentences — treat these as part of the surrounding context, not as separate statements.

Generate a Minutes of Meeting document using exactly the Markdown structure below. \
Emit every heading even if a section has no content; in that case write a single \
bullet "- Not stated" under it.

---

# Minutes of Meeting

## Meeting Details
- Date: <date or "Not stated">
- Time: <time or "Not stated">
- Facilitator: <name or "Not stated">
- Attendees: <comma-separated list of every speaker name that appears in the transcript>

## Objective
<One sentence stating the meeting's stated purpose. If no purpose was stated, write "Not stated.">

## Key Discussion Points
<Bullet list of topics discussed. One sentence per bullet. Chronological order.>

## Decisions
<Numbered list. Each item is one explicit, unambiguous decision reached during the meeting. \
Only include decisions — not proposals, suggestions, or open topics.>

## Action Items
| # | Action | Owner | Due Date | Notes |
|---|--------|-------|----------|-------|
<One row per action item. Owner and Due Date are "Not stated" if not explicit. \
Notes column captures source context in 10 words or fewer.>

## Risks and Blockers
<Bullet list of concerns, blockers, or risks explicitly flagged by speakers.>

## Open Questions
<Bullet list of questions that were raised but not resolved in the meeting.>

## Next Meeting
<Date, time, and agenda topics if stated. Otherwise a single bullet "- Not stated".>

---

Transcript:
{transcript_text}
"""


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise MomGenerationError(f"{name} must be an integer.") from exc


def _mom_model(provider: str) -> str:
    if provider == "ollama":
        return os.getenv("MOM_MODEL") or os.getenv("OLLAMA_MOM_MODEL", "qwen2.5:7b")
    return os.getenv("MOM_MODEL") or os.getenv("HF_MOM_MODEL", "google/gemma-3-27b-it")


def _mom_base_url(provider: str) -> str:
    if provider == "ollama":
        return os.getenv("MOM_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    return os.getenv("MOM_BASE_URL") or os.getenv("HF_CHAT_BASE_URL", "https://router.huggingface.co/v1")


def _response_error_detail(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = response.json()
        except ValueError:
            return response.text[:500]
        error = data.get("error") if isinstance(data, dict) else None
        return str(error or data)[:500]
    if response.status_code == 504:
        return (
            "Gateway timeout from Hugging Face Inference Providers. "
            "The selected MoM model/provider did not respond in time. "
            "Try a smaller HF_MOM_MODEL or retry shortly."
        )
    return response.text[:500]
