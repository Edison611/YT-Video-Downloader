# YouTube Audio Downloader (Local)

This is a simple **local** setup for downloading audio from YouTube videos using a FastAPI backend and a Chrome extension frontend.

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
