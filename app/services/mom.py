from __future__ import annotations

import os
from typing import Dict, List

import httpx

from app.models import SpeakerTurn


class MomGenerationError(RuntimeError):
    pass


class GroqMomClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        if not self.api_key:
            raise MomGenerationError("GROQ_API_KEY is not configured.")

    async def generate(self, transcript: List[SpeakerTurn], speaker_names: Dict[str, str]) -> str:
        prompt = build_mom_prompt(transcript, speaker_names)
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
        if response.status_code >= 400:
            raise MomGenerationError(f"Groq API failed with status {response.status_code}: {response.text}")

        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise MomGenerationError("Groq response did not include generated MoM content.") from exc


SYSTEM_PROMPT = """You generate concise, business-ready Minutes of Meeting.
Use Markdown. Preserve concrete decisions, owners, dates, risks, and open questions.
If an owner or due date is not stated, write "Not specified" instead of inventing it."""


def build_mom_prompt(transcript: List[SpeakerTurn], speaker_names: Dict[str, str]) -> str:
    lines = []
    for turn in transcript:
        speaker = speaker_names.get(turn.speaker, turn.speaker)
        lines.append(f"{speaker}: {turn.text}")

    transcript_text = "\n".join(lines)
    return f"""Create structured Minutes of Meeting from this speaker-wise transcript.

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
