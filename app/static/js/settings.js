// ═══════════════════════════════════════════════
//  SETTINGS JS
// ═══════════════════════════════════════════════

function openSettings() {
  document.getElementById("settingsModal").hidden = false;
  loadAppSettings();
  fetchOllamaModels();
}

function closeSettings() {
  document.getElementById("settingsModal").hidden = true;
  // Clear password fields
  document.getElementById("settCurrentPwd").value = "";
  document.getElementById("settNewPwd").value = "";
  document.getElementById("settConfirmPwd").value = "";
  var msg = document.getElementById("passwordMsg");
  msg.hidden = true;
  msg.className = "setting-msg";
}

function switchSettingsTab(tab) {
  // Update tab buttons
  document.querySelectorAll(".settings-tab").forEach(function(btn) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  // Show/hide sections
  document.querySelectorAll(".settings-section").forEach(function(section) {
    section.hidden = section.dataset.section !== tab;
  });
}

async function loadAppSettings() {
  try {
    var resp = await apiFetch("/api/settings");
    if (!resp.ok) return;
    var s = await resp.json();

    document.getElementById("settOllamaUrl").value = s.ollama_base_url || "";
    document.getElementById("settMaxTokens").value = s.mom_max_tokens || "";
    document.getElementById("settNumCtx").value = s.ollama_num_ctx || "";
    document.getElementById("settNumGpu").value = s.ollama_num_gpu || "";

    // Whisper / transcription
    _setSelect("settWhisperModel", s.whisper_model);
    _setSelect("settWhisperDevice", s.whisper_device);
    _setSelect("settLiveWhisperModel", s.live_whisper_model);
    _setSelect("settDiarization", s.diarization_provider);
    _setSelect("settVoiceprinting", s.voiceprinting_enabled);

    // Account
    var chip = document.getElementById("userChip");
    document.getElementById("settUsername").value = chip ? chip.textContent.trim() : "admin";

    // Store current model to pre-select after model list loads
    window._currentOllamaModel = s.ollama_model || "";
  } catch (e) {
    console.error("Failed to load settings", e);
  }
}

async function fetchOllamaModels() {
  var select = document.getElementById("settOllamaModel");
  select.innerHTML = "<option value=''>Loading…</option>";
  try {
    var resp = await apiFetch("/api/settings/ollama-models");
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return {}; });
      select.innerHTML = "<option value=''>" + (err.detail || "Could not reach Ollama") + "</option>";
      return;
    }
    var data = await resp.json();
    var models = data.models || [];
    if (models.length === 0) {
      select.innerHTML = "<option value=''>No models found</option>";
      return;
    }
    select.innerHTML = "";
    models.forEach(function(m) {
      var opt = document.createElement("option");
      opt.value = m.name;
      var sizeGB = m.size ? (m.size / 1e9).toFixed(1) + " GB" : "";
      opt.textContent = m.name + (sizeGB ? "  (" + sizeGB + ")" : "");
      select.appendChild(opt);
    });
    // Pre-select current model
    if (window._currentOllamaModel) {
      select.value = window._currentOllamaModel;
      // If exact match didn't work, try partial
      if (!select.value) {
        for (var i = 0; i < select.options.length; i++) {
          if (select.options[i].value.indexOf(window._currentOllamaModel) !== -1) {
            select.selectedIndex = i;
            break;
          }
        }
      }
    }
  } catch (e) {
    select.innerHTML = "<option value=''>Error: " + e.message + "</option>";
  }
}

async function saveAppSettings() {
  var btn = document.getElementById("saveSettingsBtn");
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    var body = {
      ollama_base_url: document.getElementById("settOllamaUrl").value.trim(),
      ollama_model: document.getElementById("settOllamaModel").value,
      mom_max_tokens: document.getElementById("settMaxTokens").value.trim(),
      ollama_num_ctx: document.getElementById("settNumCtx").value.trim(),
      ollama_num_gpu: document.getElementById("settNumGpu").value.trim(),
      whisper_model: document.getElementById("settWhisperModel").value,
      whisper_device: document.getElementById("settWhisperDevice").value,
      live_whisper_model: document.getElementById("settLiveWhisperModel").value,
      diarization_provider: document.getElementById("settDiarization").value,
      voiceprinting_enabled: document.getElementById("settVoiceprinting").value,
    };
    // Remove empty strings so we don't overwrite with blanks
    Object.keys(body).forEach(function(k) { if (!body[k]) delete body[k]; });

    var resp = await apiFetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error("Save failed");
    closeSettings();
  } catch (e) {
    console.error("Failed to save settings", e);
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
}

async function changeUserPassword() {
  var msg = document.getElementById("passwordMsg");
  var currentPwd = document.getElementById("settCurrentPwd").value;
  var newPwd = document.getElementById("settNewPwd").value;
  var confirmPwd = document.getElementById("settConfirmPwd").value;

  msg.hidden = true;

  if (!currentPwd || !newPwd) {
    _showPwdMsg("Please fill in all password fields.", "error");
    return;
  }
  if (newPwd !== confirmPwd) {
    _showPwdMsg("New passwords do not match.", "error");
    return;
  }
  if (newPwd.length < 4) {
    _showPwdMsg("Password must be at least 4 characters.", "error");
    return;
  }

  try {
    var resp = await apiFetch("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: currentPwd, new_password: newPwd }),
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return { detail: "Failed" }; });
      _showPwdMsg(err.detail || "Password change failed.", "error");
      return;
    }
    _showPwdMsg("Password updated successfully!", "success");
    document.getElementById("settCurrentPwd").value = "";
    document.getElementById("settNewPwd").value = "";
    document.getElementById("settConfirmPwd").value = "";
  } catch (e) {
    _showPwdMsg("Network error: " + e.message, "error");
  }
}

function _showPwdMsg(text, type) {
  var msg = document.getElementById("passwordMsg");
  msg.textContent = text;
  msg.className = "setting-msg " + type;
  msg.hidden = false;
}

function _setSelect(id, value) {
  var el = document.getElementById(id);
  if (!el) return;
  el.value = value;
  // If no option matched, select the first one
  if (el.selectedIndex === -1 && el.options.length > 0) {
    el.selectedIndex = 0;
  }
}
