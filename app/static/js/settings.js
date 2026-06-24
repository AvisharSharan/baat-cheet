// ═══════════════════════════════════════════════
//  SETTINGS JS
// ═══════════════════════════════════════════════

function openSettings() {
  document.getElementById("settingsModal").hidden = false;
  loadAppSettings();
}

document.addEventListener("DOMContentLoaded", function() {
  var momProvider = document.getElementById("settMomProvider");
  var engine = document.getElementById("settSpeechEngine");
  var provider = document.getElementById("settTranscriptionProvider");
  if (momProvider) momProvider.addEventListener("change", updateMomProviderVisibility);
  if (engine) engine.addEventListener("change", updateSpeechSettingsVisibility);
  if (provider) provider.addEventListener("change", updateSpeechSettingsVisibility);
});

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

    _setSelect("settMomProvider", s.mom_provider || "ollama");
    document.getElementById("settOllamaUrl").value = s.ollama_base_url || "";
    document.getElementById("settHostedApiModel").value = s.hosted_api_model || "deepseek-ai/DeepSeek-V4-Flash";
    document.getElementById("settMaxTokens").value = s.mom_max_tokens || "";
    document.getElementById("settNumCtx").value = s.ollama_num_ctx || "";
    document.getElementById("settNumGpu").value = s.ollama_num_gpu || "";

    // Speech-to-text / transcription
    var provider = s.transcription_provider || "local";
    _setSelect("settSpeechEngine", provider === "sarvam" ? "sarvam" : "open-source");
    _setSelect("settTranscriptionProvider", provider === "indic-conformer" ? "indic-conformer" : "local");
    _setSelect("settWhisperModel", s.whisper_model);
    _setSelect("settWhisperDevice", s.whisper_device);
    _setSelect("settLiveWhisperModel", s.live_whisper_model);
    document.getElementById("settIndicConformerModel").value = s.indic_conformer_model || "";
    _setSelect("settIndicConformerLanguage", s.indic_conformer_language);
    _setSelect("settIndicConformerDecoder", s.indic_conformer_decoder);
    _setSelect("settIndicConformerDevice", s.indic_conformer_device);
    document.getElementById("settSarvamModel").value = s.sarvam_stt_model || "";
    _setSelect("settSarvamMode", s.sarvam_stt_mode);
    document.getElementById("settSarvamLanguage").value = s.sarvam_language_code || "";
    _setSelect("settDiarization", s.diarization_provider);
    _setSelect("settVoiceprinting", s.voiceprinting_enabled);
    window.currentSpeechEngineValue = provider === "sarvam" ? "sarvam" : "open-source";
    updateSpeechSettingsVisibility();
    // Account
    var chip = document.getElementById("userChip");
    document.getElementById("settUsername").value = chip ? chip.textContent.trim() : "admin";

    // Store current model to pre-select after model list loads
    window._currentOllamaModel = s.ollama_model || "";
    updateMomProviderVisibility();
  } catch (e) {
    console.error("Failed to load settings", e);
  }
}

async function fetchOllamaModels() {
  if (document.getElementById("settMomProvider").value !== "ollama") return;
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
      mom_provider: document.getElementById("settMomProvider").value,
      ollama_base_url: document.getElementById("settOllamaUrl").value.trim(),
      ollama_model: document.getElementById("settOllamaModel").value,
      hosted_api_model: document.getElementById("settHostedApiModel").value.trim(),
      mom_max_tokens: document.getElementById("settMaxTokens").value.trim(),
      ollama_num_ctx: document.getElementById("settNumCtx").value.trim(),
      ollama_num_gpu: document.getElementById("settNumGpu").value.trim(),
      transcription_provider: selectedTranscriptionProvider(),
      whisper_model: document.getElementById("settWhisperModel").value,
      whisper_device: document.getElementById("settWhisperDevice").value,
      live_whisper_model: document.getElementById("settLiveWhisperModel").value,
      indic_conformer_model: document.getElementById("settIndicConformerModel").value.trim(),
      indic_conformer_language: document.getElementById("settIndicConformerLanguage").value,
      indic_conformer_decoder: document.getElementById("settIndicConformerDecoder").value,
      indic_conformer_device: document.getElementById("settIndicConformerDevice").value,
      sarvam_stt_model: document.getElementById("settSarvamModel").value.trim(),
      sarvam_stt_mode: document.getElementById("settSarvamMode").value,
      sarvam_language_code: document.getElementById("settSarvamLanguage").value.trim(),
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
    window.currentSpeechEngineValue = document.getElementById("settSpeechEngine").value;
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

function selectedTranscriptionProvider() {
  var engine = document.getElementById("settSpeechEngine").value;
  if (engine === "sarvam") return "sarvam";
  return document.getElementById("settTranscriptionProvider").value || "local";
}

function updateMomProviderVisibility() {
  var providerEl = document.getElementById("settMomProvider");
  var provider = providerEl ? providerEl.value : "ollama";
  document.querySelectorAll("[data-mom-provider-setting]").forEach(function(group) {
    group.hidden = group.dataset.momProviderSetting !== provider;
  });
  if (provider === "ollama") fetchOllamaModels();
}

function updateSpeechSettingsVisibility() {
  var engineEl = document.getElementById("settSpeechEngine");
  var providerEl = document.getElementById("settTranscriptionProvider");
  var engine = engineEl ? engineEl.value : "open-source";
  var provider = providerEl ? providerEl.value : "local";

  document.querySelectorAll("[data-engine-setting]").forEach(function(group) {
    group.hidden = group.dataset.engineSetting !== engine;
  });
  document.querySelectorAll("[data-open-source-setting]").forEach(function(group) {
    group.hidden = engine !== "open-source" || group.dataset.openSourceSetting !== provider;
  });
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
