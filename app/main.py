from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .models import MeetingCreateResponse, MeetingState, MeetingStatus, MeetingStatusResponse, SpeakerUpdate
from .services.export import markdown_to_pdf
from .services.mom import GroqMomClient
from .services.transcription import SarvamTranscriptionClient
from .storage import MeetingStore, delete_temp_file

load_dotenv()

app = FastAPI(title="Minutes-of-Meeting Tool")
store = MeetingStore()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMP_DIR = Path(tempfile.gettempdir()) / "mom-tool"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/meetings/audio", response_model=MeetingCreateResponse)
async def upload_audio(background_tasks: BackgroundTasks, audio: UploadFile = File(...)) -> MeetingCreateResponse:
    meeting_id = uuid4().hex
    suffix = Path(audio.filename or "meeting.webm").suffix or ".webm"
    audio_path = TEMP_DIR / f"{meeting_id}{suffix}"

    with audio_path.open("wb") as target:
        shutil.copyfileobj(audio.file, target)

    meeting = MeetingState(id=meeting_id, status=MeetingStatus.UPLOADED, audio_path=str(audio_path))
    store.add(meeting)
    background_tasks.add_task(transcribe_meeting, meeting_id)
    return MeetingCreateResponse(id=meeting.id, status=meeting.status)


@app.get("/api/meetings/{meeting_id}/status", response_model=MeetingStatusResponse)
async def get_status(meeting_id: str) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    return MeetingStatusResponse(**meeting.model_dump())


@app.patch("/api/meetings/{meeting_id}/speakers", response_model=MeetingStatusResponse)
async def update_speakers(meeting_id: str, update: SpeakerUpdate) -> MeetingStatusResponse:
    meeting = _get_meeting(meeting_id)
    meeting.speaker_names = {key: value.strip() for key, value in update.speakers.items() if value.strip()}
    store.update(meeting)
    return MeetingStatusResponse(**meeting.model_dump())


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
        meeting.mom_markdown = await GroqMomClient().generate(meeting.transcript, meeting.speaker_names)
        meeting.status = MeetingStatus.READY
    except Exception as exc:
        meeting.status = MeetingStatus.FAILED
        meeting.error = str(exc)
    store.update(meeting)
    return MeetingStatusResponse(**meeting.model_dump())


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
        meeting.transcript = await SarvamTranscriptionClient().transcribe(meeting.audio_path or "")
        speakers = sorted({turn.speaker for turn in meeting.transcript})
        meeting.speaker_names = {speaker: speaker for speaker in speakers}
        meeting.status = MeetingStatus.TRANSCRIBED
        meeting.error = None
    except Exception as exc:
        meeting.status = MeetingStatus.FAILED
        meeting.error = str(exc)
    finally:
        delete_temp_file(meeting.audio_path)
        meeting.audio_path = None
        store.update(meeting)
        await asyncio.sleep(0)


def _get_meeting(meeting_id: str) -> MeetingState:
    try:
        return store.get(meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found.") from exc
