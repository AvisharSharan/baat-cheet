let recorder;
let chunks = [];
let meetingId = null;
let pollTimer = null;
let activeStreams = [];
let activeAudioContext = null;

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

startBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopRecording);
momBtn.addEventListener("click", generateMom);
saveSpeakersBtn.addEventListener("click", saveSpeakers);

async function startRecording() {
  try {
    const stream = captureMode.value === "meeting" ? await createMeetingCaptureStream() : await createMicrophoneStream();
    chunks = [];
    recorder = new MediaRecorder(stream, getRecorderOptions());
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      stopActiveCapture();
      uploadRecording();
    };
    recorder.start();
    setStatus("Recording...");
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
    setStatus("Uploading audio...");
    stopBtn.disabled = true;
  }
}

async function uploadRecording() {
  const blob = new Blob(chunks, { type: "audio/webm" });
  captureMode.disabled = false;
  speakerCount.disabled = false;
  if (!blob.size) {
    setStatus("No audio was recorded");
    startBtn.disabled = false;
    return;
  }
  const form = new FormData();
  form.append("audio", blob, "meeting.webm");
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
  captureMode.disabled = startBtn.disabled;
  speakerCount.disabled = startBtn.disabled;
  momBtn.disabled = !data.transcript || data.transcript.length === 0 || data.status === "transcribing" || data.status === "generating";
  saveSpeakersBtn.disabled = !data.transcript || data.transcript.length === 0;
}

function renderTranscript(transcript, speakerNames) {
  if (!transcript.length) {
    transcriptEl.className = "transcript empty";
    transcriptEl.innerHTML = "<strong>No transcript yet</strong><span>Start a recording and stop it when the meeting ends.</span>";
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
      return `<div class="turn"><span class="speaker">${escapeHtml(label)}</span><br />${escapeHtml(turn.text)}</div>`;
    })
    .join("");
}

function updateMetrics(transcript) {
  const speakers = new Set(transcript.map((turn) => turn.speaker));
  speakerMetric.textContent = String(speakers.size);
  turnMetric.textContent = String(transcript.length);
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
  setStatus("Generating notes...");
  momBtn.disabled = true;
  const response = await fetch(`/api/meetings/${meetingId}/mom`, { method: "POST" });
  renderState(await response.json());
}

function setStatus(text) {
  statusText.textContent = text;
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
