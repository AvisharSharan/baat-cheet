# Minutes of Meeting Tool

Browser-based meeting recording with Sarvam transcription and local or hosted minutes generation.

## Features

- Record meeting tab audio plus microphone, or microphone only
- Toggle live captions on or off for real-time meetings
- Upload finished audio/video recordings for batch transcription
- Upload the completed recording for Sarvam batch transcription with diarization
- Review speaker-wise transcript turns and rename speaker labels
- Generate structured Minutes of Meeting with local Qwen or a configured hosted chat model
- Export generated notes as Markdown or PDF
- Temporary audio cleanup after transcription
- FastAPI backend with a static frontend

## Current Flow

```text
Browser recording
      |
      v
FastAPI upload endpoint
      |
      v
Sarvam batch transcription + diarization
      |
      v
Transcript review and speaker labels
      |
      v
Local Qwen or configured chat model MoM generation
      |
      v
Markdown / PDF export
```

## Setup

Clone the repository and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Optional voiceprinting support:

```powershell
python -m pip install -r requirements-voiceprint.txt
```

Voiceprinting runs in a separate worker process so the optional ML stack does not destabilize the FastAPI server. Enable it explicitly in `.env`:

```env
VOICEPRINTING_ENABLED=1
```

Voice profiles are stored locally in `data/speaker_profiles.json` by default. Set `VOICE_PROFILE_STORE_PATH` to use a different file. Speaker labels are remembered only when `Remember voices` is checked before saving labels. Set `VOICEPRINTING_USE_WORKER=0` only for debugging; the worker path is recommended on Windows.

Create a `.env` file in the project root:

```env
SARVAM_API_KEY=your_sarvam_api_key
SARVAM_STREAM_LANGUAGE_CODE=unknown
SARVAM_STREAM_SAMPLE_RATE=16000
SARVAM_STREAM_MODEL=saaras:v3
SARVAM_STREAM_MODE=transcribe

MOM_PROVIDER=ollama
OLLAMA_MOM_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_NUM_CTX=8192
MOM_MAX_TOKENS=1200
MOM_TIMEOUT_S=240
MOM_RETRIES=2

# Optional hosted fallback:
# MOM_PROVIDER=huggingface
# HF_TOKEN=your_hugging_face_token
# HF_MOM_MODEL=google/gemma-3-27b-it
# HF_CHAT_BASE_URL=https://router.huggingface.co/v1
```

Run the app:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Notes

- Live captions can be turned on for real-time meetings through Sarvam's streaming STT WebSocket, or turned off to avoid streaming token usage while recording.
- The final transcript still uses Sarvam batch diarization after the recording is stopped and uploaded.
- Use `Real-time meeting` for live capture and captions; use `Recorded media` for existing audio/video files, which is the more reliable path for voice matching.
- The speaker hint is passed to the batch transcription job when provided.
- MoM generation is extractive by prompt: the configured chat model is instructed not to invent owners, dates, decisions, or action items.
- Meeting state is in memory, so sessions reset when the server restarts.

## Development

Run tests:

```powershell
python -m pytest -q
```

Compile-check Python files:

```powershell
python -m py_compile app\main.py app\services\transcription.py app\services\mom.py app\services\export.py
```
