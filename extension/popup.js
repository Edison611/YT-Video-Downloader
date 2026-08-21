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
    backendStatus.classList.remove("error");
    backendStatus.classList.add("ok");
    app.style.display = "block";
  } catch (e) {
    backendStatus.textContent =
      "Backend not running. Start it locally to use the extension.";
    backendStatus.classList.remove("ok");
    backendStatus.classList.add("error");
  }
}

/* ---------- DETECT YOUTUBE TAB ---------- */
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

/* ---------- DOWNLOAD ---------- */
const downloadBtn = document.getElementById("download");

downloadBtn.onclick = async () => {
  if (!currentUrl) {
    statusEl.textContent = "No YouTube video detected";
    statusEl.classList.remove("success");
    statusEl.classList.add("error");
    return;
  }

  downloadBtn.disabled = true;
  statusEl.classList.remove("success", "error");
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
    statusEl.classList.add("success");
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    statusEl.classList.add("error");
  } finally {
    downloadBtn.disabled = false;
  }
};

/* ---------- INIT ---------- */
checkBackend();
