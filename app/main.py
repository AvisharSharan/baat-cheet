from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .models import MeetingCreateResponse, MeetingHistoryItem, MeetingState, MeetingStatus, MeetingStatusResponse, SpeakerUpdate
from .services.export import markdown_to_pdf
from .services.mom import MomGenerationClient
from .services.speaker_id import SpeakerIdentificationUnavailable, SpeakerIdentifier
from .services.transcription import create_transcription_client, transcribe_live_preview
from .storage import MeetingStore, delete_temp_file

load_dotenv()

app = FastAPI(title="Minutes-of-Meeting Tool")
store = MeetingStore()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMP_DIR = Path(tempfile.gettempdir()) / "mom-tool"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/api/live/transcribe")
async def live_transcribe(websocket: WebSocket) -> None:
    await websocket.accept()
    sample_rate = int(websocket.query_params.get("sample_rate", "16000"))
    chunk_seconds = int(websocket.query_params.get("chunk_seconds", "2"))
    bytes_per_chunk = sample_rate * 2 * max(2, chunk_seconds)
    pcm_buffer = bytearray()
    sequence = 0
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
            if turns:
                await websocket.send_json(
                    {
                        "type": "transcript",
                        "turns": [turn.model_dump(mode="json") for turn in turns],
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
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    num_speakers: int | None = Form(default=None),
    meeting_name: str | None = Form(default=None),
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
    )
    store.add(meeting)
    background_tasks.add_task(transcribe_meeting, meeting_id)
    return MeetingCreateResponse(id=meeting.id, name=meeting.name, status=meeting.status)


@app.get("/api/meetings", response_model=list[MeetingHistoryItem])
async def list_meetings() -> list[MeetingHistoryItem]:
    return [MeetingHistoryItem.from_state(meeting) for meeting in store.list()]


@app.get("/api/meetings/{meeting_id}/status", response_model=MeetingStatusResponse)
async def get_status(meeting_id: str) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    return MeetingStatusResponse.from_state(meeting)


@app.patch("/api/meetings/{meeting_id}/speakers", response_model=MeetingStatusResponse)
async def update_speakers(meeting_id: str, update: SpeakerUpdate) -> MeetingStatusResponse:
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
        except Exception:
            logger.warning("Could not persist voice profiles.", exc_info=True)
    store.update(meeting)
    return MeetingStatusResponse.from_state(meeting)


@app.post("/api/meetings/{meeting_id}/mom", response_model=MeetingStatusResponse)
async def generate_mom(meeting_id: str) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    if not meeting.transcript:
        raise HTTPException(status_code=409, detail="No transcript is available.")
    if meeting.status in {MeetingStatus.UPLOADED, MeetingStatus.TRANSCRIBING, MeetingStatus.GENERATING}:
        raise HTTPException(status_code=409, detail="Transcription must be complete before generating MoM.")

    meeting.status = MeetingStatus.GENERATING
    store.update(meeting)
    try:
        meeting.mom_markdown = await MomGenerationClient().generate(meeting.transcript, meeting.speaker_names)
        meeting.status = MeetingStatus.READY
        meeting.completed_at = meeting.completed_at or datetime.now(timezone.utc)
        meeting.error = None
    except Exception as exc:
        meeting.status = MeetingStatus.FAILED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = str(exc)
    store.update(meeting)
    return MeetingStatusResponse.from_state(meeting)


@app.get("/api/meetings/{meeting_id}/export.md")
async def export_markdown(meeting_id: str) -> PlainTextResponse:
    meeting = _get_meeting(meeting_id)
    if not meeting.mom_markdown:
        raise HTTPException(status_code=404, detail="MoM is not available.")
    return PlainTextResponse(
        meeting.mom_markdown,
        headers={"Content-Disposition": f'attachment; filename="mom-{meeting_id}.md"'},
    )


@app.get("/api/meetings/{meeting_id}/export.pdf")
async def export_pdf(meeting_id: str) -> Response:
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
        )
        speakers = sorted({turn.speaker for turn in meeting.transcript})
        meeting.speaker_embeddings = {}
        meeting.voiceprint_status = "processing"
        meeting.voiceprint_error = None
        try:
            identifier = SpeakerIdentifier()
            meeting.speaker_embeddings = await identifier.extract_speaker_embeddings(
                meeting.audio_path or "",
                meeting.transcript,
            )
            if meeting.speaker_embeddings:
                meeting.speaker_names = identifier.label_speakers(meeting.speaker_embeddings, speakers)
                meeting.voiceprint_status = "ready"
                meeting.voiceprint_error = None
            else:
                meeting.speaker_names = {speaker: speaker for speaker in speakers}
                meeting.voiceprint_status = "unavailable"
                meeting.voiceprint_error = "No usable speaker audio segments were found for voiceprinting."
        except SpeakerIdentificationUnavailable as exc:
            logger.info("Voiceprinting unavailable: %s", exc)
            meeting.speaker_names = {speaker: speaker for speaker in speakers}
            meeting.voiceprint_status = "unavailable"
            meeting.voiceprint_error = str(exc)
        except Exception:
            logger.warning("Voiceprinting failed; falling back to diarized speaker labels.", exc_info=True)
            meeting.speaker_names = {speaker: speaker for speaker in speakers}
            meeting.voiceprint_status = "failed"
            meeting.voiceprint_error = "Voiceprinting failed. Check the server log for details."
        meeting.status = MeetingStatus.TRANSCRIBED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = None
    except Exception as exc:
        meeting.status = MeetingStatus.FAILED
        meeting.completed_at = datetime.now(timezone.utc)
        meeting.error = str(exc)
    finally:
        delete_temp_file(meeting.audio_path)
        meeting.audio_path = None
        store.update(meeting)


def _get_meeting(meeting_id: str) -> MeetingState:
    try:
        return store.get(meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found.") from exc


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
