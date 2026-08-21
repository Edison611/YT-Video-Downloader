# YouTube Audio Downloader (Local)

A **local** setup for downloading audio from YouTube videos using a FastAPI backend
and a Chrome extension frontend. Downloads land in a folder on your machine and can
be mirrored to Google Drive automatically.

## Setup

### 1. Run the backend locally

1. Build the Docker image:

```bash
docker build -t yt_download .
```

2. Run the container with the download folder mounted:

```bash
docker run -p 8765:8765 -v {local-path}:/downloads yt_download
```
Note: With Docker Desktop, set the port to 8765 and mount the local directory when running

### 2. Load the Chrome extension

Open Chrome and go to chrome://extensions/.

Enable Developer mode.

Click Load unpacked and select the folder containing the extension files.

Make sure the backend is running locally, then open a YouTube video and use the extension to download audio.

### 3. (Optional) Enable Google Drive upload

Drive upload is off until you supply an OAuth client ID. The extension performs the
Google sign-in itself via `chrome.identity` and passes a short-lived access token to
the backend with each request, so **the backend never stores your Google credentials**.

1. **Load the extension first and copy its ID** from chrome://extensions/. You need the
   ID before you can create the OAuth client. For an unpacked extension the ID is
   derived from the folder's absolute path, so it stays stable as long as you don't move
   or rename the folder. If you need it to survive a move, pack the extension once and
   add the resulting `key` to `manifest.json`.
2. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and
   enable the **Google Drive API**.
3. Configure the **OAuth consent screen**: user type *External*, then add your own Google
   account under *Test users*. Add the scope
   `https://www.googleapis.com/auth/drive.file`. You do not need to submit the app for
   verification while it is in testing mode and you are the only user.
4. Create an **OAuth client ID** with application type **Chrome Extension**, and paste the
   extension ID from step 1 into the Item ID field. This client type has no client secret,
   which is exactly what you want — extension source is readable by anyone who installs it.
5. Copy the generated client ID into `extension/manifest.json`:

```json
"oauth2": {
  "client_id": "YOUR_ID_HERE.apps.googleusercontent.com",
  "scopes": ["https://www.googleapis.com/auth/drive.file"]
}
```

6. Reload the extension, open the popup, and click **Connect Google Drive**.

The client ID committed here is safe to publish: the Chrome Extension client type has
no client secret, and Google binds the ID to one specific extension ID. That binding
also means **it will not work for you if you clone this repo** — the extension ID is
derived from your own folder path, so follow the steps above to create your own client.

#### Why the app creates its own Drive folder

The extension requests the narrow `drive.file` scope, which grants access only to files
and folders the app itself created. That keeps the blast radius small — it can never read
the rest of your Drive — but it also means it cannot upload into an arbitrary pre-existing
folder you point it at; Drive would reject that with a 403.

So the destination folder is created and owned by the app. Set its name in the popup
(default `YT Audio Downloads`); use `/` for nested folders, e.g. `Music/YouTube`. Drive has
no real file paths, so each segment is resolved or created as a folder by name.

Re-downloading the same video replaces the existing Drive file rather than adding a
duplicate, since Drive otherwise allows several files with the same name in one folder.

## Configuration

Backend environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `/downloads` | Where audio files are written inside the container |
| `ALLOWED_ORIGINS` | *(none)* | Extra comma-separated CORS origins for testing |

By default only `chrome-extension://` origins may call the API, so ordinary web pages
cannot drive your backend.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness, plus whether the Drive libraries are installed |
| `POST /download` | Starts a job, returns `{ "job_id": ... }` immediately |
| `GET /jobs/{id}` | Job stage and result |
| `POST /jobs/{id}/upload` | Retries only the Drive upload for an existing job |

Downloading and transcoding take a while, so `POST /download` returns a job id and the
extension polls for progress. The Drive access token travels in an `X-Drive-Token` header.

A failed upload does not fail the job: the local file is the durable artifact, so the
popup reports "Saved locally. Drive upload failed: ..." and `upload.status` is tracked
separately from `stage`. Access tokens last about an hour, so when one expires the
extension refreshes it and calls `POST /jobs/{id}/upload` rather than re-downloading.

## Development

Install dependencies and run the tests:

```bash
pip install -r requirements.txt pytest httpx
python -m pytest tests -q
```
