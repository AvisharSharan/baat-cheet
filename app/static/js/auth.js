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

