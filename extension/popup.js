const BACKEND = "http://127.0.0.1:8765";
const DEFAULT_FOLDER = "YT Audio Downloads";
const POLL_INTERVAL_MS = 1200;
const POLL_TIMEOUT_MS = 15 * 60 * 1000;

const backendStatus = document.getElementById("backend-status");
const app = document.getElementById("app");
const videoEl = document.getElementById("video");
const statusEl = document.getElementById("status");
const downloadBtn = document.getElementById("download");
const connectBtn = document.getElementById("connect");
const disconnectBtn = document.getElementById("disconnect");
const connectedRow = document.getElementById("drive-connected");
const uploadToggle = document.getElementById("upload-toggle");
const driveConfig = document.getElementById("drive-config");
const folderInput = document.getElementById("folder");
const driveLink = document.getElementById("drive-link");

let currentUrl = null;

/* ---------- SMALL HELPERS ---------- */

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.classList.remove("success", "error", "warn");
  if (kind) statusEl.classList.add(kind);
}

function showLink(url) {
  if (url) {
    driveLink.href = url;
    driveLink.classList.remove("hidden");
  } else {
    driveLink.classList.add("hidden");
    driveLink.removeAttribute("href");
  }
}

/* ---------- CHROME API PROMISE WRAPPERS ---------- */

/**
 * Chrome returns either a bare token string (older builds) or a
 * { token, grantedScopes } object (newer MV3 builds), so handle both.
 */
function getAuthToken(interactive) {
  return new Promise((resolve, reject) => {
    chrome.identity.getAuthToken({ interactive }, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      const token = typeof result === "string" ? result : result && result.token;
      if (!token) {
        reject(new Error("Google did not grant a token"));
        return;
      }
      resolve(token);
    });
  });
}

function removeCachedToken(token) {
  return new Promise((resolve) =>
    chrome.identity.removeCachedAuthToken({ token }, resolve)
  );
}

function loadSettings() {
  return new Promise((resolve) =>
    chrome.storage.local.get(
      { folderPath: DEFAULT_FOLDER, uploadEnabled: true },
      resolve
    )
  );
}

function saveSettings(patch) {
  return new Promise((resolve) => chrome.storage.local.set(patch, resolve));
}

/* ---------- DRIVE CONNECTION STATE ---------- */

function renderConnected(isConnected) {
  connectBtn.classList.toggle("hidden", isConnected);
  connectedRow.classList.toggle("hidden", !isConnected);
}

/** Probe for a cached token without prompting the user. */
async function refreshConnectionState() {
  try {
    await getAuthToken(false);
    renderConnected(true);
  } catch {
    renderConnected(false);
  }
}

connectBtn.onclick = async () => {
  connectBtn.disabled = true;
  setStatus("Opening Google sign-in...");
  try {
    await getAuthToken(true);
    renderConnected(true);
    setStatus("Google Drive connected", "success");
  } catch (e) {
    setStatus("Could not connect Drive: " + e.message, "error");
  } finally {
    connectBtn.disabled = false;
  }
};

disconnectBtn.onclick = async () => {
  try {
    const token = await getAuthToken(false);
    await removeCachedToken(token);
  } catch {
    // Nothing cached; already disconnected.
  }
  renderConnected(false);
  setStatus("Drive disconnected. The extension keeps no copy of the token.");
};

/* ---------- SETTINGS WIRING ---------- */

uploadToggle.onchange = async () => {
  driveConfig.classList.toggle("hidden", !uploadToggle.checked);
  await saveSettings({ uploadEnabled: uploadToggle.checked });
};

folderInput.onchange = async () => {
  const folderPath = folderInput.value.trim() || DEFAULT_FOLDER;
  folderInput.value = folderPath;
  await saveSettings({ folderPath });
};

/* ---------- BACKEND ---------- */

async function checkBackend() {
  try {
    const res = await fetch(`${BACKEND}/health`, { method: "GET" });
    if (!res.ok) throw new Error("Backend not responding");

    const health = await res.json();
    backendStatus.textContent = health.drive_available
      ? "Backend running!"
      : "Backend running (Drive libraries missing)";
    backendStatus.classList.remove("error");
    backendStatus.classList.add("ok");
    app.classList.remove("hidden");
  } catch {
    backendStatus.textContent =
      "Backend not running. Start it locally to use the extension.";
    backendStatus.classList.remove("ok");
    backendStatus.classList.add("error");
  }
}

const STAGE_LABELS = {
  queued: "Queued...",
  downloading: "Downloading and converting...",
  downloaded: "Saved locally, preparing upload...",
  uploading: "Uploading to Google Drive...",
};

async function pollJob(jobId) {
  const deadline = Date.now() + POLL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    await sleep(POLL_INTERVAL_MS);

    const res = await fetch(`${BACKEND}/jobs/${jobId}`);
    if (!res.ok) throw new Error(`Lost track of the job (HTTP ${res.status})`);

    const job = await res.json();
    if (job.stage === "done" || job.stage === "error") return job;
    setStatus(STAGE_LABELS[job.stage] || "Working...");
  }

  throw new Error("Timed out waiting for the download to finish");
}

async function startJob(token) {
  const res = await fetch(`${BACKEND}/download`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Drive-Token": token } : {}),
    },
    body: JSON.stringify({
      url: currentUrl,
      folder_path: folderInput.value.trim() || DEFAULT_FOLDER,
      upload: uploadToggle.checked,
    }),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Backend rejected the request");
  return pollJob(data.job_id);
}

/** Upload-only retry, so an expired token costs no re-download. */
async function retryUpload(jobId, token) {
  const res = await fetch(`${BACKEND}/jobs/${jobId}/upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Drive-Token": token },
    body: JSON.stringify({
      folder_path: folderInput.value.trim() || DEFAULT_FOLDER,
    }),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Retry was rejected");
  return pollJob(jobId);
}

function renderResult(job) {
  if (job.stage === "error") {
    setStatus("Error: " + job.error, "error");
    return;
  }

  const upload = job.upload || {};
  if (upload.status === "done") {
    setStatus(`Saved locally and uploaded to ${upload.folder_path}`, "success");
    showLink(upload.link);
  } else if (upload.status === "error") {
    // The local file is the durable artifact, so this is a partial success.
    setStatus(`Saved locally. Drive upload failed: ${upload.message}`, "warn");
  } else {
    setStatus("Saved locally", "success");
  }
}

/* ---------- DOWNLOAD ---------- */

downloadBtn.onclick = async () => {
  if (!currentUrl) {
    setStatus("No YouTube video detected", "error");
    return;
  }

  downloadBtn.disabled = true;
  showLink(null);
  setStatus("Starting...");

  try {
    let token = null;
    if (uploadToggle.checked) {
      try {
        token = await getAuthToken(true);
        renderConnected(true);
      } catch (e) {
        setStatus(
          "Drive not connected: " + e.message + ". Downloading locally only.",
          "warn"
        );
      }
    }

    let job = await startJob(token);

    if (token && job.upload && job.upload.token_expired) {
      setStatus("Drive token expired, reconnecting...");
      await removeCachedToken(token);
      const freshToken = await getAuthToken(true);
      job = await retryUpload(job.id, freshToken);
    }

    renderResult(job);
  } catch (e) {
    setStatus("Error: " + e.message, "error");
  } finally {
    downloadBtn.disabled = false;
  }
};

/* ---------- INIT ---------- */

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const url = tabs[0]?.url || "";
  if (url.includes("youtube.com")) {
    currentUrl = url;
    videoEl.textContent = "YouTube video detected";
    videoEl.classList.add("detected");
  } else {
    videoEl.textContent = "Not on a YouTube video";
    videoEl.classList.remove("detected");
  }
});

(async function init() {
  const settings = await loadSettings();
  folderInput.value = settings.folderPath;
  uploadToggle.checked = settings.uploadEnabled;
  driveConfig.classList.toggle("hidden", !settings.uploadEnabled);

  await Promise.all([checkBackend(), refreshConnectionState()]);
})();
