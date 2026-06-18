// Init
if (window.innerWidth <= 768) {
  workspace.classList.add("collapsed");
}
modeBtns.forEach(btn => btn.addEventListener("click", () => setWorkflowMode(btn.dataset.mode)));
recordedFile.addEventListener("change", onFileChange);
liveCaptionsToggle.addEventListener("change", updateLiveCaptionPreference);
speakerLabelsToggle.addEventListener("change", updateSpeakerLabelPreference);
startBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopRecording);
uploadRecordedBtn.addEventListener("click", uploadRecordedFile);
momBtn.addEventListener("click", generateMom);
cancelActionBtn.addEventListener("click", cancelActiveAction);
saveSpeakersBtn.addEventListener("click", saveSpeakers);
themeToggle.addEventListener("click", toggleTheme);
newMeetingBtn.addEventListener("click", startNewMeeting);
historyTabBtn.addEventListener("click", showHistory);
refreshHistoryBtn.addEventListener("click", loadHistory);
loginForm.addEventListener("submit", login);
logoutBtn.addEventListener("click", logout);
sidebarToggleBtn.addEventListener("click", () => workspace.classList.toggle("collapsed"));

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

