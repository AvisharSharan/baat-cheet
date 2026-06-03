# Minutes of Meeting Tool

Browser-based meeting recording with Sarvam transcription and Hugging Face Gemma minutes generation.

## Features

- Record meeting tab audio plus microphone, or microphone only
- Upload the completed recording for Sarvam batch transcription with diarization
- Review speaker-wise transcript turns and rename speaker labels
- Generate structured Minutes of Meeting with Hugging Face Gemma
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
Hugging Face Gemma MoM generation
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

Create a `.env` file in the project root:

```env
SARVAM_API_KEY=your_sarvam_api_key

HF_TOKEN=your_hugging_face_token
HF_MOM_MODEL=google/gemma-3-27b-it
HF_CHAT_BASE_URL=https://router.huggingface.co/v1
HF_MOM_MAX_TOKENS=1200
HF_MOM_TIMEOUT_S=240
HF_MOM_RETRIES=2
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

- Transcription starts only after the recording is stopped and uploaded.
- Sarvam diarization is used for speaker turns; the speaker hint is passed when provided.
- MoM generation is extractive by prompt: Gemma is instructed not to invent owners, dates, decisions, or action items.
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
