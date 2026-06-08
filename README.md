# Minutes of Meeting Tool

Browser-based meeting recording with local open-source transcription and local or hosted minutes generation.

## Features

- Record meeting tab audio plus microphone, or microphone only
- Upload finished audio/video recordings for batch transcription
- Transcribe with faster-whisper and diarize speakers with pyannote.audio
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
faster-whisper transcription + pyannote diarization
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

Optional open-source speech pipeline support:

```powershell
python -m pip install -r requirements-open-source-speech.txt
```

The local open-source pipeline uses `faster-whisper` for transcription and `pyannote.audio` for speaker diarization. It requires `ffmpeg`; pyannote's community diarization model also requires accepting the model conditions on Hugging Face and providing an access token.
`pyannote.audio` 4.x requires Python 3.10 or newer.
The app preloads recordings with `imageio-ffmpeg`/`torchaudio` before diarization so pyannote does not depend on TorchCodec's built-in decoder.

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

# Legacy Sarvam keys may remain in .env, but the app does not read them.
# Batch transcription is local-only through faster-whisper + pyannote.audio.
TRANSCRIPTION_PROVIDER=local
FASTER_WHISPER_MODEL=base
FASTER_WHISPER_DEVICE=cpu
FASTER_WHISPER_COMPUTE_TYPE=int8
FASTER_WHISPER_VAD_FILTER=1
FASTER_WHISPER_BEAM_SIZE=1
LIVE_WHISPER_MODEL=tiny
LIVE_WHISPER_BEAM_SIZE=1
LIVE_WHISPER_VAD_FILTER=0
DIARIZATION_PROVIDER=pyannote
PYANNOTE_DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
HF_TOKEN=your_hugging_face_token

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

- Live hosted captions are disabled. Real-time meetings are recorded first, then transcribed locally after upload.
- Local live captions are preview-only and use faster-whisper on short audio chunks without diarization.
- The final transcript uses faster-whisper for ASR and pyannote.audio for diarization.
- For faster final transcription without speaker diarization, set `DIARIZATION_PROVIDER=none`.
- Use `Real-time meeting` for live capture; use `Recorded media` for existing audio/video files, which is the more reliable path for voice matching.
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
