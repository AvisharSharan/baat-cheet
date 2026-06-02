let recorder;
let chunks = [];
let meetingId = null;
let pollTimer = null;

const startBtn = document.querySelector("#startBtn");
const stopBtn = document.querySelector("#stopBtn");
const momBtn = document.querySelector("#momBtn");
const saveSpeakersBtn = document.querySelector("#saveSpeakersBtn");
const statusText = document.querySelector("#statusText");
const transcriptEl = document.querySelector("#transcript");
const speakerEditor = document.querySelector("#speakerEditor");
const momOutput = document.querySelector("#momOutput");
const exportLinks = document.querySelector("#exportLinks");

startBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopRecording);
momBtn.addEventListener("click", generateMom);
saveSpeakersBtn.addEventListener("click", saveSpeakers);

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  chunks = [];
  recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop());
    uploadRecording();
  };
  recorder.start();
  setStatus("Recording...");
  startBtn.disabled = true;
  stopBtn.disabled = false;
  momBtn.disabled = true;
}

function stopRecording() {
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
    setStatus("Uploading audio...");
    stopBtn.disabled = true;
  }
}

async function uploadRecording() {
  const blob = new Blob(chunks, { type: "audio/webm" });
  const form = new FormData();
  form.append("audio", blob, "meeting.webm");

  const response = await fetch("/api/meetings/audio", { method: "POST", body: form });
  if (!response.ok) {
    setStatus("Upload failed");
    startBtn.disabled = false;
    return;
  }

  const data = await response.json();
  meetingId = data.id;
  setStatus("Transcribing...");
  pollStatus();
  pollTimer = window.setInterval(pollStatus, 2500);
}

async function pollStatus() {
  if (!meetingId) return;
  const response = await fetch(`/api/meetings/${meetingId}/status`);
  const data = await response.json();
  renderState(data);
  if (["transcribed", "ready", "failed"].includes(data.status) && pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function renderState(data) {
  setStatus(data.error ? `${data.status}: ${data.error}` : data.status);
  renderTranscript(data.transcript || [], data.speaker_names || {});
  if (data.mom_markdown) {
    momOutput.classList.remove("empty");
    momOutput.textContent = data.mom_markdown;
    exportLinks.innerHTML = `<a href="/api/meetings/${data.id}/export.md">Markdown</a><a href="/api/meetings/${data.id}/export.pdf">PDF</a>`;
  }
  startBtn.disabled = data.status === "transcribing" || data.status === "generating";
  momBtn.disabled = !data.transcript || data.transcript.length === 0 || data.status === "transcribing" || data.status === "generating";
  saveSpeakersBtn.disabled = !data.transcript || data.transcript.length === 0;
}

function renderTranscript(transcript, speakerNames) {
  if (!transcript.length) {
    transcriptEl.className = "transcript empty";
    transcriptEl.textContent = "No transcript yet.";
    speakerEditor.innerHTML = "";
    return;
  }

  const speakers = [...new Set(transcript.map((turn) => turn.speaker))];
  speakerEditor.innerHTML = speakers
    .map((speaker) => {
      const value = speakerNames[speaker] || speaker;
      return `<label>${escapeHtml(speaker)}<input data-speaker="${escapeHtml(speaker)}" value="${escapeHtml(value)}" /></label>`;
    })
    .join("");

  transcriptEl.className = "transcript";
  transcriptEl.innerHTML = transcript
    .map((turn) => {
      const label = speakerNames[turn.speaker] || turn.speaker;
      return `<div class="turn"><span class="speaker">${escapeHtml(label)}</span><br />${escapeHtml(turn.text)}</div>`;
    })
    .join("");
}

async function saveSpeakers() {
  if (!meetingId) return;
  const speakers = {};
  speakerEditor.querySelectorAll("input").forEach((input) => {
    speakers[input.dataset.speaker] = input.value;
  });
  const response = await fetch(`/api/meetings/${meetingId}/speakers`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speakers }),
  });
  renderState(await response.json());
}

async function generateMom() {
  if (!meetingId) return;
  await saveSpeakers();
  setStatus("Generating MoM...");
  momBtn.disabled = true;
  const response = await fetch(`/api/meetings/${meetingId}/mom`, { method: "POST" });
  renderState(await response.json());
}

function setStatus(text) {
  statusText.textContent = text;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
