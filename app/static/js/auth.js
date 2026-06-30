// AUTH
async function bootstrapAuth() {
  if (!authToken) {
    showLogin();
    return;
  }
  try {
    const response = await fetch("/api/auth/me", {
      headers: { "Authorization": `Bearer ${authToken}` },
    });
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
  const alreadyShowing = !loginView.hidden;
  document.body.classList.add("auth-pending");
  loginView.hidden = false;
  userChip.hidden = true;
  logoutBtn.hidden = true;
  setStatus("Sign in required");
  // Only steal focus when the login view was not already visible AND the
  // username field is empty — avoids jumping away from the password field
  // when showLogin() is called re-entrantly (e.g. a background 401).
  if (!alreadyShowing || !loginUsername.value.trim()) {
    window.setTimeout(() => { if (!loginUsername.value.trim()) loginUsername.focus(); }, 0);
  }
}

function showApp(username) {
  currentUsername = username || currentUsername;
  document.body.classList.remove("auth-pending");
  loginView.hidden = true;
  userChip.textContent = currentUsername;
  userChip.hidden = false;
  logoutBtn.hidden = false;
  setStatus("Ready");
  if (typeof configureCaptureAvailability === "function") configureCaptureAvailability();
  loadHistory();
}

// Count consecutive 401s from background calls before deciding to log out.
// A single transient 401 (server busy, momentary restart) must not boot the user.
var _consecutiveAuthFailures = 0;
var _AUTH_FAILURE_THRESHOLD = 3;

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    // Already on the login screen — don't disrupt typing.
    if (!loginView.hidden) return response;

    _consecutiveAuthFailures += 1;
    if (_consecutiveAuthFailures >= _AUTH_FAILURE_THRESHOLD) {
      // Multiple consecutive 401s — confirm the session is truly gone.
      const stillAuthenticated = await verifyCurrentSession();
      if (!stillAuthenticated) {
        _consecutiveAuthFailures = 0;
        authToken = "";
        localStorage.removeItem(authTokenKey);
        showLogin();
      } else {
        // verifyCurrentSession says we're fine — transient issue, reset counter.
        _consecutiveAuthFailures = 0;
      }
    }
    // Return the raw 401 response so callers can handle it (e.g. skip rendering).
    return response;
  }
  // Successful response — reset the failure counter.
  _consecutiveAuthFailures = 0;
  return response;
}

async function verifyCurrentSession() {
  if (!authToken) return false;
  try {
    const response = await fetch("/api/auth/me", {
      headers: { "Authorization": `Bearer ${authToken}` },
    });
    return response.ok;
  } catch (error) {
    return true;
  }
}
