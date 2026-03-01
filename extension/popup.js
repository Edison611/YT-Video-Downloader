const backendStatus = document.getElementById("backend-status");
const app = document.getElementById("app");
const outputInput = document.getElementById("output");
const statusEl = document.getElementById("status");
const videoEl = document.getElementById("video");

let currentUrl = null;

/* ---------- HEALTH CHECK ---------- */
async function checkBackend() {
  try {
    const res = await fetch("http://127.0.0.1:8765/health", {
      method: "GET"
    });

    if (!res.ok) throw new Error("Backend not responding");

    backendStatus.textContent = "Backend running!";
    app.style.display = "block";
  } catch (e) {
    backendStatus.textContent =
      "Backend not running. Start it locally to use the extension.";
  }
}

/* ---------- DETECT YOUTUBE TAB ---------- */
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const url = tabs[0]?.url || "";
  if (url.includes("youtube.com")) {
    currentUrl = url;
    videoEl.textContent = "YouTube video detected";
  } else {
    videoEl.textContent = "Not on a YouTube video";
  }
});

/* ---------- DOWNLOAD ---------- */
document.getElementById("download").onclick = async () => {
  if (!currentUrl) {
    statusEl.textContent = "No YouTube video detected";
    return;
  }

  statusEl.textContent = "Downloading...";

  try {
    const r = await fetch("http://127.0.0.1:8765/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: currentUrl }),
    });

    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Unknown error");

    statusEl.textContent = "Download complete";
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
  }
};

/* ---------- INIT ---------- */
checkBackend();
