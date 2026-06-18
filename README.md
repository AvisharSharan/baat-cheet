# Verbari

Verbari is a local-first meeting intelligence tool. It records live meetings or
accepts uploaded media, transcribes the audio with faster-whisper, optionally
diarizes speakers with pyannote.audio, lets you review the transcript, and then
generates structured Minutes of Meeting (MoM) with a local Ollama model or an
OpenAI-compatible hosted chat endpoint.

The app is built as a FastAPI backend with a static browser UI. Meeting history,
transcripts, generated minutes, and optional remembered speaker profiles are
stored on the local machine.

## Features

- Sign in with local username/password auth and short-lived bearer tokens.
- Record a meeting tab plus microphone, record microphone only, or upload audio/video files.
- Preview local live captions while recording, then run the final batch transcription.
- Transcribe locally with faster-whisper.
- Add speaker labels with pyannote diarization, or disable speaker labels for a plain transcript.
- Provide an expected speaker count, including a fast single-speaker path.
- Edit transcript turns before generating minutes.
- Rename speakers and optionally remember voices with local SpeechBrain voice profiles.
- Generate extractive MoM documents for different meeting types.
- Export generated minutes as Markdown or PDF.
- Browse, reopen, refresh, and delete saved meeting history.
- Cancel active transcription or minutes generation jobs.
- Toggle light/dark UI themes.

## Architecture

```text
Browser UI
  |-- MediaRecorder / file upload
  |-- optional local live-caption websocket
  v
FastAPI app
  |-- local auth and meeting history
  |-- faster-whisper transcription
  |-- optional pyannote speaker diarization
  |-- optional SpeechBrain voice profiles
  |-- Ollama or OpenAI-compatible MoM generation
  v
Local JSON stores + Markdown/PDF exports
```

Important paths:

- `app/main.py` - FastAPI routes, background job orchestration, exports, and websocket captions.
- `app/services/transcription.py` - faster-whisper transcription and pyannote diarization.
- `app/services/mom.py` - MoM prompt construction and chat-provider client.
- `app/services/speaker_id.py` - optional voiceprint extraction, matching, and profile storage.
- `app/storage.py` - JSON-backed meeting history.
- `app/static/js/` and `app/templates/` - static frontend.
- `data/meetings.json` - default persisted meeting history.
- `data/speaker_profiles.json` - default remembered voice profiles.

## Requirements

- Python 3.10 or newer.
- A browser with MediaRecorder support.
- ffmpeg support through `imageio-ffmpeg` for uploaded browser/media formats.
- Optional: Ollama running locally for default MoM generation.
- Optional: Hugging Face token and accepted model terms for pyannote diarization.
- Optional: PyTorch, torchaudio, and SpeechBrain for remembered speaker voices.

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

Install optional voice profile support:

```powershell
python -m pip install -r requirements-voiceprint.txt
```

If you use the default Ollama minutes provider, make sure Ollama is running and
the configured model is available:

```powershell
ollama pull qwen2.5:7b
```

## Configuration

Create a `.env` file in the project root. This is a practical local default:

```env
# Local auth
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=admin
# Prefer LOCAL_AUTH_PASSWORD_HASH for a less fragile local setup.
JWT_SECRET=change_this_local_secret
JWT_EXPIRES_MINUTES=720

# Meeting persistence
MOM_MEETINGS_PATH=data/meetings.json

# Final transcription
TRANSCRIPTION_PROVIDER=local
FASTER_WHISPER_MODEL=base
FASTER_WHISPER_DEVICE=cpu
FASTER_WHISPER_COMPUTE_TYPE=int8
FASTER_WHISPER_CPU_FALLBACK=1
FASTER_WHISPER_VAD_FILTER=1
FASTER_WHISPER_BEAM_SIZE=1

# Local live-caption preview
LIVE_WHISPER_MODEL=tiny
LIVE_WHISPER_DEVICE=cpu
LIVE_WHISPER_COMPUTE_TYPE=int8
LIVE_WHISPER_BEAM_SIZE=1
LIVE_WHISPER_VAD_FILTER=0

# Diarization
DIARIZATION_PROVIDER=pyannote
PYANNOTE_DEVICE=cpu
HF_TOKEN=your_hugging_face_token

# Optional remembered voices
VOICEPRINTING_ENABLED=0
VOICEPRINTING_USE_WORKER=1
VOICE_PROFILE_STORE_PATH=data/speaker_profiles.json
VOICE_MATCH_THRESHOLD=0.68
VOICE_MIN_SEGMENT_MS=900
VOICE_MAX_SECONDS_PER_SPEAKER=12

# Minutes generation
MOM_PROVIDER=ollama
OLLAMA_MOM_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_NUM_CTX=32768
OLLAMA_NUM_GPU=0
MOM_MAX_TOKENS=1200
MOM_TIMEOUT_S=240
MOM_RETRIES=2
```

Hosted or OpenAI-compatible MoM generation can be configured instead:

```env
MOM_PROVIDER=huggingface
HF_TOKEN=your_hugging_face_token
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

Sign in with `LOCAL_AUTH_USERNAME` and `LOCAL_AUTH_PASSWORD` from `.env`.

## Usage

1. Name the meeting.
2. Choose `Live` or `Recorded`.
3. For live meetings, choose `Meeting tab + microphone` or `Microphone only`.
4. Optionally enable local live captions for preview while recording.
5. Choose an expected speaker count or leave it on auto-detect.
6. Keep speaker labels enabled for diarization, or disable them for one plain transcript.
7. Record or upload the media.
8. Review the transcript, edit any turn if needed, and rename speakers.
9. If voiceprinting is enabled and embeddings are ready, check `Remember voices` before saving labels.
10. Choose a meeting type and click `Draft Minutes`.
11. Export the generated minutes as Markdown or PDF.
12. Use `History` to reopen or delete saved meetings.

## Notes

- Live captions are preview-only. The final transcript is produced after the recording is uploaded.
- Local live captions use the `LIVE_WHISPER_*` settings and do not diarize speakers.
- Final transcription uses faster-whisper. Diarization is skipped when speaker labels are off, when `DIARIZATION_PROVIDER=none`, or when the selected speaker count is `1`.
- pyannote community diarization requires compatible `pyannote.audio` packages and access to the Hugging Face model.
- Browser recordings are uploaded to a temporary file and deleted after final processing.
- Meeting history is persisted in `data/meetings.json` by default, but raw audio is not kept after processing.
- Voice profiles are local embeddings, not calibrated identity guarantees. They help suggest labels when a saved voice is similar enough.
- MoM generation is intentionally extractive: prompts instruct the model not to invent owners, due dates, decisions, or action items.
- Export links include the current auth token as a query parameter so browser downloads can work without custom headers.

## API Summary

- `POST /api/auth/login` - local login.
- `GET /api/auth/me` - validate the current bearer token.
- `POST /api/meetings/audio` - upload recorded audio/video and start transcription.
- `GET /api/meetings` - list meeting history.
- `GET /api/meetings/{id}/status` - fetch transcript, speaker labels, voiceprint status, and MoM.
- `PATCH /api/meetings/{id}/transcript` - edit one transcript turn.
- `PATCH /api/meetings/{id}/speakers` - save speaker display labels and optionally remember voice profiles.
- `POST /api/meetings/{id}/mom` - generate minutes.
- `POST /api/meetings/{id}/cancel` - cancel active transcription or minutes generation.
- `DELETE /api/meetings/{id}` - delete a meeting from history.
- `GET /api/meetings/{id}/export.md` - download generated minutes as Markdown.
- `GET /api/meetings/{id}/export.pdf` - download generated minutes as PDF.
- `WS /api/live/transcribe` - local live-caption preview websocket.

## Development

Run the test suite:

```powershell
python -m pytest -q
```

Compile-check the Python source:

```powershell
python -m py_compile app\main.py app\models.py app\auth.py app\storage.py app\services\transcription.py app\services\mom.py app\services\speaker_id.py app\services\voiceprint_worker.py app\services\live_transcription.py app\services\export.py
```

The frontend is plain HTML, CSS, and JavaScript served by FastAPI, so there is
no separate Node build step.
