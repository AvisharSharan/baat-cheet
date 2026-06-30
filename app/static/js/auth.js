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

var _isRefreshing = false;
var _refreshPromise = null;

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  let response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    if (!loginView.hidden || url.includes("/api/auth/refresh") || url.includes("/api/auth/login")) {
      return response;
    }

    if (!_isRefreshing) {
      _isRefreshing = true;
      _refreshPromise = fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Authorization": `Bearer ${authToken}` }
      }).then(async (res) => {
        if (!res.ok) throw new Error("Refresh failed");
        const data = await res.json();
        authToken = data.access_token;
        localStorage.setItem(authTokenKey, authToken);
      }).catch((err) => {
        authToken = "";
        localStorage.removeItem(authTokenKey);
        showLogin();
        throw err;
      }).finally(() => {
        _isRefreshing = false;
      });
    }

    try {
      await _refreshPromise;
      const retryHeaders = new Headers(options.headers || {});
      retryHeaders.set("Authorization", `Bearer ${authToken}`);
      response = await fetch(url, { ...options, headers: retryHeaders });
    } catch (error) {
      return response;
    }
  }
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
