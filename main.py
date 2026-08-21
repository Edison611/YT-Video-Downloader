"""Local FastAPI backend: downloads YouTube audio and optionally mirrors it to Drive.

Downloads are long-running (fetch + ffmpeg transcode + upload), so ``/download``
returns a job id immediately and the client polls ``/jobs/{id}``.
"""

import copy
import os
import re
import threading
import uuid
from collections import OrderedDict
from typing import Optional

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Soft import: the backend stays usable for local-only downloads even if the
# Google client libraries aren't installed.
try:
    import drive_upload
except ImportError:  # pragma: no cover - exercised only on incomplete installs
    drive_upload = None

app = FastAPI()

# Only the extension may call this API. The previous allow_origins=["*"] meant
# any web page could drive the backend; a chrome-extension:// regex keeps the
# rule zero-config while excluding ordinary websites. Extension ids are 32
# chars in the range a-p.
EXTENSION_ORIGIN_RE = r"^chrome-extension://[a-p]{32}$"
_extra_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_extra_origins,
    allow_origin_regex=EXTENSION_ORIGIN_RE,
    allow_credentials=False,  # we authenticate per-request, no cookies
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Drive-Token"],
)

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/downloads")
MAX_TRACKED_JOBS = 50

# In-process job registry. Adequate for a single-user local tool; state is
# intentionally lost on restart rather than adding a persistence dependency.
_jobs: "OrderedDict[str, dict]" = OrderedDict()
_jobs_lock = threading.Lock()


class DownloadRequest(BaseModel):
    url: str
    folder_path: Optional[str] = None
    upload: bool = True


def create_job() -> dict:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "stage": "queued",
        "title": None,
        "local_path": None,
        "error": None,
        "upload": {
            "status": "disabled",
            "message": None,
            "file_id": None,
            "link": None,
            "folder_path": None,
            "token_expired": False,
        },
    }
    with _jobs_lock:
        _jobs[job_id] = job
        while len(_jobs) > MAX_TRACKED_JOBS:
            _jobs.popitem(last=False)
    return job


def update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def update_upload(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["upload"].update(fields)


def get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        # Deep copy so callers never observe a half-applied update.
        return copy.deepcopy(job) if job is not None else None


def first_entry(info: dict) -> dict:
    """Unwrap a playlist result to its first usable entry."""
    entries = info.get("entries")
    if not entries:
        return info
    for entry in entries:
        if entry:
            return entry
    raise ValueError("yt-dlp returned no usable entries")


def resolve_output_path(info: Optional[dict], preferred_ext: str = "mp3") -> str:
    """Find the file yt-dlp actually wrote.

    ``prepare_filename()`` reports the pre-postprocessor extension (.webm/.m4a),
    not the .mp3 that FFmpegExtractAudio produces, so the authoritative source
    is ``requested_downloads[*].filepath``.
    """
    if not info:
        raise ValueError("yt-dlp returned no metadata")

    entry = first_entry(info)

    for download in entry.get("requested_downloads") or []:
        path = download.get("filepath") or download.get("_filename")
        if path:
            return path

    fallback = entry.get("_filename") or entry.get("filename")
    if fallback:
        base, _ = os.path.splitext(fallback)
        return f"{base}.{preferred_ext}"

    raise ValueError("Could not determine the downloaded file path")


def resolve_title(info: dict, path: str) -> str:
    entry = first_entry(info)
    return entry.get("title") or os.path.splitext(os.path.basename(path))[0]


def download_audio(url: str) -> tuple[str, str]:
    """Download and transcode to mp3. Returns (local_path, title)."""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "extractaudio": True,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                "player_skip": ["webpage"],
            }
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    path = resolve_output_path(info)
    return path, resolve_title(info, path)


def run_job(
    job_id: str,
    url: str,
    access_token: Optional[str],
    folder_path: Optional[str],
    upload_requested: bool,
) -> None:
    """Download, then upload. Upload failure never invalidates the local file."""
    try:
        update_job(job_id, stage="downloading")
        local_path, title = download_audio(url)
        update_job(job_id, stage="downloaded", local_path=local_path, title=title)
    except Exception as exc:
        update_job(job_id, stage="error", error=str(exc))
        return

    if not upload_requested:
        update_upload(job_id, status="disabled")
        update_job(job_id, stage="done")
        return

    if drive_upload is None:
        update_upload(
            job_id,
            status="error",
            message="Drive libraries are not installed on the backend",
        )
        update_job(job_id, stage="done")
        return

    if not access_token:
        update_upload(
            job_id,
            status="error",
            message="No Drive token supplied; connect Drive in the extension",
            token_expired=True,
        )
        update_job(job_id, stage="done")
        return

    try:
        update_job(job_id, stage="uploading")
        update_upload(job_id, status="uploading")
        result = drive_upload.upload_audio(access_token, local_path, folder_path)
        update_upload(
            job_id,
            status="done",
            file_id=result["file_id"],
            link=result["link"],
            folder_path=result["folder_path"],
            message="Replaced existing file" if result["replaced"] else None,
        )
    except drive_upload.DriveUploadError as exc:
        update_upload(
            job_id, status="error", message=str(exc), token_expired=exc.token_expired
        )
    except Exception as exc:  # unexpected: still keep the local file result
        update_upload(job_id, status="error", message=f"Unexpected upload error: {exc}")

    # The local download succeeded, so the job as a whole did too. Clients read
    # upload.status separately to report partial success.
    update_job(job_id, stage="done")


def run_upload_only(
    job_id: str,
    local_path: str,
    access_token: str,
    folder_path: Optional[str],
) -> None:
    """Retry just the Drive upload for an already-downloaded job."""
    try:
        update_job(job_id, stage="uploading")
        update_upload(job_id, status="uploading", message=None, token_expired=False)
        result = drive_upload.upload_audio(access_token, local_path, folder_path)
        update_upload(
            job_id,
            status="done",
            file_id=result["file_id"],
            link=result["link"],
            folder_path=result["folder_path"],
            message="Replaced existing file" if result["replaced"] else None,
        )
    except drive_upload.DriveUploadError as exc:
        update_upload(
            job_id, status="error", message=str(exc), token_expired=exc.token_expired
        )
    except Exception as exc:
        update_upload(job_id, status="error", message=f"Unexpected upload error: {exc}")

    update_job(job_id, stage="done")


@app.get("/health")
def health():
    return {"status": "ok", "drive_available": drive_upload is not None}


@app.post("/download")
def download(
    req: DownloadRequest,
    background_tasks: BackgroundTasks,
    x_drive_token: Optional[str] = Header(default=None),
):
    if not re.match(r"^https?://", req.url or ""):
        raise HTTPException(status_code=400, detail="A http(s) URL is required")

    job = create_job()
    folder_path = req.folder_path or (
        drive_upload.DEFAULT_FOLDER if drive_upload else "YT Audio Downloads"
    )

    if req.upload:
        update_upload(job["id"], status="pending", folder_path=folder_path)

    background_tasks.add_task(
        run_job, job["id"], req.url, x_drive_token, folder_path, req.upload
    )
    return {"job_id": job["id"], "stage": "queued"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job


class RetryUploadRequest(BaseModel):
    folder_path: Optional[str] = None


@app.post("/jobs/{job_id}/upload")
def retry_upload(
    job_id: str,
    req: RetryUploadRequest,
    background_tasks: BackgroundTasks,
    x_drive_token: Optional[str] = Header(default=None),
):
    """Re-attempt only the upload, reusing the already-downloaded file.

    Access tokens expire after about an hour, so the common failure is a stale
    token; re-downloading and re-transcoding to recover from that would be
    pure waste.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    if drive_upload is None:
        raise HTTPException(
            status_code=503, detail="Drive libraries are not installed on the backend"
        )
    if not x_drive_token:
        raise HTTPException(status_code=400, detail="Missing X-Drive-Token header")

    local_path = job.get("local_path")
    if not local_path:
        raise HTTPException(status_code=409, detail="Job has no downloaded file yet")
    if not os.path.isfile(local_path):
        raise HTTPException(
            status_code=410, detail="The downloaded file is no longer on disk"
        )

    folder_path = req.folder_path or job["upload"].get("folder_path") or (
        drive_upload.DEFAULT_FOLDER
    )
    update_upload(job_id, status="pending", folder_path=folder_path)
    background_tasks.add_task(
        run_upload_only, job_id, local_path, x_drive_token, folder_path
    )
    return {"job_id": job_id, "stage": "uploading"}
