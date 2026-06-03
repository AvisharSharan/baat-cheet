let recorder;
let chunks = [];
let meetingId = null;
let pollTimer = null;
let activeStreams = [];
let activeAudioContext = null;
let liveAudioContext = null;
let liveSocket = null;
let liveAudioNodes = [];
let recordingUrl = null;
let liveTranscript = [];
let cleanupOverlayActive = false;
let cleanupGlow = null;
const liveSampleRate = 16000;

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
      stopLiveTranscription();
      stopActiveCapture();
      renderRecordingPlayback();
      uploadRecording();
    };
    await startLiveTranscription(stream);
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

async function startLiveTranscription(stream) {
  liveSocket = await createLiveSocket();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  liveAudioContext = new AudioContextClass();
  await liveAudioContext.audioWorklet.addModule("/static/pcm-worklet.js");

  const source = liveAudioContext.createMediaStreamSource(stream);
  const processor = new AudioWorkletNode(liveAudioContext, "pcm-capture-processor");
  const mutedOutput = liveAudioContext.createGain();
  mutedOutput.gain.value = 0;
  processor.port.onmessage = (event) => {
    if (!liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
    const pcm = downsampleToPcm16(event.data, liveAudioContext.sampleRate, liveSampleRate);
    if (pcm.byteLength > 0) liveSocket.send(pcm);
  };
  source.connect(processor);
  processor.connect(mutedOutput).connect(liveAudioContext.destination);
  liveAudioNodes = [source, processor, mutedOutput];
}

async function createLiveSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/api/live/transcribe`);
  socket.binaryType = "arraybuffer";
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "transcript" && payload.turns) {
      liveTranscript = liveTranscript.concat(payload.turns);
      renderTranscript(liveTranscript, { Live: "Live" });
      setStatus("Recording - live captions");
    }
    if (payload.type === "error") {
      setStatus(`Live captions failed: ${payload.message}`);
    }
  };
  socket.onclose = () => {
    liveSocket = null;
  };
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error("Live transcription connection failed"));
  });
  socket.onerror = () => setStatus("Live transcription connection failed");
  return socket;
}

function stopLiveTranscription() {
  if (liveSocket && liveSocket.readyState === WebSocket.OPEN) {
    liveSocket.send("stop");
  }
  if (liveAudioContext) {
    liveAudioNodes.forEach((node) => {
      try {
        node.disconnect();
      } catch (error) {
        // Node may already be disconnected during browser shutdown.
      }
    });
    liveAudioNodes = [];
    liveAudioContext.close();
    liveAudioContext = null;
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
  const finalTranscript = data.transcript || [];
  const keepLiveTranscript = data.status === "transcribing" && finalTranscript.length === 0 && liveTranscript.length > 0;
  if (finalTranscript.length > 0) {
    liveTranscript = [];
    cleanupOverlayActive = false;
    destroyCleanupGlow();
  }
  if (keepLiveTranscript && cleanupOverlayActive) {
    updateControls(data, finalTranscript);
    return;
  }
  renderTranscript(
    keepLiveTranscript ? liveTranscript : finalTranscript,
    keepLiveTranscript ? { Live: "Live captions" } : data.speaker_names || {},
    {
      cleanupOverlay: keepLiveTranscript,
      skipSpeakerEditor: keepLiveTranscript,
    },
  );
  cleanupOverlayActive = keepLiveTranscript;
  if (data.mom_markdown) {
    momOutput.classList.remove("mom-empty");
    momOutput.textContent = data.mom_markdown;
    exportLinks.innerHTML = `<a href="/api/meetings/${data.id}/export.md">Markdown</a><a href="/api/meetings/${data.id}/export.pdf">PDF</a>`;
  }
  updateControls(data, finalTranscript);
}

function updateControls(data, finalTranscript) {
  startBtn.disabled = data.status === "transcribing" || data.status === "generating";
  captureMode.disabled = startBtn.disabled;
  speakerCount.disabled = startBtn.disabled;
  momBtn.disabled = !finalTranscript.length || data.status === "transcribing" || data.status === "generating";
  saveSpeakersBtn.disabled = !finalTranscript.length;
}

function renderTranscript(transcript, speakerNames, options = {}) {
  if (!options.cleanupOverlay) destroyCleanupGlow();
  if (!transcript.length) {
    transcriptEl.className = "transcript transcript-empty";
    transcriptEl.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg width="32" height="32" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5" opacity="0.4"/><path d="M10 16 Q13 11 16 16 Q19 21 22 16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg></div><strong>No transcript yet</strong><span>Start recording to see live captions, then stop to finalize with Sarvam diarization.</span></div>';
    speakerEditor.innerHTML = "";
    updateMetrics([]);
    return;
  }

  const speakers = [...new Set(transcript.map((turn) => turn.speaker))];
  updateMetrics(transcript);
  speakerEditor.innerHTML = options.skipSpeakerEditor
    ? ""
    : speakers
        .map((speaker) => {
          const value = speakerNames[speaker] || speaker;
          return `<label>${escapeHtml(speaker)}<input data-speaker="${escapeHtml(speaker)}" value="${escapeHtml(value)}" /></label>`;
        })
        .join("");

  transcriptEl.className = "transcript";
  const cleanupOverlay = options.cleanupOverlay
    ? '<div class="cleanup-overlay" aria-live="polite"><div class="cleanup-dots"></div><div class="cleanup-glow"></div><div class="cleanup-text">Cleaning up with Sarvam</div></div>'
    : "";
  transcriptEl.innerHTML = cleanupOverlay + transcript
    .map((turn) => {
      const label = speakerNames[turn.speaker] || turn.speaker;
      return `<div class="turn"><span class="speaker">${escapeHtml(label)}</span><div class="turn-text">${escapeHtml(turn.text)}</div></div>`;
    })
    .join("");
  if (options.cleanupOverlay) mountCleanupGlow();
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
  liveTranscript = [];
  cleanupOverlayActive = false;
  destroyCleanupGlow();
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  clearRecordingPlayback();
  exportLinks.innerHTML = "";
  momOutput.className = "mom mom-empty";
  momOutput.textContent = "Finalize the transcript, then click Draft Minutes to generate.";
  renderTranscript([], {});
}

function mountCleanupGlow() {
  if (cleanupGlow) return;
  const target = transcriptEl.querySelector(".cleanup-dots");
  if (!target || !window.DottedGlowBackground) return;
  cleanupGlow = new window.DottedGlowBackground(target, {
    gap: 13,
    radius: 1.7,
    color: "rgba(224,187,106,0.66)",
    glowColor: "rgba(224,187,106,0.92)",
    opacity: 0.78,
    speedMin: 0.34,
    speedMax: 1.2,
    speedScale: 0.9,
  });
}

function destroyCleanupGlow() {
  if (!cleanupGlow) return;
  cleanupGlow.destroy();
  cleanupGlow = null;
}

function downsampleToPcm16(float32, inputSampleRate, outputSampleRate) {
  if (inputSampleRate === outputSampleRate) {
    return floatToPcm16(float32);
  }
  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.floor(float32.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), float32.length);
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += float32[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return floatToPcm16(output);
}

function floatToPcm16(float32) {
  const pcm = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32[i]));
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return pcm.buffer;
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
