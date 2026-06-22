from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Coroutine
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import AuthTokenResponse, CurrentUser, LoginRequest, authenticate_user, change_password, create_access_token, current_user, user_from_authorization, user_from_token, websocket_user
from .models import ChangePasswordRequest, MeetingCreateResponse, MeetingHistoryItem, MeetingState, MeetingStatus, MeetingStatusResponse, MomGenerateRequest, SettingsResponse, SettingsUpdateRequest, SpeakerUpdate, TranscriptUpdate
from .settings_store import load_settings, save_settings
from .services.export import markdown_to_pdf
from .services.mom import MomGenerationClient
from .services.speaker_id import SpeakerIdentificationUnavailable, SpeakerIdentifier
from .services.transcription import create_transcription_client, transcribe_live_preview
from .services.live_transcription import new_suffix
from .storage import MeetingStore, delete_temp_file

load_dotenv()

app = FastAPI(title="Minutes-of-Meeting Tool")
store = MeetingStore()
logger = logging.getLogger(__name__)
running_tasks: dict[str, asyncio.Task[None]] = {}

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMP_DIR = Path(tempfile.gettempdir()) / "mom-tool"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/")
async def index(request: Request) -> Response:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/auth/login", response_model=AuthTokenResponse)
async def login(request: LoginRequest) -> AuthTokenResponse:
    user = authenticate_user(request.username, request.password)
    return AuthTokenResponse(access_token=create_access_token(user), username=user.username)


@app.get("/api/auth/me", response_model=CurrentUser)
async def me(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    return user


@app.post("/api/auth/change-password", status_code=204)
async def api_change_password(
    request: ChangePasswordRequest,
    _: CurrentUser = Depends(current_user),
) -> Response:
    change_password(request.current_password, request.new_password)
    return Response(status_code=204)


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings(_: CurrentUser = Depends(current_user)) -> SettingsResponse:
    return SettingsResponse(**load_settings())


@app.put("/api/settings", response_model=SettingsResponse)
async def update_settings(
    request: SettingsUpdateRequest,
    _: CurrentUser = Depends(current_user),
) -> SettingsResponse:
    updates = request.model_dump(exclude_none=True)
    return SettingsResponse(**save_settings(updates))


@app.get("/api/settings/ollama-models")
async def list_ollama_models(_: CurrentUser = Depends(current_user)) -> Any:
    """Proxy the local Ollama tags endpoint to list available models."""
    import httpx
    settings = load_settings()
    base = settings.get("ollama_base_url", "http://127.0.0.1:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [
                {"name": m["name"], "size": m.get("size"), "modified_at": m.get("modified_at")}
                for m in data.get("models", [])
            ]
            return {"models": models}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Ollama: {exc}")


@app.websocket("/api/live/transcribe")
async def live_transcribe(websocket: WebSocket) -> None:
    await websocket_user(websocket)
    await websocket.accept()
    sample_rate = int(websocket.query_params.get("sample_rate", "16000"))
    chunk_seconds = int(websocket.query_params.get("chunk_seconds", "1"))
    bytes_per_chunk = sample_rate * 2 * max(1, chunk_seconds)
    pcm_buffer = bytearray()
    sequence = 0
    # Tracks the last emitted text per speaker so overlapping Whisper chunks
    # don't repeat words that were already sent to the client.
    last_text: dict[str, str] = {}
    await websocket.send_json({"type": "state", "message": "Local captions connected"})

    async def _flush() -> None:
        nonlocal sequence
        if not pcm_buffer:
            return
        sequence += 1
        wav_path = _write_pcm_wav(bytes(pcm_buffer), sample_rate, f"live-{sequence}")
        pcm_buffer.clear()
        try:
            await websocket.send_json({"type": "state", "message": "Processing local caption chunk"})
            turns = await asyncio.to_thread(transcribe_live_preview, str(wav_path))
            novel_turns = []
            for turn in (turns or []):
                suffix = new_suffix(last_text.get(turn.speaker, ""), turn.text)
                if suffix:
                    last_text[turn.speaker] = turn.text
                    novel_turns.append(turn.model_copy(update={"text": suffix}))
            if novel_turns:
                await websocket.send_json(
                    {
                        "type": "transcript",
                        "turns": [turn.model_dump(mode="json") for turn in novel_turns],
                    }
                )
            else:
                await websocket.send_json({"type": "state", "message": "Listening for speech"})
        finally:
            delete_temp_file(str(wav_path))

    try:
        while True:
            message = await websocket.receive()
            if message.get("text") == "stop":
                await _flush()
                break
            chunk = message.get("bytes")
            if not chunk:
                continue
            pcm_buffer.extend(chunk)
            if len(pcm_buffer) >= bytes_per_chunk:
                await _flush()
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.post("/api/meetings/audio", response_model=MeetingCreateResponse)
async def upload_audio(
    audio: UploadFile = File(...),
    num_speakers: int | None = Form(default=None),
    speaker_labels_enabled: bool = Form(default=True),
    meeting_name: str | None = Form(default=None),
    _: CurrentUser = Depends(current_user),
) -> MeetingCreateResponse:
    if num_speakers is not None and not 1 <= num_speakers <= 10:
        raise HTTPException(status_code=422, detail="num_speakers must be between 1 and 10.")

    meeting_id = uuid4().hex
    suffix = Path(audio.filename or "meeting.webm").suffix or ".webm"
    audio_path = TEMP_DIR / f"{meeting_id}{suffix}"

    with audio_path.open("wb") as target:
        shutil.copyfileobj(audio.file, target)

    meeting = MeetingState(
        id=meeting_id,
        name=_meeting_name(meeting_name, meeting_id),
        status=MeetingStatus.UPLOADED,
        audio_path=str(audio_path),
        num_speakers=num_speakers,
        speaker_labels_enabled=speaker_labels_enabled,
    )
    store.add(meeting)
    _start_meeting_task(meeting_id, transcribe_meeting(meeting_id))
    return MeetingCreateResponse(id=meeting.id, name=meeting.name, status=meeting.status)


@app.get("/api/meetings", response_model=list[MeetingHistoryItem])
async def list_meetings(_: CurrentUser = Depends(current_user)) -> list[MeetingHistoryItem]:
    return [MeetingHistoryItem.from_state(meeting) for meeting in store.list()]


@app.get("/api/meetings/{meeting_id}/status", response_model=MeetingStatusResponse)
async def get_status(meeting_id: str, _: CurrentUser = Depends(current_user)) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    return MeetingStatusResponse.from_state(meeting)


@app.delete("/api/meetings/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str, _: CurrentUser = Depends(current_user)) -> Response:
    _cancel_running_task(meeting_id)
    try:
        meeting = store.delete(meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found.") from exc
    delete_temp_file(meeting.audio_path)
    return Response(status_code=204)


@app.patch("/api/meetings/{meeting_id}/speakers", response_model=MeetingStatusResponse)
async def update_speakers(
    meeting_id: str,
    update: SpeakerUpdate,
    _: CurrentUser = Depends(current_user),
) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    blank_keys = [key for key, value in update.speakers.items() if not value.strip()]
    if blank_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Speaker label(s) must not be blank: {', '.join(blank_keys)}",
        )
    meeting.speaker_names.update({key: value.strip() for key, value in update.speakers.items()})
    if update.remember_voices:
        try:
            SpeakerIdentifier().remember_labels(meeting.speaker_embeddings, meeting.speaker_names)
            meeting.voiceprint_status = "ready"
            meeting.voiceprint_error = None
        except Exception:
            logger.warning("Could not persist voice profiles.", exc_info=True)
            meeting.voiceprint_error = "Could not persist voice profiles. Check the server log for details."
    store.update(meeting)
    return MeetingStatusResponse.from_state(meeting)


@app.patch("/api/meetings/{meeting_id}/transcript", response_model=MeetingStatusResponse)
async def update_transcript_turn(
    meeting_id: str,
    update: TranscriptUpdate,
    _: CurrentUser = Depends(current_user),
) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    if not 0 <= update.index < len(meeting.transcript):
        raise HTTPException(status_code=422, detail="Transcript turn index is out of range.")
    text = update.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Transcript text must not be blank.")
    meeting.transcript[update.index].text = text
    meeting.mom_markdown = None
    if meeting.status == MeetingStatus.READY:
        meeting.status = MeetingStatus.TRANSCRIBED
    store.update(meeting)
    return MeetingStatusResponse.from_state(meeting)


@app.post("/api/meetings/{meeting_id}/mom", response_model=MeetingStatusResponse)
async def generate_mom(
    meeting_id: str,
    request: MomGenerateRequest | None = None,
    _: CurrentUser = Depends(current_user),
) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    if not meeting.transcript:
        raise HTTPException(status_code=409, detail="No transcript is available.")
    if meeting.status in {MeetingStatus.UPLOADED, MeetingStatus.TRANSCRIBING, MeetingStatus.GENERATING}:
        raise HTTPException(status_code=409, detail="Transcription must be complete before generating MoM.")

    meeting.status = MeetingStatus.GENERATING
    meeting.error = None
    store.update(meeting)
    _start_meeting_task(meeting_id, generate_mom_for_meeting(meeting_id, (request or MomGenerateRequest()).mom_type))
    return MeetingStatusResponse.from_state(meeting)


@app.post("/api/meetings/{meeting_id}/cancel", response_model=MeetingStatusResponse)
async def cancel_meeting_action(meeting_id: str, _: CurrentUser = Depends(current_user)) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    if meeting.status not in {MeetingStatus.UPLOADED, MeetingStatus.TRANSCRIBING, MeetingStatus.GENERATING}:
        raise HTTPException(status_code=409, detail="No active transcription or MoM generation to cancel.")

    _cancel_running_task(meeting_id)
    delete_temp_file(meeting.audio_path)
    meeting.audio_path = None
    meeting.status = MeetingStatus.CANCELED
    meeting.completed_at = datetime.now(timezone.utc)
    meeting.error = "Canceled by user."
    store.update(meeting)
    return MeetingStatusResponse.from_state(meeting)


async def generate_mom_for_meeting(meeting_id: str, mom_type: str = "auto") -> None:
    meeting = store.get(meeting_id)
    try:
        meeting.mom_markdown = await MomGenerationClient().generate(
            meeting.transcript,
            meeting.speaker_names,
            speaker_labels_enabled=meeting.speaker_labels_enabled,
            mom_type=mom_type,
        )
        meeting.status = MeetingStatus.READY
        meeting.completed_at = meeting.completed_at or datetime.now(timezone.utc)
        meeting.error = None
    except asyncio.CancelledError:
        meeting.status = MeetingStatus.CANCELED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = "Canceled by user."
        raise
    except Exception as exc:
        meeting.status = MeetingStatus.FAILED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = _short_error(exc)
    finally:
        _finish_meeting_task(meeting_id)
        _safe_update_meeting(meeting)


@app.get("/api/meetings/{meeting_id}/export.md")
async def export_markdown(
    meeting_id: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> PlainTextResponse:
    _authorize_export(token, authorization)
    meeting = _get_meeting(meeting_id)
    if not meeting.mom_markdown:
        raise HTTPException(status_code=404, detail="MoM is not available.")
    return PlainTextResponse(
        meeting.mom_markdown,
        headers={"Content-Disposition": f'attachment; filename="mom-{meeting_id}.md"'},
    )


@app.get("/api/meetings/{meeting_id}/export.pdf")
async def export_pdf(
    meeting_id: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> Response:
    _authorize_export(token, authorization)
    meeting = _get_meeting(meeting_id)
    if not meeting.mom_markdown:
        raise HTTPException(status_code=404, detail="MoM is not available.")
    return Response(
        markdown_to_pdf(meeting.mom_markdown),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="mom-{meeting_id}.pdf"'},
    )


async def transcribe_meeting(meeting_id: str) -> None:
    meeting = store.get(meeting_id)
    meeting.status = MeetingStatus.TRANSCRIBING
    store.update(meeting)

    try:
        meeting.transcript = await create_transcription_client().transcribe(
            meeting.audio_path or "",
            num_speakers=meeting.num_speakers,
            speaker_labels_enabled=meeting.speaker_labels_enabled,
        )
        speakers = sorted({turn.speaker for turn in meeting.transcript})
        meeting.speaker_names = {speaker: speaker for speaker in speakers if speaker} if meeting.speaker_labels_enabled else {}
        meeting.status = MeetingStatus.TRANSCRIBED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = None
        store.update(meeting)

        if not meeting.speaker_labels_enabled:
            meeting.speaker_embeddings = {}
            meeting.voiceprint_status = "disabled"
            meeting.voiceprint_error = "Speaker labels are disabled for this meeting."
            store.update(meeting)
            return

        meeting.speaker_embeddings = {}
        meeting.voiceprint_status = "processing"
        meeting.voiceprint_error = None
        store.update(meeting)
        try:
            identifier = SpeakerIdentifier()
            meeting.speaker_embeddings = await identifier.extract_speaker_embeddings(
                meeting.audio_path or "",
                meeting.transcript,
            )
            if meeting.speaker_embeddings:
                meeting.speaker_names = identifier.label_speakers(meeting.speaker_embeddings, speakers)
                meeting.voiceprint_status = "ready"
                matched = sum(1 for speaker in speakers if meeting.speaker_names.get(speaker) != speaker)
                scores = identifier.best_match_scores(meeting.speaker_embeddings)
                score_hint = f" Best scores: {scores}" if scores else ""
                meeting.voiceprint_error = None if matched else f"No saved speaker profile matched this meeting.{score_hint}"
            else:
                meeting.speaker_names = meeting.speaker_names or {speaker: speaker for speaker in speakers}
                meeting.voiceprint_status = "unavailable"
                meeting.voiceprint_error = "No usable speaker audio segments were found for voiceprinting."
        except SpeakerIdentificationUnavailable as exc:
            logger.info("Voiceprinting unavailable: %s", exc)
            meeting.speaker_names = meeting.speaker_names or {speaker: speaker for speaker in speakers}
            meeting.voiceprint_status = "unavailable"
            meeting.voiceprint_error = str(exc)
        except Exception:
            logger.warning("Voiceprinting failed; falling back to diarized speaker labels.", exc_info=True)
            meeting.speaker_names = meeting.speaker_names or {speaker: speaker for speaker in speakers}
            meeting.voiceprint_status = "failed"
            meeting.voiceprint_error = "Voiceprinting failed. Check the server log for details."
    except asyncio.CancelledError:
        meeting.status = MeetingStatus.CANCELED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = "Canceled by user."
        raise
    except Exception as exc:
        meeting.status = MeetingStatus.FAILED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = _short_error(exc)
    finally:
        delete_temp_file(meeting.audio_path)
        meeting.audio_path = None
        _finish_meeting_task(meeting_id)
        _safe_update_meeting(meeting)


def _start_meeting_task(meeting_id: str, coro: Coroutine[Any, Any, None]) -> None:
    _cancel_running_task(meeting_id)
    task = asyncio.create_task(coro)
    task.add_done_callback(_consume_task_result)
    running_tasks[meeting_id] = task


def _short_error(exc: Exception, limit: int = 600) -> str:
    message = " ".join(str(exc).split())
    if len(message) <= limit:
        return message
    return f"{message[:limit].rstrip()}..."


def _cancel_running_task(meeting_id: str) -> None:
    task = running_tasks.pop(meeting_id, None)
    if task and not task.done():
        task.cancel()


def _finish_meeting_task(meeting_id: str) -> None:
    task = running_tasks.get(meeting_id)
    if task is asyncio.current_task():
        running_tasks.pop(meeting_id, None)


def _safe_update_meeting(meeting: MeetingState) -> None:
    try:
        store.update(meeting)
    except KeyError:
        logger.info("Meeting %s disappeared before background task completed.", meeting.id)


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("Background meeting task failed unexpectedly.", exc_info=True)


def _get_meeting(meeting_id: str) -> MeetingState:
    try:
        return store.get(meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found.") from exc


def _authorize_export(token: str | None, authorization: str | None) -> None:
    if authorization:
        user_from_authorization(authorization)
        return
    user_from_token(token)


def _meeting_name(raw_name: str | None, meeting_id: str) -> str:
    name = (raw_name or "").strip()
    if name:
        return name[:120]
    return f"Meeting {datetime.now().strftime('%Y-%m-%d %H:%M')} ({meeting_id[:6]})"


def _write_pcm_wav(pcm_bytes: bytes, sample_rate: int, stem: str) -> Path:
    path = TEMP_DIR / f"{stem}-{uuid4().hex}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    return path
