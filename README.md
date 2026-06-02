# Minutes of Meeting Tool

An open-source web app for recording online meetings, producing speaker-wise transcripts, and generating structured minutes of meeting.

The app records audio in the browser, sends the recording to a FastAPI backend, transcribes and diarizes it with Sarvam Saaras v3, and uses Groq to generate meeting notes with summaries, decisions, action items, risks, and next steps.

## Features

- Browser-based meeting recording
- Google Meet tab audio plus microphone capture
- Speaker-wise transcription with editable speaker labels
- Structured MoM generation
- Markdown and PDF exports
- Temporary audio handling with cleanup after transcription
- Simple FastAPI backend and static frontend

## How It Works

```text
Browser recording
      |
      v
FastAPI upload endpoint
      |
      v
Sarvam Batch Speech-to-Text
      |
      v
Speaker-wise transcript
      |
      v
Groq MoM generation
      |
      v
Markdown / PDF export
```

## Tech Stack

- **Backend:** FastAPI
- **Frontend:** HTML, CSS, vanilla JavaScript
- **Speech-to-text and diarization:** Sarvam Saaras v3
- **MoM generation:** GroqCloud
- **PDF export:** ReportLab

## Setup

Clone the repository and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
SARVAM_API_KEY=your_sarvam_key
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
```

Run the app:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Usage

1. Select a capture source.
2. Optionally enter the expected number of speakers.
3. Click **Start Recording**.
4. If recording Google Meet, select the Meet tab/window in the browser picker and enable audio sharing.
5. Click **Stop Recording** when the meeting ends.
6. Review the speaker-wise transcript.
7. Rename speakers if needed and save them.
8. Click **Generate Notes**.
9. Export the result as Markdown or PDF.

## Recording Google Meet

Use **Meet tab + mic** when you want to capture both remote participants and your own local microphone.

Browser security does not allow a web app to silently listen to another tab. You must explicitly select the Google Meet tab/window in the browser share picker and enable audio sharing.

For cleaner testing, use headphones or keep test devices far apart. If another device is near your laptop, your laptop microphone may capture both your voice and the other device's speaker output.

## Sarvam Batch STT Notes

This app uses Sarvam Batch Speech-to-Text with:

```text
model="saaras:v3"
mode="transcribe"
with_diarization=True
```

The app uploads one meeting recording per batch job. Sarvam returns diarized transcript entries with speaker IDs and timestamps, which are normalized into editable labels like `Speaker 1`, `Speaker 2`, and so on.

## Privacy Notes

- Uploaded meeting audio is stored temporarily during processing.
- Audio is deleted after transcription succeeds or fails.
- Transcript and generated notes are kept in in-memory state for the running server process.
- This project does not include persistent meeting history by default.

## Development

Run tests:

```powershell
python -m pytest -q
```

Compile-check Python files:

```powershell
python -m py_compile app\main.py app\services\transcription.py app\services\mom.py app\services\export.py
```

## Credits

Built with speech intelligence from [Sarvam](https://www.sarvam.ai/) and generation from [Groq](https://groq.com/).
