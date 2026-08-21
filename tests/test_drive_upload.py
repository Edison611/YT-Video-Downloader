import pytest
from fake_drive import FakeDrive, http_error

import drive_upload
from drive_upload import DriveUploadError


@pytest.fixture
def drive():
    return FakeDrive()


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "Some Song.mp3"
    path.write_bytes(b"\x00" * 2048)
    return str(path)


# ---------- folder path handling ----------


def test_split_folder_path_defaults_when_blank():
    assert drive_upload.split_folder_path("") == [drive_upload.DEFAULT_FOLDER]
    assert drive_upload.split_folder_path(None) == [drive_upload.DEFAULT_FOLDER]
    assert drive_upload.split_folder_path("   ") == [drive_upload.DEFAULT_FOLDER]


def test_split_folder_path_handles_both_separators_and_junk():
    assert drive_upload.split_folder_path("Music/YouTube") == ["Music", "YouTube"]
    assert drive_upload.split_folder_path("Music\\YouTube") == ["Music", "YouTube"]
    assert drive_upload.split_folder_path("//Music//YouTube//") == ["Music", "YouTube"]
    assert drive_upload.split_folder_path("../Music") == ["Music"]


def test_ensure_folder_path_creates_nested_folders(drive):
    leaf = drive_upload.ensure_folder_path(drive, "Music/YouTube")

    assert len(drive.created) == 2
    assert drive.created[0]["name"] == "Music"
    assert "parents" not in drive.created[0]  # top level lands in root
    assert drive.created[1]["name"] == "YouTube"

    music_id = next(i for i, it in drive.items.items() if it["name"] == "Music")
    assert drive.created[1]["parents"] == [music_id]
    assert drive.items[leaf]["name"] == "YouTube"
    assert drive.items[leaf]["parents"] == [music_id]


def test_ensure_folder_path_reuses_existing_folder(drive):
    existing = drive.add_folder(drive_upload.DEFAULT_FOLDER)

    resolved = drive_upload.ensure_folder_path(drive, drive_upload.DEFAULT_FOLDER)

    assert resolved == existing
    assert drive.created == []  # nothing new created


def test_ensure_folder_path_is_idempotent(drive):
    first = drive_upload.ensure_folder_path(drive, "Music/YouTube")
    second = drive_upload.ensure_folder_path(drive, "Music/YouTube")

    assert first == second
    assert len(drive.created) == 2  # only the first call created anything


def test_folder_names_with_quotes_are_escaped(drive):
    drive_upload.ensure_folder_path(drive, "Don't Stop")

    # The literal must be escaped in the query or Drive rejects it.
    assert any("Don\\'t Stop" in query for query in drive.queries)
    assert drive.created[0]["name"] == "Don't Stop"


# ---------- uploading ----------


def test_upload_file_creates_new_file(drive, audio_file):
    folder_id = drive.add_folder("Target")

    result = drive_upload.upload_file(drive, audio_file, folder_id)

    assert result["replaced"] is False
    assert result["name"] == "Some Song.mp3"
    assert result["link"].startswith("https://drive.google.com/")
    assert drive.created[0]["parents"] == [folder_id]


def test_upload_file_replaces_same_name_instead_of_duplicating(drive, audio_file):
    folder_id = drive.add_folder("Target")
    existing_id = drive.add_file("Some Song.mp3", folder_id)

    result = drive_upload.upload_file(drive, audio_file, folder_id)

    assert result["replaced"] is True
    assert result["file_id"] == existing_id
    assert drive.updated == [existing_id]
    assert drive.created == []


def test_same_name_in_a_different_folder_is_not_treated_as_duplicate(
    drive, audio_file
):
    other_folder = drive.add_folder("Other")
    drive.add_file("Some Song.mp3", other_folder)
    target = drive.add_folder("Target")

    result = drive_upload.upload_file(drive, audio_file, target)

    assert result["replaced"] is False


def test_upload_audio_end_to_end(monkeypatch, drive, audio_file):
    monkeypatch.setattr(drive_upload, "build_service", lambda token: drive)

    result = drive_upload.upload_audio("token-123", audio_file, "Music/YouTube")

    assert result["folder_path"] == "Music/YouTube"
    assert result["file_id"]
    leaf = drive.items[result["folder_id"]]
    assert leaf["name"] == "YouTube"


# ---------- error mapping ----------


def test_missing_local_file_is_reported(tmp_path):
    with pytest.raises(DriveUploadError, match="Local file missing"):
        drive_upload.upload_audio("token", str(tmp_path / "nope.mp3"))


def test_empty_local_file_is_reported(tmp_path):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")

    with pytest.raises(DriveUploadError, match="empty"):
        drive_upload.upload_audio("token", str(empty))


def test_missing_token_is_reported():
    with pytest.raises(DriveUploadError) as excinfo:
        drive_upload.build_service("")

    assert excinfo.value.status == 401
    assert excinfo.value.token_expired is True


def test_401_maps_to_token_expired(drive, audio_file):
    folder_id = drive.add_folder("Target")
    drive.errors["upload"] = http_error(401, "Invalid Credentials")

    with pytest.raises(DriveUploadError) as excinfo:
        drive_upload.upload_file(drive, audio_file, folder_id)

    assert excinfo.value.status == 401
    assert excinfo.value.token_expired is True


def test_403_is_not_treated_as_token_expiry(drive, audio_file):
    """A scope/ownership problem must not trigger a pointless token retry."""
    folder_id = drive.add_folder("Target")
    drive.errors["upload"] = http_error(403, "Insufficient permissions")

    with pytest.raises(DriveUploadError) as excinfo:
        drive_upload.upload_file(drive, audio_file, folder_id)

    assert excinfo.value.status == 403
    assert excinfo.value.token_expired is False
    assert "drive.file" in str(excinfo.value)


def test_api_not_enabled_is_not_blamed_on_folder_ownership(drive, audio_file):
    """A 403 from a disabled API must not suggest a drive.file scope problem."""
    folder_id = drive.add_folder("Target")
    drive.errors["upload"] = http_error(
        403,
        "Google Drive API has not been used in project 1234 before or it is disabled.",
    )

    with pytest.raises(DriveUploadError) as excinfo:
        drive_upload.upload_file(drive, audio_file, folder_id)

    message = str(excinfo.value)
    assert "not enabled for this Cloud project" in message
    assert "drive.file" not in message
    assert excinfo.value.token_expired is False


def test_folder_lookup_error_is_wrapped(drive):
    drive.errors["list"] = http_error(500, "Backend error")

    with pytest.raises(DriveUploadError, match="look up folder"):
        drive_upload.ensure_folder_path(drive, "Music")
