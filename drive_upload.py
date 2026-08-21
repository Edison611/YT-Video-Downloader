"""Google Drive upload helper.

The backend deliberately stores **no** Google credentials. The Chrome extension
obtains a short-lived OAuth access token via ``chrome.identity`` and passes it
per request, so the worst case for a compromised backend is a token that
expires within the hour.

Because the extension requests the narrow ``drive.file`` scope, this module can
only see files and folders it created itself. That is why the destination
folder is *created and owned by the app* rather than pointed at an arbitrary
pre-existing folder, which would fail with a 403.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

FOLDER_MIME = "application/vnd.google-apps.folder"
AUDIO_MIME = "audio/mpeg"
DEFAULT_FOLDER = "YT Audio Downloads"

# Drive resolves an upload in 5 MB chunks; large enough to be efficient,
# small enough that a dropped connection doesn't restart the whole transfer.
CHUNK_SIZE = 5 * 1024 * 1024


class DriveUploadError(Exception):
    """Raised for any failure during folder resolution or upload."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status

    @property
    def token_expired(self) -> bool:
        """True only when a fresh token could plausibly fix the failure.

        Deliberately excludes 403: that indicates a permission/scope problem
        (e.g. a folder this app doesn't own), which retrying cannot resolve.
        """
        return self.status == 401


def _escape(value: str) -> str:
    """Escape a value for interpolation into a Drive query string.

    Drive wraps query literals in single quotes, so backslashes and quotes
    must be escaped or a title like ``Don't Stop`` breaks the query.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _wrap_http_error(err: HttpError, action: str) -> DriveUploadError:
    status = getattr(getattr(err, "resp", None), "status", None)
    detail = getattr(err, "reason", None) or str(err)
    if status == 401:
        return DriveUploadError("Drive token expired or invalid", status=401)
    if status == 403:
        lowered = detail.lower()
        # A 403 covers two very different causes; don't blame folder
        # ownership when the project simply hasn't enabled the API.
        if (
            "has not been used in project" in lowered
            or "accessnotconfigured" in lowered
            or "api is disabled" in lowered
        ):
            return DriveUploadError(
                f"The Google Drive API is not enabled for this Cloud project. {detail}",
                status=403,
            )
        return DriveUploadError(
            f"Drive refused to {action}: {detail}. The app can only touch "
            "folders it created itself under the drive.file scope.",
            status=403,
        )
    if status == 404:
        return DriveUploadError(f"Drive target not found while trying to {action}", status=404)
    return DriveUploadError(f"Drive failed to {action}: {detail}", status=status)


def build_service(access_token: str):
    """Build a Drive v3 client from a bare OAuth access token."""
    if not access_token:
        raise DriveUploadError("Missing Drive access token", status=401)
    creds = Credentials(token=access_token)
    # cache_discovery=False avoids the noisy oauth2client file_cache warning.
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def split_folder_path(folder_path: Optional[str]) -> list[str]:
    """Turn a user-supplied folder string into clean path segments.

    Drive has no real paths, so ``A/B`` means "folder B inside folder A", each
    created by this app if missing.
    """
    if not folder_path:
        return [DEFAULT_FOLDER]
    segments = [seg.strip() for seg in re.split(r"[\\/]+", folder_path)]
    segments = [seg for seg in segments if seg and seg not in (".", "..")]
    return segments or [DEFAULT_FOLDER]


def find_folder(service, name: str, parent_id: Optional[str]) -> Optional[str]:
    """Return the id of an app-created folder, or None."""
    clauses = [
        f"name = '{_escape(name)}'",
        f"mimeType = '{FOLDER_MIME}'",
        "trashed = false",
        f"'{_escape(parent_id) if parent_id else 'root'}' in parents",
    ]
    try:
        response = (
            service.files()
            .list(
                q=" and ".join(clauses),
                spaces="drive",
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
    except HttpError as err:
        raise _wrap_http_error(err, f"look up folder '{name}'") from err

    files = response.get("files") or []
    return files[0]["id"] if files else None


def create_folder(service, name: str, parent_id: Optional[str]) -> str:
    metadata = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        metadata["parents"] = [parent_id]
    try:
        folder = service.files().create(body=metadata, fields="id").execute()
    except HttpError as err:
        raise _wrap_http_error(err, f"create folder '{name}'") from err
    return folder["id"]


def ensure_folder_path(service, folder_path: Optional[str]) -> str:
    """Resolve (creating as needed) a folder path and return the leaf id."""
    parent_id: Optional[str] = None
    for segment in split_folder_path(folder_path):
        parent_id = find_folder(service, segment, parent_id) or create_folder(
            service, segment, parent_id
        )
    assert parent_id is not None  # split_folder_path never returns empty
    return parent_id


def find_file(service, name: str, folder_id: str) -> Optional[str]:
    """Return the id of a same-named file in the folder, if any.

    Drive permits duplicate sibling names, so without this check every
    re-download would silently pile up another copy.
    """
    clauses = [
        f"name = '{_escape(name)}'",
        "trashed = false",
        f"'{_escape(folder_id)}' in parents",
    ]
    try:
        response = (
            service.files()
            .list(
                q=" and ".join(clauses),
                spaces="drive",
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
    except HttpError as err:
        raise _wrap_http_error(err, f"look up file '{name}'") from err

    files = response.get("files") or []
    return files[0]["id"] if files else None


def _execute_resumable(request, progress_callback: Optional[Callable[[int], None]]):
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            progress_callback(int(status.progress() * 100))
    return response


def upload_file(
    service,
    file_path: str,
    folder_id: str,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> dict:
    """Upload (or replace) a single audio file inside ``folder_id``."""
    name = os.path.basename(file_path)
    media = MediaFileUpload(
        file_path, mimetype=AUDIO_MIME, chunksize=CHUNK_SIZE, resumable=True
    )
    existing_id = find_file(service, name, folder_id)

    try:
        if existing_id:
            # parents is not writable via update(); content only.
            request = service.files().update(
                fileId=existing_id,
                media_body=media,
                fields="id, name, webViewLink",
            )
        else:
            request = service.files().create(
                body={"name": name, "parents": [folder_id]},
                media_body=media,
                fields="id, name, webViewLink",
            )
        response = _execute_resumable(request, progress_callback)
    except HttpError as err:
        raise _wrap_http_error(err, f"upload '{name}'") from err

    return {
        "file_id": response.get("id"),
        "name": response.get("name", name),
        "link": response.get("webViewLink"),
        "folder_id": folder_id,
        "replaced": bool(existing_id),
    }


def upload_audio(
    access_token: str,
    file_path: str,
    folder_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> dict:
    """Upload a local audio file into an app-owned Drive folder."""
    if not os.path.isfile(file_path):
        raise DriveUploadError(f"Local file missing: {file_path}")
    if os.path.getsize(file_path) == 0:
        raise DriveUploadError(f"Local file is empty: {file_path}")

    service = build_service(access_token)
    folder_id = ensure_folder_path(service, folder_path)
    result = upload_file(service, file_path, folder_id, progress_callback)
    result["folder_path"] = "/".join(split_folder_path(folder_path))
    return result
