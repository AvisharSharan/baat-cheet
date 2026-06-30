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

function selectedMicrophoneDeviceId() {
  return microphoneDevice ? microphoneDevice.value : "";
}

function microphoneAudioConstraints() {
  const deviceId = selectedMicrophoneDeviceId();
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  if (deviceId) audio.deviceId = { exact: deviceId };
  return audio;
}

function ensureMediaCaptureSupported() {
  const reason = mediaCaptureUnavailableReason();
  if (reason) throw new Error(reason);
}

function mediaCaptureUnavailableReason() {
  if (!window.isSecureContext) {
    return "Microphone access is blocked on this address. Open the app on localhost, or use HTTPS for phone/LAN recording.";
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return "This browser does not expose microphone recording. Try Chrome/Safari over HTTPS.";
  }
  if (typeof MediaRecorder === "undefined") {
    return "This browser does not support in-page audio recording.";
  }
  return "";
}

async function createMicrophoneStream() {
  ensureMediaCaptureSupported();
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: microphoneAudioConstraints(),
  });
  activeStreams = [stream];
  refreshAudioInputDevices();
  return stream;
}

async function createMeetingCaptureStream() {
  ensureMediaCaptureSupported();
  if (!navigator.mediaDevices.getDisplayMedia) {
    captureMode.value = "microphone";
    updateWorkflowUI();
    setStatus("Meeting-tab capture is not available here. Recording microphone only.");
    return createMicrophoneStream();
  }
  const displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
  const displayAudioTracks = displayStream.getAudioTracks();
  if (!displayAudioTracks.length) {
    displayStream.getTracks().forEach((track) => track.stop());
    throw new Error("No meeting audio was shared");
  }
  const micStream = await navigator.mediaDevices.getUserMedia({
    audio: microphoneAudioConstraints(),
  });
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  activeAudioContext = new AudioContextClass();
  const destination = activeAudioContext.createMediaStreamDestination();
  activeAudioContext.createMediaStreamSource(new MediaStream(displayAudioTracks)).connect(destination);
  activeAudioContext.createMediaStreamSource(micStream).connect(destination);
  activeStreams = [displayStream, micStream, destination.stream];
  refreshAudioInputDevices();
  displayStream.getTracks().forEach((track) => {
    track.onended = () => { if (recorder && recorder.state !== "inactive") stopRecording(); };
  });
  return destination.stream;
}

async function refreshAudioInputDevices() {
  if (!microphoneDevice || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
  const previousValue = microphoneDevice.value;
  let devices = [];
  try {
    devices = await navigator.mediaDevices.enumerateDevices();
  } catch (error) {
    return;
  }

  const audioInputs = devices.filter((device) => device.kind === "audioinput");
  const defaultOption = new Option("Default microphone", "microphone");
  defaultOption.value = "";
  microphoneDevice.innerHTML = "";
  microphoneDevice.append(defaultOption);

  audioInputs
    .filter((device) => device.deviceId && device.deviceId !== "default")
    .forEach((device, index) => {
      const label = device.label || `Microphone ${index + 1}`;
      microphoneDevice.append(new Option(label, device.deviceId));
    });

  if ([...microphoneDevice.options].some((option) => option.value === previousValue)) {
    microphoneDevice.value = previousValue;
  }
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

function configureCaptureAvailability() {
  if (!captureMode) return;
  const meetingOption = [...captureMode.options].find((option) => option.value === "meeting");
  const displayCaptureAvailable = Boolean(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
  if (meetingOption) meetingOption.disabled = !displayCaptureAvailable;
  if (!displayCaptureAvailable && captureMode.value === "meeting") {
    captureMode.value = "microphone";
  }
  const unavailableReason = mediaCaptureUnavailableReason();
  if (unavailableReason && !document.body.classList.contains("auth-pending")) {
    setStatus(unavailableReason);
  }
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

function updateSpeakerLabelPreference() {
  if (!speakerLabelsToggle.checked) speakerCount.value = "";
  updateWorkflowUI();
}

function syncLiveCaptionPreference() {
  liveCaptionsToggle.checked = localStorage.getItem("momLiveCaptions") !== "off";
}

function emptyTranscriptMessage() {
  if (!speakerLabelsToggle.checked) {
    return workflowMode.value === "recorded"
      ? "Upload a recording to create one plain transcript without speaker labels."
      : "Start recording, then stop to create one plain transcript without speaker labels.";
  }
  if (workflowMode.value === "recorded") return "Upload a recording to create a local diarized transcript.";
  return liveCaptionsToggle.checked
    ? "Start recording to see local caption previews, then stop for the final diarized transcript."
    : "Start recording, then stop to finalize with local transcription and diarization.";
}

function refreshEmptyTranscriptMessage() {
  const msg = document.querySelector("#emptyTranscriptMsg");
  if (msg) msg.textContent = emptyTranscriptMessage();
}

window.switchMobileTab = function(target) {
  const mv = document.getElementById("meetingView");
  if(mv) {
    mv.className = "meeting-view show-" + target;
  }
  document.querySelectorAll(".mobile-tab").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.target === target);
  });
};
