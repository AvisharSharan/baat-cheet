# Minutes of Meeting Tool

An open-source meeting-notes app for recording conversations, transcribing audio with a self-hosted Whisper model, and generating structured minutes with Hugging Face Gemma.

## Features

- Browser-based meeting recording
- Google Meet tab audio plus microphone capture
- Local Whisper transcription through `faster-whisper`
- Structured MoM generation with Hugging Face Gemma
- Markdown and PDF exports
- Temporary audio handling with cleanup after transcription
- Simple FastAPI backend and static frontend

## Current Flow

```text
Browser recording
      |
      v
FastAPI upload endpoint
      |
      v
Local faster-whisper transcription
      |
      v
Transcript review
      |
      v
Hugging Face Gemma MoM generation
      |
      v
Markdown / PDF export
```

## Target Live Stack

The next architecture should move from post-meeting upload to live transcription:

```text
Browser AudioWorklet / MediaRecorder chunks
      |
      v
FastAPI WebSocket
      |
      v
Silero VAD + faster-whisper streaming worker
      |
      v
Live transcript events in browser
      |
      v
Final transcript accumulated in meeting state
      |
      v
Hugging Face Gemma MoM generation
```

Recommended stack:

- **Frontend streaming:** `AudioWorklet` for PCM chunks, or short `MediaRecorder` WebM chunks for an easier first version
- **Backend:** FastAPI WebSocket endpoint
- **Self-hosted ASR:** `faster-whisper`, starting with `small` or `medium`
- **Voice activity detection:** Silero VAD, or faster-whisper's built-in VAD for the first pass
- **Live transcript state:** in-memory per meeting initially; Redis if multiple workers/sessions are needed
- **MoM generation:** Hugging Face OpenAI-compatible router with `google/gemma-4-31B-it`
- **Speaker diarization:** defer for v1; add local pyannote or Diart after live ASR is stable

## Setup

Clone the repository and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
HF_TOKEN=your_hugging_face_token
HF_MOM_MODEL=google/gemma-3-27b-it
HF_CHAT_BASE_URL=https://router.huggingface.co/v1
HF_MOM_MAX_TOKENS=1200
HF_MOM_TIMEOUT_S=240
HF_MOM_RETRIES=2

LOCAL_WHISPER_MODEL=small
LOCAL_WHISPER_DEVICE=auto
LOCAL_WHISPER_COMPUTE_TYPE=int8
```

For better GPU quality/speed on a CUDA setup, try:

```env
LOCAL_WHISPER_MODEL=medium
LOCAL_WHISPER_DEVICE=cuda
LOCAL_WHISPER_COMPUTE_TYPE=float16
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

- The current implementation still uses post-recording upload while the backend is being simplified away from vendor STT.
- Live transcription should be built as a WebSocket flow rather than polling the existing upload endpoint.
- Speaker labels are currently `Speaker 1` because local Whisper does not perform diarization.
- Add diarization only after live ASR latency and stability are acceptable.

## Development

Run tests:

```powershell
python -m pytest -q
```

Compile-check Python files:

```powershell
python -m py_compile app\main.py app\services\transcription.py app\services\mom.py app\services\export.py
```
