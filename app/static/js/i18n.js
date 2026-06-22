// ═══════════════════════════════════════════════
//  i18n (Localization) Engine
// ═══════════════════════════════════════════════

const i18nDict = {
  en: {
    // Topbar
    "topbar.new": "New Meeting",
    "topbar.history": "History",
    // Login
    "login.title": "Welcome back",
    "login.subtitle": "Sign in to your workspace",
    "login.username": "Username",
    "login.password": "Password",
    "login.btn": "Sign in",
    "login.tagline": "Your meetings, intelligently documented.",
    "login.feat1": "Live Transcription",
    "login.feat1_sub": "Record & transcribe meetings in real-time",
    "login.feat2": "Speaker Diarization",
    "login.feat2_sub": "AI identifies who said what",
    "login.feat3": "Auto Minutes",
    "login.feat3_sub": "Structured MoM drafted by AI",
    "login.footer": "Local-first · Privacy-focused",
    // Sidebar Setup
    "setup.title": "Setup",
    "setup.name": "Meeting name",
    "setup.name_ph": "e.g. Weekly sync",
    "setup.mode": "Mode",
    "setup.live": "Live",
    "setup.recorded": "Recorded",
    "setup.audio_src": "Audio source",
    "setup.src_meeting": "Meeting tab + microphone",
    "setup.src_mic": "Microphone only",
    "setup.live_cap": "Live captions",
    "setup.local_prev": "Local preview",
    "setup.file_label": "Audio or video file",
    "setup.file_drop": "Drop file or click to browse",
    "setup.speakers": "Expected speakers",
    "setup.optional": "optional",
    "setup.auto_detect": "Auto-detect",
    "setup.speaker_labels": "Speaker labels",
    "setup.diarization": "Diarization",
    // Sidebar Capture
    "cap.title": "Capture",
    "cap.start": "Start Recording",
    "cap.stop": "Stop & Finalize",
    "cap.upload": "Upload & Transcribe",
    "cap.download": "Download audio",
    // Sidebar Label & Finalize
    "fin.title": "Label & Finalize",
    "fin.speakers": "Speakers",
    "fin.turns": "Turns",
    "fin.words": "Words",
    "fin.type": "Meeting type",
    "fin.type_auto": "Auto-detect",
    "fin.type_gov": "Government / official review",
    "fin.type_rev": "Review / status",
    "fin.type_plan": "Planning / decision",
    "fin.type_action": "Action tracker",
    "fin.type_gen": "General meeting",
    "fin.draft": "Draft Minutes",
    "fin.cancel": "Cancel current action",
    "fin.remember": "Remember voices",
    "fin.save": "Save labels",
    "fin.hint": "Record or upload meeting audio, then finalize locally with faster-whisper transcription and pyannote diarization.",
    // History
    "hist.title": "Meeting History",
    "hist.refresh": "Refresh",
    "hist.empty_title": "No meetings yet",
    "hist.empty_sub": "Completed meetings will appear here with their transcript and minutes.",
    // Meeting View
    "meet.tab_trans": "Transcript",
    "meet.tab_mom": "Draft Minutes",
    "meet.trans_title": "Transcript",
    "meet.empty_trans": "No transcript yet",
    "meet.empty_trans_sub": "Start recording, then stop to finalize with local transcription and diarization.",
    "meet.mom_title": "Draft Minutes",
    "meet.empty_mom": "Transcribe the meeting first, then click Draft Minutes to generate AI-powered minutes.",
    // Settings
    "set.title": "Settings",
    "set.tab_ai": "AI Model",
    "set.tab_trans": "Transcription",
    "set.tab_acc": "Account",
    "set.ollama_url": "Ollama Base URL",
    "set.ollama_url_hint": "The URL of your local Ollama instance",
    "set.model": "Model",
    "set.model_hint": "Select from models installed in your Ollama instance",
    "set.max_tokens": "Max Tokens",
    "set.max_tokens_hint": "Maximum tokens for generated minutes (256–8192)",
    "set.ctx": "Context Window",
    "set.ctx_hint": "Ollama context window size",
    "set.gpu": "GPU Layers",
    "set.gpu_hint": "Number of GPU layers to offload (0 = CPU only)",
    "set.trans_provider": "Transcription Engine",
    "set.trans_provider_hint": "Use Indic Conformer for Indian-language recordings",
    "set.w_model": "Whisper Model",
    "set.w_model_hint": "Larger models are more accurate but slower",
    "set.w_dev": "Whisper Device",
    "set.w_dev_hint": "Use CUDA for faster transcription if available",
    "set.w_live": "Live Preview Model",
    "set.w_live_hint": "Model used for live caption preview during recording",
    "set.indic_model": "Indic Conformer Model",
    "set.indic_model_hint": "Requires accepting the gated Hugging Face model terms and setting HF_TOKEN",
    "set.indic_lang": "Indic Language",
    "set.indic_lang_hint": "Language code passed to the Indic Conformer model",
    "set.indic_decoder": "Indic Decoder",
    "set.indic_decoder_hint": "CTC is the simpler default; RNNT is also supported by the model",
    "set.indic_device": "Indic Device",
    "set.indic_device_hint": "600M parameters; GPU is recommended",
    "set.diar": "Speaker Diarization",
    "set.diar_hint": "Identifies who said what in multi-speaker meetings",
    "set.vp": "Voice Profiles",
    "set.vp_hint": "Remember speaker voices across meetings",
    "set.user": "Username",
    "set.user_hint": "Username cannot be changed at runtime",
    "set.pwd_title": "Change Password",
    "set.pwd_cur": "Current Password",
    "set.pwd_new": "New Password",
    "set.pwd_conf": "Confirm New Password",
    "set.pwd_btn": "Update Password",
    "set.cancel": "Cancel",
    "set.save": "Save Changes",
    // Topbar actions
    "top.status": "Ready",
    "top.logout": "Logout",
  },
  hi: {
    // Topbar
    "topbar.new": "नई बैठक",
    "topbar.history": "इतिहास",
    // Login
    "login.title": "नमस्ते, फिर से स्वागत है",
    "login.subtitle": "अपने वर्कस्पेस में साइन इन करें",
    "login.username": "उपयोगकर्ता नाम",
    "login.password": "पासवर्ड",
    "login.btn": "साइन इन करें",
    "login.tagline": "आपकी बैठकें, बुद्धिमानी से प्रलेखित।",
    "login.feat1": "लाइव ट्रांसक्रिप्शन",
    "login.feat1_sub": "रीयल-टाइम में बैठकों को रिकॉर्ड और ट्रांसक्राइब करें",
    "login.feat2": "स्पीकर डायराइजेशन",
    "login.feat2_sub": "AI पहचानता है कि किसने क्या कहा",
    "login.feat3": "ऑटो मिनट्स",
    "login.feat3_sub": "AI द्वारा तैयार किए गए संरचित MoM",
    "login.footer": "लोकल-फर्स्ट · गोपनीयता-केंद्रित",
    // Sidebar Setup
    "setup.title": "सेटप",
    "setup.name": "बैठक का नाम",
    "setup.name_ph": "उदाहरण: साप्ताहिक समीक्षा",
    "setup.mode": "मोड",
    "setup.live": "लाइव",
    "setup.recorded": "रिकॉर्डेड",
    "setup.audio_src": "ऑडियो स्रोत",
    "setup.src_meeting": "मीटिंग टैब + माइक्रोफोन",
    "setup.src_mic": "केवल माइक्रोफोन",
    "setup.live_cap": "लाइव कैप्शन",
    "setup.local_prev": "लोकल प्रीव्यू",
    "setup.file_label": "ऑडियो या वीडियो फ़ाइल",
    "setup.file_drop": "फ़ाइल छोड़ें या ब्राउज़ करने के लिए क्लिक करें",
    "setup.speakers": "स्पीकर की संख्या",
    "setup.optional": "वैकल्पिक",
    "setup.auto_detect": "स्वतः पता लगाएं",
    "setup.speaker_labels": "स्पीकर लेबल",
    "setup.diarization": "डायराइजेशन",
    // Sidebar Capture
    "cap.title": "कैप्चर",
    "cap.start": "रिकॉर्डिंग शुरू करें",
    "cap.stop": "रोकें और अंतिम रूप दें",
    "cap.upload": "अपलोड और ट्रांसक्राइब करें",
    "cap.download": "ऑडियो डाउनलोड करें",
    // Sidebar Label & Finalize
    "fin.title": "लेबल करें और सेव करें",
    "fin.speakers": "वक्ता",
    "fin.turns": "टर्न",
    "fin.words": "शब्द",
    "fin.type": "बैठक का प्रकार",
    "fin.type_auto": "स्वतः पता लगाएं",
    "fin.type_gov": "सरकारी / आधिकारिक समीक्षा",
    "fin.type_rev": "समीक्षा / स्थिति",
    "fin.type_plan": "योजना / निर्णय",
    "fin.type_action": "एक्शन ट्रैकर",
    "fin.type_gen": "सामान्य बैठक",
    "fin.draft": "मिनट्स तैयार करें",
    "fin.cancel": "कार्रवाई रद्द करें",
    "fin.remember": "आवाज़ें याद रखें",
    "fin.save": "सेव करें",
    "fin.hint": "ऑडियो रिकॉर्ड या अपलोड करें, और फिर स्थानीय रूप से ट्रांसक्राइब करें।",
    // History
    "hist.title": "मीटिंग का इतिहास",
    "hist.refresh": "रिफ्रेश करें",
    "hist.empty_title": "कोई मीटिंग नहीं",
    "hist.empty_sub": "आपकी पूरी की गई मीटिंग्स यहाँ दिखाई देंगी।",
    // Meeting View
    "meet.tab_trans": "ट्रांसक्रिप्ट",
    "meet.tab_mom": "मिनट्स ड्राफ्ट",
    "meet.trans_title": "ट्रांसक्रिप्ट",
    "meet.empty_trans": "कोई ट्रांसक्रिप्ट उपलब्ध नहीं",
    "meet.empty_trans_sub": "रिकॉर्डिंग शुरू करें, फिर स्थानीय ट्रांसक्रिप्शन और डायराइजेशन के साथ अंतिम रूप देने के लिए रोकें।",
    "meet.mom_title": "ड्राफ्ट मिनट्स",
    "meet.empty_mom": "पहले बैठक का ट्रांसक्राइब करें, फिर AI-संचालित मिनट्स उत्पन्न करने के लिए ड्राफ्ट मिनट्स पर क्लिक करें।",
    // Settings
    "set.title": "सेटिंग्स",
    "set.tab_ai": "AI मॉडल",
    "set.tab_trans": "ट्रांसक्रिप्शन",
    "set.tab_acc": "खाता",
    "set.ollama_url": "ओलामा बेस URL",
    "set.ollama_url_hint": "आपके स्थानीय ओलामा इंस्टेंस का URL",
    "set.model": "मॉडल",
    "set.model_hint": "अपने ओलामा इंस्टेंस में स्थापित मॉडलों में से चुनें",
    "set.max_tokens": "अधिकतम टोकन",
    "set.max_tokens_hint": "उत्पन्न मिनट्स के लिए अधिकतम टोकन (256–8192)",
    "set.ctx": "कॉन्टेक्स्ट विंडो",
    "set.ctx_hint": "ओलामा कॉन्टेक्स्ट विंडो का आकार",
    "set.gpu": "GPU लेयर्स",
    "set.gpu_hint": "ऑफ़लोड करने के लिए GPU लेयर्स की संख्या (0 = केवल CPU)",
    "set.trans_provider": "Transcription Engine",
    "set.trans_provider_hint": "Use Indic Conformer for Indian-language recordings",
    "set.w_model": "व्हिस्पर मॉडल",
    "set.w_model_hint": "बड़े मॉडल अधिक सटीक होते हैं लेकिन धीमे होते हैं",
    "set.w_dev": "व्हिस्पर डिवाइस",
    "set.w_dev_hint": "यदि उपलब्ध हो तो तेज़ ट्रांसक्रिप्शन के लिए CUDA का उपयोग करें",
    "set.w_live": "लाइव प्रीव्यू मॉडल",
    "set.w_live_hint": "रिकॉर्डिंग के दौरान लाइव कैप्शन प्रीव्यू के लिए उपयोग किया जाने वाला मॉडल",
    "set.indic_model": "Indic Conformer Model",
    "set.indic_model_hint": "Requires accepting the gated Hugging Face model terms and setting HF_TOKEN",
    "set.indic_lang": "Indic Language",
    "set.indic_lang_hint": "Language code passed to the Indic Conformer model",
    "set.indic_decoder": "Indic Decoder",
    "set.indic_decoder_hint": "CTC is the simpler default; RNNT is also supported by the model",
    "set.indic_device": "Indic Device",
    "set.indic_device_hint": "600M parameters; GPU is recommended",
    "set.diar": "स्पीकर डायराइजेशन",
    "set.diar_hint": "पहचानता है कि मल्टी-स्पीकर मीटिंग्स में किसने क्या कहा",
    "set.vp": "वॉयस प्रोफाइल",
    "set.vp_hint": "मीटिंग्स के दौरान स्पीकर की आवाज़ें याद रखें",
    "set.user": "उपयोगकर्ता नाम",
    "set.user_hint": "रनटाइम पर उपयोगकर्ता नाम नहीं बदला जा सकता",
    "set.pwd_title": "पासवर्ड बदलें",
    "set.pwd_cur": "वर्तमान पासवर्ड",
    "set.pwd_new": "नया पासवर्ड",
    "set.pwd_conf": "नया पासवर्ड पुष्टि करें",
    "set.pwd_btn": "पासवर्ड अपडेट करें",
    "set.cancel": "रद्द करें",
    "set.save": "बदलाव सहेजें",
    // Topbar actions
    "top.status": "तैयार",
    "top.logout": "लॉग आउट",
  }
};

let currentLang = localStorage.getItem("momLang") || "en";

function setLanguage(lang) {
  if (!i18nDict[lang]) lang = "en";
  currentLang = lang;
  localStorage.setItem("momLang", lang);
  document.documentElement.lang = lang;
  
  // Update all elements with data-i18n
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.dataset.i18n;
    const translation = i18nDict[lang][key];
    if (translation) {
      if (el.tagName === "INPUT" && el.placeholder) {
        el.placeholder = translation;
      } else {
        // Keep icons intact if it's a button with inner HTML
        // For buttons that might have SVG + text, we need to be careful.
        // Easiest is to wrap the text in a span.
        if (el.tagName === "SPAN" || el.tagName === "DIV" || el.tagName === "H1" || el.tagName === "H2" || el.tagName === "H3" || el.tagName === "P" || el.tagName === "LABEL" || el.tagName === "STRONG" || el.tagName === "BUTTON" || el.tagName === "PRE") {
          // If the element has children (like svgs), only replace the text nodes.
          let hasElementChildren = Array.from(el.childNodes).some(n => n.nodeType === 1);
          if (hasElementChildren) {
            // Find the first text node and replace its content, or try to be smarter.
            // Better practice: wrap text in a `<span data-i18n="...">` when inside a button with an icon.
            el.textContent = translation;
          } else {
            el.textContent = translation;
          }
        }
      }
    }
  });

  // Re-run status update to translate "Ready" etc.
  if (typeof setStatus === "function") {
    // If we're on the login screen vs app screen
    var statText = document.getElementById("statusText");
    if (statText) {
      if (document.body.classList.contains("auth-pending")) {
        statText.textContent = t("login.subtitle") || "Sign in required";
      } else if (!statText.textContent.includes(":") && !statText.textContent.includes("%")) {
        // Simple "Ready"
        statText.textContent = t("top.status");
      }
    }
  }

  // Dispatch event so other components can react if needed
  window.dispatchEvent(new Event('languageChanged'));
}

function toggleLanguage() {
  setLanguage(currentLang === "en" ? "hi" : "en");
}

function t(key) {
  return i18nDict[currentLang][key] || i18nDict["en"][key] || key;
}

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  setLanguage(currentLang);
});
