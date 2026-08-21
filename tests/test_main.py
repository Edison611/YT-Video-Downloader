import pytest
from fastapi.testclient import TestClient

import drive_upload
import main

EXTENSION_ORIGIN = "chrome-extension://" + "a" * 32


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clear_jobs():
    main._jobs.clear()
    yield
    main._jobs.clear()


@pytest.fixture
def local_file(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"\x00" * 1024)
    return str(path)


# ---------- resolve_output_path ----------


def test_prefers_the_post_processed_filepath():
    """The .mp3 written by FFmpegExtractAudio, not the source .webm."""
    info = {
        "title": "Song",
        "_filename": "/downloads/Song.webm",
        "requested_downloads": [{"filepath": "/downloads/Song.mp3"}],
    }

    assert main.resolve_output_path(info) == "/downloads/Song.mp3"


def test_falls_back_to_filename_with_swapped_extension():
    info = {"title": "Song", "_filename": "/downloads/Song.webm"}

    assert main.resolve_output_path(info) == "/downloads/Song.mp3"


def test_unwraps_playlist_entries():
    info = {
        "entries": [
            None,
            {"title": "First", "requested_downloads": [{"filepath": "/d/First.mp3"}]},
        ]
    }

    assert main.resolve_output_path(info) == "/d/First.mp3"


def test_dotted_titles_keep_their_full_name():
    info = {
        "title": "Song feat. Someone",
        "requested_downloads": [{"filepath": "/d/Song feat. Someone.mp3"}],
    }

    assert main.resolve_output_path(info) == "/d/Song feat. Someone.mp3"


def test_missing_metadata_raises():
    with pytest.raises(ValueError):
        main.resolve_output_path(None)
    with pytest.raises(ValueError):
        main.resolve_output_path({"title": "no paths at all"})


def test_resolve_title_falls_back_to_the_filename():
    assert main.resolve_title({}, "/downloads/Fallback Name.mp3") == "Fallback Name"
    assert main.resolve_title({"title": "Real Title"}, "/d/x.mp3") == "Real Title"


# ---------- health ----------


def test_health_reports_drive_availability(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["drive_available"] is True


# ---------- download endpoint ----------


def test_download_rejects_a_non_http_url(client):
    res = client.post("/download", json={"url": "not-a-url"})

    assert res.status_code == 400


def test_download_without_upload_reports_local_success(client, monkeypatch, local_file):
    monkeypatch.setattr(main, "download_audio", lambda url: (local_file, "Track"))

    res = client.post(
        "/download", json={"url": "https://youtube.com/watch?v=x", "upload": False}
    )
    job_id = res.json()["job_id"]

    # TestClient runs background tasks before returning, so the job is settled.
    job = client.get(f"/jobs/{job_id}").json()
    assert job["stage"] == "done"
    assert job["local_path"] == local_file
    assert job["title"] == "Track"
    assert job["upload"]["status"] == "disabled"


def test_download_failure_is_surfaced(client, monkeypatch):
    def boom(url):
        raise RuntimeError("video unavailable")

    monkeypatch.setattr(main, "download_audio", boom)

    res = client.post("/download", json={"url": "https://youtube.com/watch?v=x"})
    job = client.get(f"/jobs/{res.json()['job_id']}").json()

    assert job["stage"] == "error"
    assert "video unavailable" in job["error"]


def test_upload_requested_without_a_token_is_an_upload_error_only(
    client, monkeypatch, local_file
):
    monkeypatch.setattr(main, "download_audio", lambda url: (local_file, "Track"))

    res = client.post("/download", json={"url": "https://youtube.com/watch?v=x"})
    job = client.get(f"/jobs/{res.json()['job_id']}").json()

    assert job["stage"] == "done"  # the local download still succeeded
    assert job["upload"]["status"] == "error"
    assert job["upload"]["token_expired"] is True


def test_successful_upload_records_the_link(client, monkeypatch, local_file):
    monkeypatch.setattr(main, "download_audio", lambda url: (local_file, "Track"))
    monkeypatch.setattr(
        drive_upload,
        "upload_audio",
        lambda token, path, folder: {
            "file_id": "file-1",
            "link": "https://drive.google.com/file/d/file-1/view",
            "folder_path": "Music/YouTube",
            "replaced": False,
            "name": "Track.mp3",
        },
    )

    res = client.post(
        "/download",
        json={"url": "https://youtube.com/watch?v=x", "folder_path": "Music/YouTube"},
        headers={"X-Drive-Token": "token-abc"},
    )
    job = client.get(f"/jobs/{res.json()['job_id']}").json()

    assert job["stage"] == "done"
    assert job["upload"]["status"] == "done"
    assert job["upload"]["file_id"] == "file-1"
    assert job["upload"]["folder_path"] == "Music/YouTube"


def test_upload_failure_keeps_the_local_download_successful(
    client, monkeypatch, local_file
):
    monkeypatch.setattr(main, "download_audio", lambda url: (local_file, "Track"))

    def fail(token, path, folder):
        raise drive_upload.DriveUploadError("Drive token expired", status=401)

    monkeypatch.setattr(drive_upload, "upload_audio", fail)

    res = client.post(
        "/download",
        json={"url": "https://youtube.com/watch?v=x"},
        headers={"X-Drive-Token": "stale"},
    )
    job = client.get(f"/jobs/{res.json()['job_id']}").json()

    assert job["stage"] == "done"
    assert job["local_path"] == local_file
    assert job["upload"]["status"] == "error"
    assert job["upload"]["token_expired"] is True


# ---------- job lookup and retry ----------


def test_unknown_job_returns_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_retry_upload_requires_a_token(client):
    job = main.create_job()

    res = client.post(f"/jobs/{job['id']}/upload", json={})

    assert res.status_code == 400


def test_retry_upload_rejects_a_job_with_no_download(client):
    job = main.create_job()

    res = client.post(
        f"/jobs/{job['id']}/upload", json={}, headers={"X-Drive-Token": "t"}
    )

    assert res.status_code == 409


def test_retry_upload_detects_a_deleted_file(client, tmp_path):
    job = main.create_job()
    main.update_job(job["id"], local_path=str(tmp_path / "gone.mp3"))

    res = client.post(
        f"/jobs/{job['id']}/upload", json={}, headers={"X-Drive-Token": "t"}
    )

    assert res.status_code == 410


def test_retry_upload_succeeds_without_redownloading(client, monkeypatch, local_file):
    job = main.create_job()
    main.update_job(job["id"], stage="done", local_path=local_file)

    def boom(url):
        raise AssertionError("retry must not re-download")

    monkeypatch.setattr(main, "download_audio", boom)
    monkeypatch.setattr(
        drive_upload,
        "upload_audio",
        lambda token, path, folder: {
            "file_id": "file-9",
            "link": "https://drive.google.com/file/d/file-9/view",
            "folder_path": folder,
            "replaced": True,
            "name": "Track.mp3",
        },
    )

    res = client.post(
        f"/jobs/{job['id']}/upload",
        json={"folder_path": "Music"},
        headers={"X-Drive-Token": "fresh"},
    )
    assert res.status_code == 200

    settled = client.get(f"/jobs/{job['id']}").json()
    assert settled["upload"]["status"] == "done"
    assert settled["upload"]["file_id"] == "file-9"
    assert settled["upload"]["message"] == "Replaced existing file"


# ---------- job registry ----------


def test_job_registry_is_capped(client):
    for _ in range(main.MAX_TRACKED_JOBS + 10):
        main.create_job()

    assert len(main._jobs) == main.MAX_TRACKED_JOBS


def test_get_job_returns_a_copy(client):
    job = main.create_job()

    snapshot = main.get_job(job["id"])
    snapshot["upload"]["status"] = "tampered"

    assert main.get_job(job["id"])["upload"]["status"] == "disabled"


# ---------- CORS ----------


def test_extension_origin_is_allowed(client):
    res = client.get("/health", headers={"Origin": EXTENSION_ORIGIN})

    assert res.headers.get("access-control-allow-origin") == EXTENSION_ORIGIN


def test_arbitrary_websites_are_not_allowed(client):
    """Any web page could previously drive the backend via allow_origins=['*']."""
    res = client.get("/health", headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in res.headers


def test_preflight_permits_the_drive_token_header(client):
    res = client.options(
        "/download",
        headers={
            "Origin": EXTENSION_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-drive-token,content-type",
        },
    )

    assert res.status_code == 200
    allowed = res.headers.get("access-control-allow-headers", "").lower()
    assert "x-drive-token" in allowed
