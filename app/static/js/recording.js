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
    recorder.onstop = async () => {
      try {
        isFinalizingRecording = true;
        setStatus(liveSocket ? "Finishing local captions..." : "Preparing final transcription...");
        await stopLiveTranscription({ waitForFinalChunk: true });
      } finally {
        stopActiveCapture();
        renderRecordingPlayback();
        await uploadRecording();
        isFinalizingRecording = false;
      }
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
  speakerLabelsToggle.disabled = active;
  speakerCount.disabled = active || !speakerLabelsToggle.checked;
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
    isFinalizingRecording = true;
    recorder.stop();
    setStatus(liveSocket ? "Finishing local captions..." : "Preparing final transcription...");
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
  const socket = new WebSocket(`${protocol}://${window.location.host}/api/live/transcribe?sample_rate=${liveSampleRate}&chunk_seconds=1&token=${encodeURIComponent(authToken)}`);
  socket.binaryType = "arraybuffer";
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "state" && payload.message && !isFinalizingRecording) {
      setStatus(payload.message);
    }
    if (payload.type === "transcript" && payload.turns) {
      liveTranscript = liveTranscript.concat(payload.turns);
      renderTranscript(liveTranscript, { Live: "Live" }, { skipSpeakerEditor: true, follow: true });
      if (!isFinalizingRecording) setStatus("Recording - local captions");
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

async function stopLiveTranscription(options = {}) {
  const socket = liveSocket;
  const waitForFinalChunk = Boolean(options.waitForFinalChunk);
  let closed = Promise.resolve();
  if (socket && socket.readyState !== WebSocket.CLOSED) {
    closed = new Promise((resolve) => {
      const timeout = window.setTimeout(resolve, 10000);
      socket.addEventListener("close", () => {
        window.clearTimeout(timeout);
        resolve();
      }, { once: true });
    });
  }
  if (socket && socket.readyState === WebSocket.OPEN) socket.send("stop");
  if (liveAudioContext) {
    liveAudioNodes.forEach((node) => { try { node.disconnect(); } catch (error) {} });
    liveAudioNodes = [];
    liveAudioContext.close();
    liveAudioContext = null;
  }
  if (waitForFinalChunk) await closed;
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

function inferredSpeakerCount() {
  const selected = Number(speakerCount.value);
  if (Number.isInteger(selected) && selected >= 1) return selected;
  const microphoneOnly = workflowMode.value !== "recorded" && captureMode.value === "microphone";
  return microphoneOnly && speakerLabelsToggle.checked ? 2 : NaN;
}

async function uploadMeetingFile(file, filename) {
  const form = new FormData();
  form.append("audio", file, filename);
  const expectedSpeakers = inferredSpeakerCount();
  if (speakerLabelsToggle.checked && Number.isInteger(expectedSpeakers) && expectedSpeakers >= 1 && expectedSpeakers <= 10) {
    form.append("num_speakers", String(expectedSpeakers));
  }
  form.append("speaker_labels_enabled", speakerLabelsToggle.checked ? "true" : "false");
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
  const voiceprintsStillRunning = data.status === "transcribed" && ["pending", "processing"].includes(data.voiceprint_status);
  if (["transcribed", "ready", "failed", "canceled"].includes(data.status) && pollTimer && !voiceprintsStillRunning) {
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
  const speakerLabelsEnabled = data.speaker_labels_enabled !== false;
  speakerLabelsToggle.checked = speakerLabelsEnabled;
  const isTranscribing = data.status === "uploaded" || data.status === "transcribing";
  const transcriptForDisplay = finalTranscript.length ? finalTranscript : (isTranscribing ? liveTranscript : []);
  if (finalTranscript.length > 0) liveTranscript = [];
  renderTranscript(
    transcriptForDisplay,
    finalTranscript.length ? (data.speaker_names || {}) : { Live: "Live" },
    {
      processing: isTranscribing,
      skipSpeakerEditor: !speakerLabelsEnabled || (!finalTranscript.length && transcriptForDisplay.length > 0),
      noSpeakerLabels: !speakerLabelsEnabled && finalTranscript.length > 0,
      follow: isTranscribing || !finalTranscript.length,
      editable: finalTranscript.length > 0 && !isTranscribing,
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
    const speakers = meeting.speaker_labels_enabled === false
      ? "No speaker labels"
      : (meeting.speakers && meeting.speakers.length ? meeting.speakers.join(", ") : "No speaker labels yet");
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
  const speakerLabelsEnabled = data.speaker_labels_enabled !== false;
  const voiceprintsReady = data.voiceprints_ready || data.voiceprint_status === "ready";
  setUploadBusy(busy);
  momBtn.disabled = !finalTranscript.length || data.status === "generating";
  momType.disabled = busy;
  cancelActionBtn.hidden = !busy;
  cancelActionBtn.disabled = !busy;
  saveSpeakersBtn.disabled = !speakerLabelsEnabled || !finalTranscript.length;
  rememberVoices.disabled = !speakerLabelsEnabled || !finalTranscript.length || !voiceprintsReady;
  rememberVoices.title = voiceprintHint(data);
}

// Stable key — skip redundant DOM rewrites when content hasn't changed
var _lastTranscriptKey = null;

function isTranscriptNearBottom() {
  return transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight < 80;
}

function scrollTranscriptToBottom() {
  window.requestAnimationFrame(() => {
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  });
}

function renderTranscript(transcript, speakerNames, options = {}) {
  if (panelTranscript) panelTranscript.classList.toggle("transcript-processing", Boolean(options.processing));

  if (!transcript.length) {
    if (_lastTranscriptKey !== "") {
      transcriptEl.className = "transcript transcript-empty";
      transcriptEl.innerHTML = `<div class="empty-state"><div class="empty-glyph"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="17" stroke="currentColor" stroke-width="1.2" opacity="0.3"/><path d="M12 20 Q16 13 20 20 Q24 27 28 20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.5"/></svg></div><strong>No transcript yet</strong><span>${escapeHtml(emptyTranscriptMessage())}</span></div>`;
      speakerEditor.innerHTML = "";
      speakerFooter.hidden = true;
      rememberVoices.checked = false;
      rememberVoices.disabled = true;
      updateMetrics([]);
      _lastTranscriptKey = "";
    }
    if (transcriptBadge) {
      transcriptBadge.textContent = options.processing ? "Processing" : "";
      transcriptBadge.hidden = !options.processing;
    }
    return;
  }

  // Key changes only when new turns arrive or the last turn's text updates
  const speakerNameKey = JSON.stringify(speakerNames || {});
  const contentKey = `${options.noSpeakerLabels ? "plain" : "labels"}::${speakerNameKey}::${transcript.length}::${transcript[transcript.length - 1]?.text ?? ""}`;

  const speakers = [...new Set(transcript.map((turn) => turn.speaker))];
  updateMetrics(transcript, { noSpeakerLabels: options.noSpeakerLabels });

  speakerEditor.innerHTML = options.skipSpeakerEditor ? "" : speakers.map((speaker) => {
    const value = speakerNames[speaker] || speaker;
    return `<label>${escapeHtml(speaker)}<input data-speaker="${escapeHtml(speaker)}" value="${escapeHtml(value)}" /></label>`;
  }).join("");

  speakerFooter.hidden = options.skipSpeakerEditor || !speakers.length;

  if (transcriptBadge) {
    transcriptBadge.textContent = options.processing ? "Finalizing" : (options.noSpeakerLabels ? "Plain transcript" : `${transcript.length} turns`);
    transcriptBadge.hidden = false;
  }

  // Skip the innerHTML rewrite entirely if nothing changed
  if (contentKey === _lastTranscriptKey) return;
  _lastTranscriptKey = contentKey;

  const shouldFollowTranscript = options.follow || isTranscriptNearBottom();
  transcriptEl.className = options.noSpeakerLabels ? "transcript transcript-plain" : "transcript";
  transcriptEl.innerHTML = transcript.map((turn, index) => {
    if (options.noSpeakerLabels) {
      return renderTurnHtml(turn, index, "", options);
    }
    const label = speakerNames[turn.speaker] || turn.speaker;
    return renderTurnHtml(turn, index, label, options);
  }).join("");
  bindTranscriptEditControls();
  if (shouldFollowTranscript) scrollTranscriptToBottom();
}

function renderTurnHtml(turn, index, label, options = {}) {
  const editing = editingTranscriptIndex === index;
  const speaker = label ? `<span class="speaker">${escapeHtml(label)}</span>` : "";
  const editButton = options.editable
    ? `<button class="turn-edit-btn" type="button" data-index="${index}" title="Edit transcript" aria-label="Edit transcript turn">
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="m13.5 6.5 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>`
    : "";
  const body = editing
    ? `<div class="turn-editor">
        <textarea class="turn-editor-input" data-index="${index}">${escapeHtml(turn.text)}</textarea>
        <div class="turn-editor-actions">
          <button class="btn btn-primary btn-sm turn-save-btn" type="button" data-index="${index}">Save</button>
          <button class="btn btn-ghost btn-sm turn-cancel-btn" type="button">Cancel</button>
        </div>
      </div>`
    : `<div class="turn-text">${escapeHtml(turn.text)}</div>`;
  return `<div class="turn" data-index="${index}">
    <div class="turn-main">
      <div class="turn-content">${speaker}${body}</div>
      ${editButton}
    </div>
  </div>`;
}

function bindTranscriptEditControls() {
  transcriptEl.querySelectorAll(".turn-edit-btn").forEach((button) => {
    button.addEventListener("click", () => {
      editingTranscriptIndex = Number(button.dataset.index);
      _lastTranscriptKey = null;
      pollStatus();
    });
  });
  transcriptEl.querySelectorAll(".turn-cancel-btn").forEach((button) => {
    button.addEventListener("click", () => {
      editingTranscriptIndex = null;
      _lastTranscriptKey = null;
      pollStatus();
    });
  });
  transcriptEl.querySelectorAll(".turn-save-btn").forEach((button) => {
    button.addEventListener("click", () => saveTranscriptTurn(Number(button.dataset.index)));
  });
}

async function saveTranscriptTurn(index) {
  if (!meetingId || !Number.isInteger(index)) return;
  const input = transcriptEl.querySelector(`.turn-editor-input[data-index="${index}"]`);
  const text = input ? input.value.trim() : "";
  if (!text) { setStatus("Transcript text cannot be blank"); return; }
  setStatus("Saving transcript edit...");
  const response = await apiFetch(`/api/meetings/${meetingId}/transcript`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index, text }),
  });
  if (!response.ok) {
    setStatus("Could not save transcript edit");
    return;
  }
  editingTranscriptIndex = null;
  _lastTranscriptKey = null;
  renderState(await response.json());
  loadHistory();
}

function updateMetrics(transcript, options = {}) {
  const speakers = new Set(transcript.map((turn) => turn.speaker));
  const words = transcript.reduce((count, turn) => count + turn.text.trim().split(/\s+/).filter(Boolean).length, 0);
  speakerMetric.textContent = options.noSpeakerLabels ? "Off" : (speakers.size || "—");
  turnMetric.textContent = transcript.length || "—";
  wordMetric.textContent = words > 999 ? `${(words / 1000).toFixed(1)}k` : (words || "—");
}

function voiceprintHint(data) {
  if (data.voiceprints_ready || data.voiceprint_status === "ready") return "Store local voice profiles for these labels";
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

async function generateMom(options = {}) {
  if (!meetingId) return;
  if (!options.skipSaveSpeakers && !speakerFooter.hidden) await saveSpeakers();
  setStatus("Drafting minutes…");
  momBtn.disabled = true;
  setMomGenerating(true);
  const response = await apiFetch(`/api/meetings/${meetingId}/mom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mom_type: momType.value || "auto" }),
  });
  if (!response.ok) {
    setStatus("Could not start minutes generation");
    setMomGenerating(false);
    return;
  }
  renderState(await response.json());
  pollStatus();
  if (!pollTimer) pollTimer = window.setInterval(pollStatus, 2500);
}

async function cancelActiveAction() {
  if (!meetingId) return;
  cancelActionBtn.disabled = true;
  setStatus("Canceling current action…");
  const response = await apiFetch(`/api/meetings/${meetingId}/cancel`, { method: "POST" });
  if (!response.ok) {
    setStatus("Could not cancel current action");
    cancelActionBtn.disabled = false;
    return;
  }
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  renderState(await response.json());
  loadHistory();
}

function setMomGenerating(active) {
  if (active) {
    panelMinutes.classList.add("mom-generating");
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
  if (data.error) return `${data.status}: ${shortStatusError(data.error)}`;
  if (data.status === "uploaded") return "Uploaded";
  if (data.status === "transcribing") return "Transcribing locally";
  if (data.status === "transcribed" && data.voiceprint_status === "processing") return "Matching saved speaker profiles";
  if (data.status === "transcribed") return "Transcript ready";
  if (data.status === "generating") return "Drafting minutes";
  if (data.status === "ready") return "Minutes ready";
  if (data.status === "canceled") return "Canceled";
  return data.status;
}

function shortStatusError(error) {
  const text = String(error || "").replace(/\s+/g, " ").trim();
  return text.length > 180 ? `${text.slice(0, 180).trim()}...` : text;
}

function resetSessionOutput() {
  meetingId = null;
  liveTranscript = [];
  isFinalizingRecording = false;
  _lastTranscriptKey = null;
  setMomGenerating(false);
  if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; }
  clearRecordingPlayback();
  exportLinks.innerHTML = "";
  momOutput.className = "mom mom-empty";
  momOutput.textContent = "Transcribe the meeting first, then click Draft Minutes to generate AI-powered minutes.";
  cancelActionBtn.hidden = true;
  cancelActionBtn.disabled = true;
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
  const speakerLabelsEnabled = speakerLabelsToggle.checked;

  realtimeOnly.hidden = recorded;
  recordedOnly.hidden = !recorded;

  startBtn.hidden = recorded;
  stopBtn.hidden = recorded;
  uploadRecordedBtn.hidden = !recorded;

  workflowMode.disabled = Boolean(recording);
  captureMode.disabled = recorded || Boolean(recording);
  liveCaptionsToggle.disabled = recorded || Boolean(recording);
  speakerLabelsToggle.disabled = Boolean(recording);
  speakerCount.disabled = Boolean(recording) || !speakerLabelsEnabled;
  startBtn.disabled = recorded || Boolean(recording);
  uploadRecordedBtn.disabled = !recorded || !recordedFile.files.length;
  recordedFile.disabled = false;

  if (recorded) {
    workflowHint.textContent = speakerLabelsEnabled
      ? "Upload a finished audio or video recording for batch transcription, speaker labels, and voice matching."
      : "Upload a finished audio or video recording for one plain transcript without speaker labels.";
    if (transcriptSub) transcriptSub.textContent = "Final transcript after upload";
  } else if (liveCaptionsToggle.checked) {
    workflowHint.textContent = speakerLabelsEnabled
      ? "Local captions preview during recording. Final upload still runs full diarized transcription."
      : "Local captions preview during recording. Final upload creates one plain transcript without speaker labels.";
    if (transcriptSub) transcriptSub.textContent = "Local captions during recording, final transcript after upload";
  } else {
    workflowHint.textContent = speakerLabelsEnabled
      ? "Record meeting audio, then finalize with local faster-whisper transcription and pyannote diarization."
      : "Record meeting audio, then finalize as one plain transcript without speaker labels.";
    if (transcriptSub) transcriptSub.textContent = "Final local transcript after upload";
  }
  refreshEmptyTranscriptMessage();
}

function setUploadBusy(busy) {
  const recorded = workflowMode.value === "recorded";
  workflowMode.disabled = busy || (recorder && recorder.state === "recording");
  captureMode.disabled = busy || recorded;
  liveCaptionsToggle.disabled = busy || recorded;
  speakerLabelsToggle.disabled = busy;
  speakerCount.disabled = busy || !speakerLabelsToggle.checked;
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

