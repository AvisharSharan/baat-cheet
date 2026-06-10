let recorder;
let chunks = [];
let meetingId = null;
let pollTimer = null;
let activeStreams = [];
let activeAudioContext = null;
let liveAudioContext = null;
let liveSocket = null;
let liveAudioNodes = [];
let liveTranscript = [];
let recordingUrl = null;
let recTimerInterval = null;
let recStartTime = null;
const liveSampleRate = 16000;
const authTokenKey = "momAuthToken";
let authToken = localStorage.getItem(authTokenKey) || "";
let currentUsername = "";

// DOM refs
const workflowMode       = document.querySelector("#workflowMode");
const modeBtns           = document.querySelectorAll(".mode-btn");
const captureMode        = document.querySelector("#captureMode");
const liveCaptionsToggle = document.querySelector("#liveCaptionsToggle");
const realtimeOnly       = document.querySelector(".realtime-only");
const recordedOnly       = document.querySelector(".recorded-only");
const recordedSettings   = document.querySelectorAll(".recorded-setting");
const recordedFile       = document.querySelector("#recordedFile");
const fileDropZone       = document.querySelector("#fileDropZone");
const fileDropLabel      = document.querySelector("#fileDropLabel");
const uploadRecordedBtn  = document.querySelector("#uploadRecordedBtn");
const speakerCount       = document.querySelector("#speakerCount");
const startBtn           = document.querySelector("#startBtn");
const stopBtn            = document.querySelector("#stopBtn");
const momBtn             = document.querySelector("#momBtn");
const saveSpeakersBtn    = document.querySelector("#saveSpeakersBtn");
const statusText         = document.querySelector("#statusText");
const transcriptEl       = document.querySelector("#transcript");
const speakerEditor      = document.querySelector("#speakerEditor");
const speakerFooter      = document.querySelector("#speakerFooter");
const rememberVoices     = document.querySelector("#rememberVoices");
const momOutput          = document.querySelector("#momOutput");
const exportLinks        = document.querySelector("#exportLinks");
const panelMinutes       = document.querySelector(".panel-minutes");
const speakerMetric      = document.querySelector("#speakerMetric");
const turnMetric         = document.querySelector("#turnMetric");
const wordMetric         = document.querySelector("#wordMetric");
const playbackSection    = document.querySelector("#playbackSection");
const recordingPlayback  = document.querySelector("#recordingPlayback");
const downloadRecordingLink = document.querySelector("#downloadRecordingLink");
const workflowHint       = document.querySelector("#workflowHint");
const transcriptSub      = document.querySelector("#transcriptSub");
const themeToggle        = document.querySelector("#themeToggle");
const meetingName        = document.querySelector("#meetingName");
const newMeetingBtn      = document.querySelector("#newMeetingBtn");
const historyTabBtn      = document.querySelector("#historyTabBtn");
const refreshHistoryBtn  = document.querySelector("#refreshHistoryBtn");
const meetingView        = document.querySelector("#meetingView");
const historyView        = document.querySelector("#historyView");
const historyList        = document.querySelector("#historyList");
const recordingStatus    = document.querySelector("#recordingStatus");
const recTimer           = document.querySelector("#recTimer");
const transcriptBadge    = document.querySelector("#transcriptBadge");
const emptyTranscriptMsg = document.querySelector("#emptyTranscriptMsg");
const loginView          = document.querySelector("#loginView");
const loginForm          = document.querySelector("#loginForm");
const loginUsername      = document.querySelector("#loginUsername");
const loginPassword      = document.querySelector("#loginPassword");
const loginBtn           = document.querySelector("#loginBtn");
const loginError         = document.querySelector("#loginError");
const userChip           = document.querySelector("#userChip");
const logoutBtn          = document.querySelector("#logoutBtn");

// Init
modeBtns.forEach(btn => btn.addEventListener("click", () => setWorkflowMode(btn.dataset.mode)));
recordedFile.addEventListener("change", onFileChange);
liveCaptionsToggle.addEventListener("change", updateLiveCaptionPreference);
startBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopRecording);
uploadRecordedBtn.addEventListener("click", uploadRecordedFile);
momBtn.addEventListener("click", generateMom);
saveSpeakersBtn.addEventListener("click", saveSpeakers);
themeToggle.addEventListener("click", toggleTheme);
newMeetingBtn.addEventListener("click", startNewMeeting);
historyTabBtn.addEventListener("click", showHistory);
refreshHistoryBtn.addEventListener("click", loadHistory);
loginForm.addEventListener("submit", login);
logoutBtn.addEventListener("click", logout);

// File drag-and-drop
fileDropZone.addEventListener("dragover", (e) => { e.preventDefault(); fileDropZone.classList.add("drag-over"); });
fileDropZone.addEventListener("dragleave", () => fileDropZone.classList.remove("drag-over"));
fileDropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  fileDropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    recordedFile.files = dt.files;
    onFileChange();
  }
});

syncThemeToggle();
syncLiveCaptionPreference();
updateWorkflowUI();
meetingName.value = defaultMeetingName();
bootstrapAuth();

// AUTH
async function bootstrapAuth() {
  if (!authToken) {
    showLogin();
    return;
  }
  try {
    const response = await apiFetch("/api/auth/me");
    if (!response.ok) throw new Error("Session expired");
    const user = await response.json();
    showApp(user.username);
  } catch (error) {
    authToken = "";
    localStorage.removeItem(authTokenKey);
    showLogin();
  }
}

async function login(event) {
  event.preventDefault();
  loginError.hidden = true;
  loginBtn.disabled = true;
  const label = loginBtn.querySelector("span");
  const previousLabel = label ? label.textContent : loginBtn.textContent;
  if (label) label.textContent = "Signing in";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: loginUsername.value.trim(),
        password: loginPassword.value,
      }),
    });
    if (!response.ok) throw new Error("Invalid username or password");
    const data = await response.json();
    authToken = data.access_token;
    currentUsername = data.username;
    localStorage.setItem(authTokenKey, authToken);
    loginPassword.value = "";
    showApp(currentUsername);
  } catch (error) {
    loginError.textContent = error.message || "Could not sign in";
    loginError.hidden = false;
  } finally {
    loginBtn.disabled = false;
    if (label) label.textContent = previousLabel;
  }
}

function logout() {
  authToken = "";
  currentUsername = "";
  localStorage.removeItem(authTokenKey);
  stopLiveTranscription();
  stopActiveCapture();
  if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; }
  showLogin();
}

function showLogin() {
  document.body.classList.add("auth-pending");
  loginView.hidden = false;
  userChip.hidden = true;
  logoutBtn.hidden = true;
  setStatus("Sign in required");
  window.setTimeout(() => loginUsername.focus(), 0);
}

function showApp(username) {
  currentUsername = username || currentUsername;
  document.body.classList.remove("auth-pending");
  loginView.hidden = true;
  userChip.textContent = currentUsername;
  userChip.hidden = false;
  logoutBtn.hidden = false;
  setStatus("Ready");
  loadHistory();
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    authToken = "";
    localStorage.removeItem(authTokenKey);
    showLogin();
  }
  return response;
}

// ─── RECORDING ────────────────────────────────────────────────
async function startRecording() {
  try {
    const stream = captureMode.value === "meeting"
      ? await createMeetingCaptureStream()
      : await createMicrophoneStream();
    resetSessionOutput();
    chunks = [];
    recorder = new MediaRecorder(stream, getRecorderOptions());
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = () => {
      stopLiveTranscription();
      stopActiveCapture();
      renderRecordingPlayback();
      uploadRecording();
    };
    if (liveCaptionsToggle.checked) await startLiveTranscription(stream);
    recorder.start();
    setStatus(liveCaptionsToggle.checked ? "Recording - local captions" : "Recording");
    setRecordingState(true);
  } catch (error) {
    stopActiveCapture();
    setStatus(error.message || "Could not start recording");
    updateWorkflowUI();
    stopBtn.disabled = true;
  }
}

function setRecordingState(active) {
  workflowMode.disabled = active;
  captureMode.disabled = active;
  liveCaptionsToggle.disabled = active;
  speakerCount.disabled = active;
  startBtn.disabled = active;
  stopBtn.disabled = !active;
  momBtn.disabled = true;

  // Show/hide recording timer
  recordingStatus.hidden = !active;
  if (active) {
    recStartTime = Date.now();
    updateRecTimer();
    recTimerInterval = window.setInterval(updateRecTimer, 1000);
  } else {
    window.clearInterval(recTimerInterval);
    recTimerInterval = null;
  }
}

function updateRecTimer() {
  if (!recStartTime) return;
  const elapsed = Math.floor((Date.now() - recStartTime) / 1000);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  recTimer.textContent = `${m}:${s.toString().padStart(2, "0")}`;
}

function stopRecording() {
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
    setStatus("Uploading audio…");
    setRecordingState(false);
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
  const socket = new WebSocket(`${protocol}://${window.location.host}/api/live/transcribe?sample_rate=${liveSampleRate}&chunk_seconds=2&token=${encodeURIComponent(authToken)}`);
  socket.binaryType = "arraybuffer";
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "state" && payload.message) {
      setStatus(payload.message);
    }
    if (payload.type === "transcript" && payload.turns) {
      liveTranscript = liveTranscript.concat(payload.turns);
      renderTranscript(liveTranscript, { Live: "Live" }, { skipSpeakerEditor: true });
      setStatus("Recording - local captions");
    }
    if (payload.type === "error") setStatus(`Local captions failed: ${payload.message}`);
  };
  socket.onclose = () => { liveSocket = null; };
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error("Local caption connection failed"));
  });
  socket.onerror = () => setStatus("Local caption connection failed");
  return socket;
}

function stopLiveTranscription() {
  if (liveSocket && liveSocket.readyState === WebSocket.OPEN) liveSocket.send("stop");
  if (liveAudioContext) {
    liveAudioNodes.forEach((node) => { try { node.disconnect(); } catch (error) {} });
    liveAudioNodes = [];
    liveAudioContext.close();
    liveAudioContext = null;
  }
}

async function uploadRecording() {
  const mimeType = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
  const blob = new Blob(chunks, { type: mimeType });
  updateWorkflowUI();
  if (!blob.size) { setStatus("No audio was recorded"); startBtn.disabled = false; return; }
  await uploadMeetingFile(blob, recordingFilename(mimeType));
}

async function uploadRecordedFile() {
  const file = recordedFile.files[0];
  if (!file) { setStatus("Choose a recorded audio or video file"); return; }
  resetSessionOutput();
  await uploadMeetingFile(file, file.name || "recorded-meeting");
}

async function uploadMeetingFile(file, filename) {
  const form = new FormData();
  form.append("audio", file, filename);
  const expectedSpeakers = Number(speakerCount.value);
  if (Number.isInteger(expectedSpeakers) && expectedSpeakers >= 1 && expectedSpeakers <= 10) {
    form.append("num_speakers", String(expectedSpeakers));
  }
  if (meetingName.value.trim()) form.append("meeting_name", meetingName.value.trim());

  setStatus("Uploading recording…");
  setUploadBusy(true);

  const response = await apiFetch("/api/meetings/audio", { method: "POST", body: form });
  if (!response.ok) { setStatus("Upload failed"); setUploadBusy(false); return; }

  const data = await response.json();
  meetingId = data.id;
  meetingName.value = data.name || meetingName.value;
  setStatus("Transcribing locally…");
  showMeeting();
  loadHistory();
  pollStatus();
  pollTimer = window.setInterval(pollStatus, 2500);
}

async function pollStatus() {
  if (!meetingId) return;
  const response = await apiFetch(`/api/meetings/${meetingId}/status`);
  const data = await response.json();
  renderState(data);
  if (["transcribed", "ready", "failed"].includes(data.status) && pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
    loadHistory();
  }
}

function renderState(data) {
  if (data.id) meetingId = data.id;
  if (data.name) meetingName.value = data.name;
  setStatus(statusLabel(data));
  const finalTranscript = data.transcript || [];
  const isTranscribing = data.status === "uploaded" || data.status === "transcribing";
  const transcriptForDisplay = finalTranscript.length ? finalTranscript : (isTranscribing ? liveTranscript : []);
  if (finalTranscript.length > 0) liveTranscript = [];
  renderTranscript(
    transcriptForDisplay,
    finalTranscript.length ? (data.speaker_names || {}) : { Live: "Live" },
    {
      processing: isTranscribing,
      skipSpeakerEditor: !finalTranscript.length && transcriptForDisplay.length > 0,
    },
  );
  if (data.mom_markdown) {
    setMomGenerating(false);
    momOutput.classList.remove("mom-empty");
    momOutput.textContent = data.mom_markdown;
    exportLinks.innerHTML = `
      <a href="/api/meetings/${data.id}/export.md?token=${encodeURIComponent(authToken)}">
        <svg width="11" height="11" viewBox="0 0 11 11"><path d="M1 10V1h6l3 3v6H1Z" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linejoin="round"/><path d="M7 1v3h3" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
        MD
      </a>
      <a href="/api/meetings/${data.id}/export.pdf?token=${encodeURIComponent(authToken)}">
        <svg width="11" height="11" viewBox="0 0 11 11"><path d="M1 10V1h6l3 3v6H1Z" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linejoin="round"/><path d="M7 1v3h3" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
        PDF
      </a>`;
  }
  if (data.status !== "generating") setMomGenerating(false);
  updateControls(data, finalTranscript);
}

async function loadHistory() {
  try {
    const response = await apiFetch("/api/meetings");
    if (!response.ok) throw new Error("Could not load meeting history");
    renderHistory(await response.json());
  } catch (error) {
    historyList.innerHTML = `<div class="empty-state"><strong>History unavailable</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

function renderHistory(meetings) {
  if (!meetings.length) {
    historyList.innerHTML = `<div class="empty-state"><div class="empty-glyph"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="15" stroke="currentColor" stroke-width="1.2" opacity="0.35"/><path d="M20 11v10l6 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity="0.5"/></svg></div><strong>No meetings yet</strong><span>Completed meetings will appear here with their transcript and minutes.</span></div>`;
    return;
  }
  historyList.innerHTML = meetings.map((meeting) => {
    const speakers = meeting.speakers && meeting.speakers.length ? meeting.speakers.join(", ") : "No speaker labels yet";
    const active = meeting.id === meetingId ? " active" : "";
    return `<div class="history-item${active}" data-meeting-id="${escapeHtml(meeting.id)}">
      <button class="history-open" type="button" data-meeting-id="${escapeHtml(meeting.id)}">
      <div class="history-item-main">
        <span class="history-name">${escapeHtml(meeting.name)}</span>
        <span class="history-meta">${escapeHtml(formatDateTime(meeting.created_at))}</span>
      </div>
      <div class="history-badges">
        <span>${escapeHtml(statusLabel(meeting))}</span>
        <span>${meeting.transcript_turns} turns</span>
        <span>${meeting.word_count} words</span>
        ${meeting.mom_available ? "<span>Minutes ✓</span>" : ""}
      </div>
        <div class="history-speakers">${escapeHtml(speakers)}</div>
      </button>
      <div class="history-actions">
        <button class="history-delete" type="button" data-meeting-id="${escapeHtml(meeting.id)}" data-meeting-name="${escapeHtml(meeting.name)}" title="Delete meeting" aria-label="Delete ${escapeHtml(meeting.name)}">
          <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      </div>
    </div>`;
  }).join("");

  historyList.querySelectorAll(".history-open").forEach((item) => {
    item.addEventListener("click", () => openHistoryMeeting(item.dataset.meetingId));
  });
  historyList.querySelectorAll(".history-delete").forEach((item) => {
    item.addEventListener("click", () => deleteHistoryMeeting(item.dataset.meetingId, item.dataset.meetingName));
  });
}

async function openHistoryMeeting(id) {
  if (!id) return;
  const response = await apiFetch(`/api/meetings/${id}/status`);
  if (!response.ok) { setStatus("Meeting not found"); return; }
  renderState(await response.json());
  showMeeting();
  loadHistory();
}

async function deleteHistoryMeeting(id, name) {
  if (!id) return;
  const label = name || "this meeting";
  if (!window.confirm(`Delete "${label}" from history?`)) return;
  const response = await apiFetch(`/api/meetings/${id}`, { method: "DELETE" });
  if (!response.ok) {
    setStatus("Could not delete meeting");
    return;
  }
  if (id === meetingId) {
    resetSessionOutput();
    meetingName.value = defaultMeetingName();
  }
  setStatus("Meeting deleted");
  loadHistory();
}

function startNewMeeting() {
  resetSessionOutput();
  meetingName.value = defaultMeetingName();
  showMeeting();
  setStatus("Ready");
}

function showHistory() {
  historyView.hidden = false;
  meetingView.hidden = true;
  historyTabBtn.classList.add("active");
  newMeetingBtn.classList.remove("active");
  loadHistory();
}

function showMeeting() {
  meetingView.hidden = false;
  historyView.hidden = true;
  newMeetingBtn.classList.add("active");
  historyTabBtn.classList.remove("active");
}

function updateControls(data, finalTranscript) {
  const busy = data.status === "transcribing" || data.status === "generating";
  setUploadBusy(busy);
  momBtn.disabled = !finalTranscript.length || data.status === "generating";
  saveSpeakersBtn.disabled = !finalTranscript.length;
  rememberVoices.disabled = !finalTranscript.length || !data.voiceprints_ready;
  rememberVoices.title = voiceprintHint(data);
}

function renderTranscript(transcript, speakerNames, options = {}) {
  if (!transcript.length) {
    transcriptEl.className = "transcript transcript-empty";
    transcriptEl.innerHTML = options.processing
      ? aiProcessingBlock("Final transcription running", "Keeping captions here while the local diarized transcript is prepared.")
      : `<div class="empty-state"><div class="empty-glyph"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="17" stroke="currentColor" stroke-width="1.2" opacity="0.3"/><path d="M12 20 Q16 13 20 20 Q24 27 28 20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.5"/></svg></div><strong>No transcript yet</strong><span>${escapeHtml(emptyTranscriptMessage())}</span></div>`;
    speakerEditor.innerHTML = "";
    speakerFooter.hidden = true;
    rememberVoices.checked = false;
    rememberVoices.disabled = true;
    updateMetrics([]);
    if (transcriptBadge) {
      transcriptBadge.textContent = options.processing ? "Processing" : "";
      transcriptBadge.hidden = !options.processing;
    }
    return;
  }

  const speakers = [...new Set(transcript.map((turn) => turn.speaker))];
  updateMetrics(transcript);

  speakerEditor.innerHTML = options.skipSpeakerEditor ? "" : speakers.map((speaker) => {
    const value = speakerNames[speaker] || speaker;
    return `<label>${escapeHtml(speaker)}<input data-speaker="${escapeHtml(speaker)}" value="${escapeHtml(value)}" /></label>`;
  }).join("");

  speakerFooter.hidden = options.skipSpeakerEditor || !speakers.length;

  // Show badge with turn count
  if (transcriptBadge) {
    transcriptBadge.textContent = options.processing ? "Finalizing" : `${transcript.length} turns`;
    transcriptBadge.hidden = false;
  }

  transcriptEl.className = "transcript";
  const processingBanner = options.processing
    ? aiProcessingBanner("Final transcription running", "Live captions stay visible until the diarized transcript is ready.")
    : "";
  transcriptEl.innerHTML = processingBanner + transcript.map((turn) => {
    const label = speakerNames[turn.speaker] || turn.speaker;
    return `<div class="turn"><span class="speaker">${escapeHtml(label)}</span><div class="turn-text">${escapeHtml(turn.text)}</div></div>`;
  }).join("");
}

function updateMetrics(transcript) {
  const speakers = new Set(transcript.map((turn) => turn.speaker));
  const words = transcript.reduce((count, turn) => count + turn.text.trim().split(/\s+/).filter(Boolean).length, 0);
  speakerMetric.textContent = speakers.size || "—";
  turnMetric.textContent = transcript.length || "—";
  wordMetric.textContent = words > 999 ? `${(words / 1000).toFixed(1)}k` : (words || "—");
}

function voiceprintHint(data) {
  if (data.voiceprints_ready) return "Store local voice profiles for these labels";
  if (data.voiceprint_error) return data.voiceprint_error;
  if (data.voiceprint_status === "processing") return "Voiceprints are being prepared";
  if (data.voiceprint_status === "pending") return "Voiceprints become available after final transcription";
  return "Voiceprints are not available for this transcript";
}

async function saveSpeakers() {
  if (!meetingId) return;
  const speakers = {};
  speakerEditor.querySelectorAll("input").forEach((input) => {
    speakers[input.dataset.speaker] = input.value;
  });
  const response = await apiFetch(`/api/meetings/${meetingId}/speakers`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speakers, remember_voices: rememberVoices.checked }),
  });
  renderState(await response.json());
}

async function generateMom() {
  if (!meetingId) return;
  await saveSpeakers();
  setStatus("Drafting minutes…");
  momBtn.disabled = true;
  setMomGenerating(true);
  const response = await apiFetch(`/api/meetings/${meetingId}/mom`, { method: "POST" });
  renderState(await response.json());
}

function setMomGenerating(active) {
  if (active) {
    panelMinutes.classList.add("mom-generating");
    if (!panelMinutes.querySelector(".mom-generating-label")) {
      const label = document.createElement("div");
      label.className = "mom-generating-label";
      label.innerHTML = aiProcessingInline("Drafting minutes", "Structuring decisions, actions, and open questions.");
      panelMinutes.appendChild(label);
    }
  } else {
    panelMinutes.classList.remove("mom-generating");
    const label = panelMinutes.querySelector(".mom-generating-label");
    if (label) label.remove();
  }
}

function setStatus(text) {
  statusText.textContent = text;
  const n = String(text).toLowerCase();
  if (n.includes("recording")) {
    document.body.dataset.state = "recording";
  } else if (n.includes("upload") || n.includes("transcrib") || n.includes("drafting")) {
    document.body.dataset.state = "processing";
  } else {
    document.body.dataset.state = "";
  }
}

function statusLabel(data) {
  if (data.error) return `${data.status}: ${data.error}`;
  if (data.status === "uploaded") return "Uploaded";
  if (data.status === "transcribing") return "Transcribing locally";
  if (data.status === "transcribed") return "Transcript ready";
  if (data.status === "generating") return "Drafting minutes";
  if (data.status === "ready") return "Minutes ready";
  return data.status;
}

function resetSessionOutput() {
  meetingId = null;
  liveTranscript = [];
  setMomGenerating(false);
  if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; }
  clearRecordingPlayback();
  exportLinks.innerHTML = "";
  momOutput.className = "mom mom-empty";
  momOutput.textContent = "Transcribe the meeting first, then click Draft Minutes to generate AI-powered minutes.";
  renderTranscript([], {});
  updateWorkflowUI();
}

// ─── WORKFLOW MODE ─────────────────────────────────────────────
function setWorkflowMode(mode) {
  workflowMode.value = mode;
  modeBtns.forEach(btn => btn.classList.toggle("active", btn.dataset.mode === mode));
  updateWorkflowUI();
}

function onFileChange() {
  const file = recordedFile.files[0];
  if (file) {
    fileDropLabel.textContent = file.name;
    fileDropZone.style.borderStyle = "solid";
    fileDropZone.style.borderColor = "var(--gold)";
  } else {
    fileDropLabel.textContent = "Drop file or click to browse";
    fileDropZone.style.borderStyle = "";
    fileDropZone.style.borderColor = "";
  }
  updateWorkflowUI();
}

function updateWorkflowUI() {
  const recorded = workflowMode.value === "recorded";
  const recording = recorder && recorder.state === "recording";

  realtimeOnly.hidden = recorded;
  recordedOnly.hidden = !recorded;

  startBtn.hidden = recorded;
  stopBtn.hidden = recorded;
  uploadRecordedBtn.hidden = !recorded;

  workflowMode.disabled = Boolean(recording);
  captureMode.disabled = recorded || Boolean(recording);
  liveCaptionsToggle.disabled = recorded || Boolean(recording);
  speakerCount.disabled = Boolean(recording);
  startBtn.disabled = recorded || Boolean(recording);
  uploadRecordedBtn.disabled = !recorded || !recordedFile.files.length;
  recordedFile.disabled = false;

  if (recorded) {
    workflowHint.textContent = "Upload a finished audio or video recording for batch transcription, speaker labels, and voice matching.";
    if (transcriptSub) transcriptSub.textContent = "Final transcript after upload";
  } else if (liveCaptionsToggle.checked) {
    workflowHint.textContent = "Local captions preview during recording. Final upload still runs full diarized transcription.";
    if (transcriptSub) transcriptSub.textContent = "Local captions during recording, final transcript after upload";
  } else {
    workflowHint.textContent = "Record meeting audio, then finalize with local faster-whisper transcription and pyannote diarization.";
    if (transcriptSub) transcriptSub.textContent = "Final local transcript after upload";
  }
  refreshEmptyTranscriptMessage();
}

function setUploadBusy(busy) {
  const recorded = workflowMode.value === "recorded";
  workflowMode.disabled = busy || (recorder && recorder.state === "recording");
  captureMode.disabled = busy || recorded;
  liveCaptionsToggle.disabled = busy || recorded;
  speakerCount.disabled = busy;
  startBtn.disabled = busy || recorded;
  uploadRecordedBtn.disabled = busy || !recorded || !recordedFile.files.length;
  recordedFile.disabled = busy;
}

// ─── CLEANUP GLOW ─────────────────────────────────────────────
function aiProcessingBanner(title, detail) {
  return `<div class="ai-processing-banner" aria-live="polite">${aiProcessingInline(title, detail)}</div>`;
}

function aiProcessingBlock(title, detail) {
  return `<div class="ai-processing-block" aria-live="polite">${aiProcessingInline(title, detail)}</div>`;
}

function aiProcessingInline(title, detail) {
  return `<div class="loading-copy"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>
    <div class="loading-gradient" aria-hidden="true"></div>`;
}

// ─── AUDIO UTILS ──────────────────────────────────────────────
function downsampleToPcm16(float32, inputSampleRate, outputSampleRate) {
  if (inputSampleRate === outputSampleRate) return floatToPcm16(float32);
  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.floor(float32.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), float32.length);
    let sum = 0;
    for (let j = start; j < end; j++) sum += float32[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return floatToPcm16(output);
}

function floatToPcm16(float32) {
  const pcm = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
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
  if (recordingUrl) { URL.revokeObjectURL(recordingUrl); recordingUrl = null; }
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
  const displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
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
    track.onended = () => { if (recorder && recorder.state !== "inactive") stopRecording(); };
  });
  return destination.stream;
}

function stopActiveCapture() {
  activeStreams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
  activeStreams = [];
  if (activeAudioContext) { activeAudioContext.close(); activeAudioContext = null; }
}

function getRecorderOptions() {
  const preferredTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
  return mimeType ? { mimeType } : {};
}

function recordingFilename(mimeType) {
  return mimeType.includes("mp4") ? "meeting-recording.mp4" : "meeting-recording.webm";
}

// ─── HELPERS ──────────────────────────────────────────────────
function defaultMeetingName() {
  const now = new Date();
  return `Meeting ${now.toLocaleDateString([], { month: "short", day: "numeric" })} ${now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function formatDateTime(value) {
  if (!value) return "Time unavailable";
  return new Date(value).toLocaleString([], {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function toggleTheme() {
  const nextTheme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  if (nextTheme === "light") {
    document.documentElement.dataset.theme = "light";
    localStorage.setItem("momTheme", "light");
  } else {
    delete document.documentElement.dataset.theme;
    localStorage.setItem("momTheme", "dark");
  }
  syncThemeToggle();
}

function syncThemeToggle() {
  const light = document.documentElement.dataset.theme === "light";
  themeToggle.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
  themeToggle.title = light ? "Switch to dark theme" : "Switch to light theme";
}

function updateLiveCaptionPreference() {
  localStorage.setItem("momLiveCaptions", liveCaptionsToggle.checked ? "on" : "off");
  if (!liveCaptionsToggle.checked) liveTranscript = [];
  updateWorkflowUI();
}

function syncLiveCaptionPreference() {
  liveCaptionsToggle.checked = localStorage.getItem("momLiveCaptions") !== "off";
}

function emptyTranscriptMessage() {
  if (workflowMode.value === "recorded") return "Upload a recording to create a local diarized transcript.";
  return liveCaptionsToggle.checked
    ? "Start recording to see local caption previews, then stop for the final diarized transcript."
    : "Start recording, then stop to finalize with local transcription and diarization.";
}

function refreshEmptyTranscriptMessage() {
  const msg = document.querySelector("#emptyTranscriptMsg");
  if (msg) msg.textContent = emptyTranscriptMessage();
}
