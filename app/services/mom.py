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
            return {
                "model": self.model,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": _env_int("OLLAMA_NUM_CTX", 8192),
                    "num_predict": self.max_tokens,
                },
                "messages": messages,
            }
        return {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }


HuggingFaceGemmaMomClient = MomGenerationClient


SYSTEM_PROMPT = """You generate concise, business-ready Minutes of Meeting.
Use plain Markdown. Preserve concrete decisions, owners, dates, risks, and open questions.
Use only facts stated in the transcript. Do not invent decisions, owners, dates, risks, or next steps.
Do not use inline Markdown styling such as **bold**, __bold__, *italic*, or _italic_.
If an owner or due date is not stated, write "Not specified" instead of inventing it."""


def build_mom_prompt(transcript: List[SpeakerTurn], speaker_names: Dict[str, str]) -> str:
    lines = []
    for turn in sorted(transcript, key=lambda item: (item.start_ms is None, item.start_ms if item.start_ms is not None else 0)):
        speaker = speaker_names.get(turn.speaker, turn.speaker)
        lines.append(f"{speaker}: {turn.text}")

    transcript_text = "\n".join(lines)
    return f"""Create structured Minutes of Meeting from this speaker-wise transcript.

Accuracy rules:
- Use only the transcript below as source material.
- Do not invent action items, design changes, timelines, blockers, or follow-up meetings.
- Do not convert a discussion point into a decision unless the transcript explicitly says a decision was made.
- Do not create an action item unless a speaker explicitly says someone will do something.
- If a section has no evidence, write "None stated."

Formatting rules:
- Use only headings, plain bullet lists, and the action-item table.
- Do not use bold, italic, inline Markdown styling, HTML, blockquotes, horizontal rules, or decorative separators.
- Start every bullet with "- " exactly.
- Do not use "*" bullets.
- Keep each bullet to one sentence.

Required Markdown headings:
# Minutes of Meeting
## Attendees / Speakers
## Executive Summary
## Key Discussion Points
## Decisions
## Action Items
## Risks / Blockers
## Next Steps

For action items, use a Markdown table with columns: Action Item, Owner, Due Date, Source / Context.

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
