from __future__ import annotations
from app.utils import env_int

import asyncio
import os


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
        self.api_key = api_key or _mom_api_key(self.provider)
        self.model = model or _mom_model(self.provider)
        self.base_url = (base_url or _mom_base_url(self.provider)).strip().rstrip("/")
        self.max_tokens = env_int("MOM_MAX_TOKENS", env_int("HF_MOM_MAX_TOKENS", 1200))
        self.timeout_s = env_int("MOM_TIMEOUT_S", env_int("HF_MOM_TIMEOUT_S", 240))
        self.retries = env_int("MOM_RETRIES", env_int("HF_MOM_RETRIES", 2))
        if self.provider not in {"ollama", "huggingface", "openai-compatible", "hosted"}:
            raise MomGenerationError("MOM_PROVIDER must be one of: ollama, huggingface, openai-compatible, hosted.")
        if self.provider != "ollama" and not self.api_key:
            raise MomGenerationError(_missing_key_message(self.provider))
        if self.provider == "hosted" and not self.base_url:
            raise MomGenerationError("HOSTED_AI_URL is not configured.")

    async def generate(
        self,
        transcript: list[SpeakerTurn],
        speaker_names: dict[str, str],
        *,
        speaker_labels_enabled: bool = True,
        mom_type: str = "auto",
    ) -> str:
        prompt = build_mom_prompt(
            transcript,
            speaker_names,
            speaker_labels_enabled=speaker_labels_enabled,
            mom_type=mom_type,
        )
        content = await self.complete(prompt, system_prompt=SYSTEM_PROMPT)
        return _normalize_mom_markdown(content)

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str,
        max_tokens: int | None = None,
    ) -> str:
        """Run the currently selected AI model for a non-streaming text task."""
        response = await self._post_chat(prompt, system_prompt=system_prompt, max_tokens=max_tokens)
        if response.status_code >= 400:
            detail = _response_error_detail(response)
            raise MomGenerationError(f"{self.provider} AI request failed with status {response.status_code}: {detail}")

        data = response.json()
        if self.provider == "ollama":
            try:
                return data["message"]["content"].strip()
            except (KeyError, TypeError) as exc:
                raise MomGenerationError("Ollama response did not include generated content.") from exc

        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise MomGenerationError("Chat completion response did not include generated content.") from exc

    async def _post_chat(
        self,
        prompt: str,
        *,
        system_prompt: str,
        max_tokens: int | None = None,
    ) -> httpx.Response:
        payload = self._payload(prompt, system_prompt=system_prompt, max_tokens=max_tokens)
        url = self._chat_url()
        headers = {}
        if self.provider == "hosted":
            headers["X-API-Key"] = self.api_key or ""
        elif self.provider != "ollama":
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

    def _payload(self, prompt: str, *, system_prompt: str, max_tokens: int | None = None) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        output_tokens = max_tokens or self.max_tokens
        if self.provider == "ollama":
            options = {
                "temperature": 0.1,
                "num_ctx": env_int("OLLAMA_NUM_CTX", 32768),
                "num_predict": output_tokens,
                "num_gpu": env_int("OLLAMA_NUM_GPU", 0),
            }
            return {
                "model": self.model,
                "stream": False,
                "options": options,
                "messages": messages,
            }
        return {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": output_tokens,
            "messages": messages,
        }

    def _chat_url(self) -> str:
        if self.provider == "ollama":
            return f"{self.base_url}/api/chat"
        if self.provider == "hosted":
            return self.base_url
        return f"{self.base_url}/chat/completions"


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
- Action items must be valid Markdown table rows. Never put bullet points, numbered items, or free text under the Action Items table.
- Every Action Items row must start with "|" and have exactly five cells: #, Action, Owner, Due Date, Notes.
- If there are no action items, write exactly one table row: "| 1 | Not stated | Not stated | Not stated | Not stated |".
- One sentence per bullet. Use past tense for observations; use imperative for action items.
- Reproduce speaker names exactly as they appear in the transcript — do not paraphrase or abbreviate them.
- Do not repeat the same fact across multiple sections.
- The first line of the output must be a Markdown H1 header containing a descriptive title for the meeting based on its content.\
"""


def build_mom_prompt(
    transcript: list[SpeakerTurn],
    speaker_names: dict[str, str],
    *,
    speaker_labels_enabled: bool = True,
    mom_type: str = "auto",
) -> str:
    lines = []
    for turn in sorted(transcript, key=lambda item: (item.start_ms is None, item.start_ms if item.start_ms is not None else 0)):
        if speaker_labels_enabled:
            speaker = speaker_names.get(turn.speaker, turn.speaker)
            lines.append(f"{speaker}: {turn.text}")
        else:
            lines.append(turn.text)

    transcript_text = "\n".join(lines)

    # Warn when the transcript is likely to overflow the configured context window.
    # Rough heuristic: ~3.5 characters per token for English text.
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    num_ctx = env_int("OLLAMA_NUM_CTX", 32768)
    estimated_tokens = len(transcript_text) / 3.5
    if estimated_tokens > num_ctx * 0.85:
        _logger.warning(
            "Transcript is ~%d estimated tokens but OLLAMA_NUM_CTX=%d. "
            "The model may silently truncate the input and produce an incomplete MoM. "
            "Increase OLLAMA_NUM_CTX or use a larger-context model.",
            int(estimated_tokens),
            num_ctx,
        )

    transcript_context = (
        "The transcript below has already been sorted chronologically and speaker labels have been "
        "resolved to full names. Diarization may contain short overlapping fragments or incomplete "
        "sentences - treat these as part of the surrounding context, not as separate statements."
        if speaker_labels_enabled
        else
        "The transcript below has already been sorted chronologically. Speaker labels were intentionally "
        "disabled for this meeting, so do not infer attendees, speakers, owners, or facilitators from voice turns."
    )
    mom_type_instruction = _mom_type_instruction(mom_type)
    return f"""\
{transcript_context}

{mom_type_instruction}

Generate a Minutes of Meeting document using exactly the Markdown structure below.
Emit every heading even if a section has no content; in that case write a single bullet "- Not stated" under it.

---

# Minutes of Meeting

## Meeting Details
- Date: <date or "Not stated">
- Time: <time or "Not stated">
- Facilitator: <name or "Not stated">
- Attendees: <comma-separated list of every speaker name that appears in the transcript, or "Not stated" when speaker labels are disabled>

## Objective
<One sentence stating the meeting's stated purpose. If no purpose was stated, write "Not stated.">

## Key Discussion Points
<Bullet list of topics discussed. One sentence per bullet. Chronological order.>

## Decisions
<Numbered list. Each item is one explicit, unambiguous decision reached during the meeting. Only include decisions - not proposals, suggestions, or open topics.>

## Action Items
| # | Action | Owner | Due Date | Notes |
|---|--------|-------|----------|-------|
| 1 | <imperative action sentence, or "Not stated"> | <explicit owner, or "Not stated"> | <explicit due date, or "Not stated"> | <source context in 10 words or fewer, or "Not stated"> |

Rules for Action Items:
- Replace the example row above with real rows.
- Every action item must be a table row that starts and ends with "|".
- Do not write bullets, numbered lists, or plain sentences below the table.
- Owner and Due Date are "Not stated" if not explicit.
- If there are no action items, keep exactly one row with "Not stated" values.

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


def _mom_type_instruction(mom_type: str) -> str:
    normalized = (mom_type or "auto").strip().lower()
    instructions = {
        "auto": (
            "Meeting type: Auto-detect from the transcript. Quietly infer the closest type and adapt emphasis, "
            "but do not add a separate meeting-type section."
        ),
        "government": (
            "Meeting type: Government or official review. Emphasize formal decisions, accountable owners, "
            "public-service context, risks, blockers, and follow-up actions."
        ),
        "review": (
            "Meeting type: Review or status meeting. Emphasize progress, blockers, decisions, dependencies, "
            "and next follow-up actions."
        ),
        "planning": (
            "Meeting type: Planning or decision meeting. Emphasize proposals, selected decisions, rationale, "
            "owners, deadlines, and unresolved questions."
        ),
        "action": (
            "Meeting type: Action tracker. Keep discussion brief and emphasize action items, owners, due dates, "
            "blockers, and open questions."
        ),
        "general": (
            "Meeting type: General meeting. Use the standard balanced MoM structure without over-emphasizing any one section."
        ),
    }
    return instructions.get(normalized, instructions["auto"])


def env_int(name: str, default: int) -> int:
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
    if provider == "hosted":
        return os.getenv("MOM_MODEL") or os.getenv("HOSTED_AI_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    return os.getenv("MOM_MODEL") or os.getenv("HF_MOM_MODEL", "google/gemma-3-27b-it")


def _mom_base_url(provider: str) -> str:
    if provider == "ollama":
        return os.getenv("MOM_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    if provider == "hosted":
        return os.getenv("MOM_BASE_URL") or os.getenv("HOSTED_AI_URL", "")
    return os.getenv("MOM_BASE_URL") or os.getenv("HF_CHAT_BASE_URL", "https://router.huggingface.co/v1")


def _mom_api_key(provider: str) -> str | None:
    if provider == "hosted":
        return os.getenv("HOSTED_AI_API_KEY") or os.getenv("MOM_API_KEY")
    return os.getenv("MOM_API_KEY") or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")


def _missing_key_message(provider: str) -> str:
    if provider == "hosted":
        return "HOSTED_AI_API_KEY is not configured."
    return "MOM_API_KEY or HF_TOKEN is not configured."


def _normalize_mom_markdown(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    normalized: list[str] = []
    in_action_items = False
    action_index = 1

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and stripped != "## Action Items":
            in_action_items = False
        if stripped == "## Action Items":
            in_action_items = True
            action_index = 1
            normalized.append(line)
            continue
        if in_action_items and stripped.startswith("|---"):
            normalized.append(line)
            continue
        if in_action_items and stripped.startswith("|"):
            normalized.append(line)
            continue
        if in_action_items and stripped.startswith("- "):
            normalized.append(_action_bullet_to_row(stripped[2:], action_index))
            action_index += 1
            continue
        normalized.append(line)

    return "\n".join(normalized).strip()


def _action_bullet_to_row(text: str, index: int) -> str:
    action = text.strip().strip("|")
    owner = "Not stated"
    for separator in (" - ", " — ", " – "):
        if separator in action:
            action, possible_owner = action.rsplit(separator, 1)
            if possible_owner.strip():
                owner = possible_owner.strip()
            break
    return f"| {index} | {_table_cell(action)} | {_table_cell(owner)} | Not stated | Not stated |"


def _table_cell(value: str) -> str:
    return (value or "Not stated").replace("|", "/").strip() or "Not stated"


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
            "Gateway timeout from the selected MoM provider. "
            "The selected model did not respond in time. "
            "Try a smaller model or retry shortly."
        )
    return response.text[:500]
