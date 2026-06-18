# Verbari

Verbari is a local-first meeting intelligence tool. It records live meetings or
accepts uploaded media, creates a transcript with faster-whisper, optionally
diarizes speakers with pyannote.audio, helps review speaker labels, and drafts
structured Minutes of Meeting with Ollama or another OpenAI-compatible chat
provider.

The app is a FastAPI backend with a static browser UI. Meeting history,
transcripts, generated minutes, and optional speaker voice profiles are stored
on the local machine.

## Features

- Local sign-in with username/password auth and bearer tokens.
- Live recording from meeting tab plus microphone, or microphone only.
- Upload flow for audio/video files such as WebM, MP3, MP4, WAV, OGG, MOV, and MKV.
- Local live-caption preview while recording.
- Final local transcription with faster-whisper.
- Optional pyannote speaker diarization, expected-speaker hints, and one-speaker fast path.
- Plain transcript mode when speaker labels are disabled.
- Transcript editing before minutes generation.
- Speaker label editing with optional remembered voice profiles through SpeechBrain.
- Meeting-type presets for auto, government, review, planning, action tracker, and general meetings.
- Cancel support for active transcription or minutes generation jobs.
- Meeting history with reopen, refresh, and delete controls.
- Markdown and PDF exports for generated minutes.
- Light/dark theme toggle.

## Workflow

```text
Record live audio or upload media
        |
        v
FastAPI stores a temporary upload
        |
        v
faster-whisper transcription
        |
        +--> optional pyannote diarization
        |
        +--> optional SpeechBrain voice matching
        |
        v
Review transcript and speaker labels
        |
        v
Draft minutes through Ollama or hosted chat
        |
        v
Save history and export Markdown/PDF
```

Raw audio files are temporary and are deleted after processing. Meeting history
is persisted separately as JSON.

## Project Layout

- `app/main.py` - FastAPI app, routes, websocket live captions, and background jobs.
- `app/auth.py` - local password auth and JWT-style bearer tokens.
- `app/storage.py` - JSON meeting history store.
- `app/models.py` - Pydantic request/response and meeting state models.
- `app/services/transcription.py` - faster-whisper transcription and pyannote diarization.
- `app/services/live_transcription.py` - live-caption overlap cleanup.
- `app/services/speaker_id.py` - optional SpeechBrain voice profile matching.
- `app/services/mom.py` - MoM prompt and chat-provider client.
- `app/services/export.py` - Markdown-to-PDF export.
- `app/templates/` - Jinja templates for the static UI.
- `app/static/` - CSS, JavaScript, and audio worklet assets.
- `data/meetings.json` - default meeting history path.
- `data/speaker_profiles.json` - default remembered voice profile path.

## Requirements

- Python 3.10 or newer.
- A modern browser with MediaRecorder support.
- Ollama for the default local minutes provider.
- CUDA runtime libraries for the recommended GPU setup.
- A Hugging Face token with access to `pyannote/speaker-diarization-community-1`.
- Optional voice profile support requires PyTorch, torchaudio, and SpeechBrain.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install the local speech pipeline:

```powershell
python -m pip install -r requirements-open-source-speech.txt
```

Install optional remembered-voice support:

```powershell
python -m pip install -r requirements-voiceprint.txt
```

Install the default Ollama model:

```powershell
ollama pull qwen2.5:3b
```

## Configuration

Create a `.env` file in the project root. Keep real tokens and secrets out of
commits.

```env
# Hugging Face token for pyannote model access.
HF_TOKEN=your_hugging_face_token

# Local transcription and diarization.
TRANSCRIPTION_PROVIDER=local
PYANNOTE_DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
DIARIZATION_PROVIDER=pyannote
FASTER_WHISPER_MODEL=base
FASTER_WHISPER_DEVICE=cuda
FASTER_WHISPER_COMPUTE_TYPE=float16
FASTER_WHISPER_CPU_FALLBACK=1
FASTER_WHISPER_VAD_FILTER=1
FASTER_WHISPER_BEAM_SIZE=1
PYANNOTE_DEVICE=cuda

# Local live-caption preview.
LIVE_WHISPER_MODEL=base
LIVE_WHISPER_DEVICE=cuda
LIVE_WHISPER_COMPUTE_TYPE=float16
LIVE_WHISPER_BEAM_SIZE=1
LIVE_WHISPER_VAD_FILTER=0

# Local voice profile matching.
VOICEPRINTING_ENABLED=1
VOICEPRINTING_USE_WORKER=1
VOICE_PROFILE_STORE_PATH=data/speaker_profiles.json

# Meeting persistence.
MOM_MEETINGS_PATH=data/meetings.json

# Local auth.
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=admin
# Prefer LOCAL_AUTH_PASSWORD_HASH instead of LOCAL_AUTH_PASSWORD for stronger local storage.
JWT_SECRET=change_this_local_secret
JWT_EXPIRES_MINUTES=720

# Minutes generation through Ollama.
MOM_PROVIDER=ollama
OLLAMA_MOM_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_NUM_CTX=32768
MOM_MAX_TOKENS=1200
MOM_TIMEOUT_S=240
MOM_RETRIES=2
```

Optional hosted or OpenAI-compatible minutes generation:

```env
MOM_PROVIDER=huggingface
HF_MOM_MODEL=google/gemma-3-27b-it
HF_CHAT_BASE_URL=https://router.huggingface.co/v1
```

or:

```env
MOM_PROVIDER=openai-compatible
MOM_API_KEY=your_api_key
MOM_MODEL=your_model
MOM_BASE_URL=https://your-provider.example/v1
```

## Run

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Sign in with `LOCAL_AUTH_USERNAME` and `LOCAL_AUTH_PASSWORD`.

## Usage

1. Enter a meeting name.
2. Choose `Live` or `Recorded`.
3. For live meetings, choose `Meeting tab + microphone` or `Microphone only`.
4. Toggle local live captions if you want preview text during recording.
5. Choose an expected speaker count or leave it on auto-detect.
6. Keep speaker labels on for diarization, or turn them off for one plain transcript.
7. Record or upload the media.
8. Review the transcript and edit any turn that needs correction.
9. Rename speakers and optionally check `Remember voices` before saving labels.
10. Choose a meeting type and click `Draft Minutes`.
11. Download Markdown or PDF exports once minutes are ready.
12. Use `History` to reopen or delete past meetings.

## Notes

- Live captions are only a preview. Final transcript quality comes from the post-upload batch transcription.
- The recommended setup uses CUDA with `float16` for faster-whisper, live Whisper, and pyannote.
- If CUDA is unavailable, set Whisper devices to `cpu` and compute type to `int8`.
- `FASTER_WHISPER_CPU_FALLBACK=1` lets final transcription retry on CPU for common CUDA runtime failures.
- Speaker labels are skipped when the UI toggle is off, when `DIARIZATION_PROVIDER=none`, or when the expected speaker count is `1`.
- Voice profiles are local similarity embeddings, not calibrated identity proof.
- MoM generation is extractive by prompt: the model is told not to invent owners, due dates, decisions, or action items.
- Export links include the current auth token as a query parameter so browser downloads can work without custom headers.
- `data/` and pretrained model folders are ignored by git.

## API Summary

- `POST /api/auth/login` - local login.
- `GET /api/auth/me` - validate the active bearer token.
- `WS /api/live/transcribe` - local live-caption preview websocket.
- `POST /api/meetings/audio` - upload audio/video and start transcription.
- `GET /api/meetings` - list meeting history.
- `GET /api/meetings/{meeting_id}/status` - fetch transcript, labels, voiceprint status, and minutes.
- `PATCH /api/meetings/{meeting_id}/transcript` - edit one transcript turn.
- `PATCH /api/meetings/{meeting_id}/speakers` - save speaker labels and optionally remember voices.
- `POST /api/meetings/{meeting_id}/mom` - start minutes generation.
- `POST /api/meetings/{meeting_id}/cancel` - cancel active transcription or minutes generation.
- `DELETE /api/meetings/{meeting_id}` - delete a meeting from history.
- `GET /api/meetings/{meeting_id}/export.md` - download generated minutes as Markdown.
- `GET /api/meetings/{meeting_id}/export.pdf` - download generated minutes as PDF.

## Development

Run tests:

```powershell
python -m pytest -q
```

Compile-check Python files:

```powershell
python -m py_compile app\main.py app\models.py app\auth.py app\storage.py app\services\transcription.py app\services\mom.py app\services\speaker_id.py app\services\voiceprint_worker.py app\services\live_transcription.py app\services\export.py
```
