let recorder;
let chunks = [];
let meetingId = null;
let pollTimer = null;
let activeStreams = [];
let activeAudioContext = null;
let recordingUrl = null;

const captureMode = document.querySelector("#captureMode");
const speakerCount = document.querySelector("#speakerCount");
const startBtn = document.querySelector("#startBtn");
const stopBtn = document.querySelector("#stopBtn");
const momBtn = document.querySelector("#momBtn");
const saveSpeakersBtn = document.querySelector("#saveSpeakersBtn");
const statusText = document.querySelector("#statusText");
const transcriptEl = document.querySelector("#transcript");
const speakerEditor = document.querySelector("#speakerEditor");
const momOutput = document.querySelector("#momOutput");
const exportLinks = document.querySelector("#exportLinks");
const speakerMetric = document.querySelector("#speakerMetric");
const turnMetric = document.querySelector("#turnMetric");
const wordMetric = document.querySelector("#wordMetric");
const playbackSection = document.querySelector("#playbackSection");
const recordingPlayback = document.querySelector("#recordingPlayback");
const downloadRecordingLink = document.querySelector("#downloadRecordingLink");

startBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopRecording);
momBtn.addEventListener("click", generateMom);
saveSpeakersBtn.addEventListener("click", saveSpeakers);

async function startRecording() {
  try {
    const stream = captureMode.value === "meeting" ? await createMeetingCaptureStream() : await createMicrophoneStream();
    resetSessionOutput();
    chunks = [];
    recorder = new MediaRecorder(stream, getRecorderOptions());
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      stopActiveCapture();
      renderRecordingPlayback();
      uploadRecording();
    };
    recorder.start();
    setStatus("Recording");
    captureMode.disabled = true;
    speakerCount.disabled = true;
    startBtn.disabled = true;
    stopBtn.disabled = false;
    momBtn.disabled = true;
  } catch (error) {
    stopActiveCapture();
    setStatus(error.message || "Could not start recording");
    captureMode.disabled = false;
    speakerCount.disabled = false;
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
}

function stopRecording() {
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
    setStatus("Uploading audio");
    stopBtn.disabled = true;
  }
}

async function uploadRecording() {
  const mimeType = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
  const blob = new Blob(chunks, { type: mimeType });
  captureMode.disabled = false;
  speakerCount.disabled = false;
  if (!blob.size) {
    setStatus("No audio was recorded");
    startBtn.disabled = false;
    return;
  }

  const form = new FormData();
  form.append("audio", blob, recordingFilename(mimeType));
  const expectedSpeakers = Number(speakerCount.value);
  if (Number.isInteger(expectedSpeakers) && expectedSpeakers >= 1 && expectedSpeakers <= 10) {
    form.append("num_speakers", String(expectedSpeakers));
  }

  const response = await fetch("/api/meetings/audio", { method: "POST", body: form });
  if (!response.ok) {
    setStatus("Upload failed");
    startBtn.disabled = false;
    return;
  }

  const data = await response.json();
  meetingId = data.id;
  setStatus("Transcribing with Sarvam");
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
  setStatus(statusLabel(data));
  renderTranscript(data.transcript || [], data.speaker_names || {});
  if (data.mom_markdown) {
    momOutput.classList.remove("mom-empty");
    momOutput.textContent = data.mom_markdown;
    exportLinks.innerHTML = `<a href="/api/meetings/${data.id}/export.md">Markdown</a><a href="/api/meetings/${data.id}/export.pdf">PDF</a>`;
  }
  startBtn.disabled = data.status === "transcribing" || data.status === "generating";
  captureMode.disabled = startBtn.disabled;
  speakerCount.disabled = startBtn.disabled;
  momBtn.disabled = !data.transcript || data.transcript.length === 0 || data.status === "transcribing" || data.status === "generating";
  saveSpeakersBtn.disabled = !data.transcript || data.transcript.length === 0;
}

function renderTranscript(transcript, speakerNames) {
  if (!transcript.length) {
    transcriptEl.className = "transcript transcript-empty";
    transcriptEl.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5" opacity="0.4"/><path d="M10 16 Q13 11 16 16 Q19 21 22 16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg></div><strong>No transcript yet</strong><span>Record the meeting, then stop to upload audio for Sarvam transcription.</span></div>';
    speakerEditor.innerHTML = "";
    updateMetrics([]);
    return;
  }

  const speakers = [...new Set(transcript.map((turn) => turn.speaker))];
  updateMetrics(transcript);
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
      return `<div class="turn"><span class="speaker">${escapeHtml(label)}</span><div class="turn-text">${escapeHtml(turn.text)}</div></div>`;
    })
    .join("");
}

function updateMetrics(transcript) {
  const speakers = new Set(transcript.map((turn) => turn.speaker));
  const words = transcript.reduce((count, turn) => count + turn.text.trim().split(/\s+/).filter(Boolean).length, 0);
  speakerMetric.textContent = String(speakers.size);
  turnMetric.textContent = String(transcript.length);
  wordMetric.textContent = words > 999 ? `${(words / 1000).toFixed(1)}k` : String(words);
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
  setStatus("Drafting minutes with Gemma");
  momBtn.disabled = true;
  const response = await fetch(`/api/meetings/${meetingId}/mom`, { method: "POST" });
  renderState(await response.json());
}

function setStatus(text) {
  statusText.textContent = text;
  const normalized = String(text).toLowerCase();
  document.body.dataset.recordingState = normalized.includes("recording") ? "recording" : "";
}

function statusLabel(data) {
  if (data.error) return `${data.status}: ${data.error}`;
  if (data.status === "uploaded") return "Uploaded";
  if (data.status === "transcribing") return "Transcribing with Sarvam";
  if (data.status === "transcribed") return "Transcript ready";
  if (data.status === "generating") return "Drafting minutes";
  if (data.status === "ready") return "Minutes ready";
  return data.status;
}

function resetSessionOutput() {
  meetingId = null;
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  clearRecordingPlayback();
  exportLinks.innerHTML = "";
  momOutput.className = "mom mom-empty";
  momOutput.textContent = "Transcribe the meeting, then click Draft Minutes to generate.";
  renderTranscript([], {});
}

function renderRecordingPlayback() {
  clearRecordingPlayback();
  if (!chunks.length) return;
  const mimeType = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
  const recording = new Blob(chunks, { type: mimeType });
  recordingUrl = URL.createObjectURL(recording);
  recordingPlayback.src = recordingUrl;
  downloadRecordingLink.href = recordingUrl;
  downloadRecordingLink.download = recordingFilename(mimeType);
  playbackSection.hidden = false;
}

function clearRecordingPlayback() {
  if (recordingUrl) {
    URL.revokeObjectURL(recordingUrl);
    recordingUrl = null;
  }
  recordingPlayback.removeAttribute("src");
  recordingPlayback.load();
  downloadRecordingLink.removeAttribute("href");
  playbackSection.hidden = true;
}

async function createMicrophoneStream() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  activeStreams = [stream];
  return stream;
}

async function createMeetingCaptureStream() {
  const displayStream = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: true,
  });
  const displayAudioTracks = displayStream.getAudioTracks();
  if (!displayAudioTracks.length) {
    displayStream.getTracks().forEach((track) => track.stop());
    throw new Error("No meeting audio was shared");
  }

  const micStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  activeAudioContext = new AudioContextClass();
  const destination = activeAudioContext.createMediaStreamDestination();
  activeAudioContext.createMediaStreamSource(new MediaStream(displayAudioTracks)).connect(destination);
  activeAudioContext.createMediaStreamSource(micStream).connect(destination);

  activeStreams = [displayStream, micStream, destination.stream];
  displayStream.getTracks().forEach((track) => {
    track.onended = () => {
      if (recorder && recorder.state !== "inactive") stopRecording();
    };
  });

  return destination.stream;
}

function stopActiveCapture() {
  activeStreams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
  activeStreams = [];
  if (activeAudioContext) {
    activeAudioContext.close();
    activeAudioContext = null;
  }
}

function getRecorderOptions() {
  const preferredTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
  return mimeType ? { mimeType } : {};
}

function recordingFilename(mimeType) {
  return mimeType.includes("mp4") ? "meeting-recording.mp4" : "meeting-recording.webm";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
