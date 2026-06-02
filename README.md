# Minutes-of-Meeting Tool

A FastAPI web app that records meeting audio in the browser, transcribes it with Sarvam Saaras v3 speaker diarization, and generates a structured MoM with GroqCloud.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file:

```env
SARVAM_API_KEY=your_sarvam_key
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
```

Run locally:

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Notes

- v1 processes audio after recording stops because speaker diarization is handled through Sarvam Batch Speech-to-Text with `saaras:v3`.
- Meeting audio is stored temporarily and deleted after transcription succeeds or fails.
- Transcript and MoM data are kept in in-memory session state for the running process.
