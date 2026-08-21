"""A small in-memory stand-in for the Drive v3 client.

It parses the subset of Drive query syntax the uploader emits, so tests can
assert real behaviour (folder reuse, same-name dedupe, quote escaping) rather
than just that some method was called.
"""

import re

from googleapiclient.errors import HttpError

FOLDER_MIME = "application/vnd.google-apps.folder"
AUDIO_MIME = "audio/mpeg"

NAME_RE = re.compile(r"name = '((?:[^'\\]|\\.)*)'")
PARENT_RE = re.compile(r"'((?:[^'\\]|\\.)*)' in parents")


def unescape(value: str) -> str:
    return value.replace("\\'", "'").replace("\\\\", "\\")


class FakeResponse:
    def __init__(self, status):
        self.status = status
        self.reason = "Fake error"


def http_error(status, message="Something went wrong"):
    body = ('{"error": {"message": "%s"}}' % message).encode()
    return HttpError(FakeResponse(status), body)


class FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response

    def next_chunk(self):
        # Single-chunk completion: (status, response)
        return (None, self._response)


class FakeFilesApi:
    def __init__(self, drive):
        self.drive = drive

    def list(self, **kwargs):
        return self.drive.handle_list(kwargs)

    def create(self, **kwargs):
        return self.drive.handle_create(kwargs)

    def update(self, **kwargs):
        return self.drive.handle_update(kwargs)


class FakeDrive:
    def __init__(self):
        self.items = {}
        self.queries = []
        self.created = []
        self.updated = []
        self.errors = {}
        self._counter = 0

    def files(self):
        return FakeFilesApi(self)

    def _new_id(self, prefix="id"):
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def add_folder(self, name, parent="root"):
        folder_id = self._new_id("folder")
        self.items[folder_id] = {
            "name": name,
            "parents": [parent],
            "mimeType": FOLDER_MIME,
        }
        return folder_id

    def add_file(self, name, parent):
        file_id = self._new_id("file")
        self.items[file_id] = {
            "name": name,
            "parents": [parent],
            "mimeType": AUDIO_MIME,
        }
        return file_id

    def handle_list(self, kwargs):
        query = kwargs["q"]
        self.queries.append(query)
        if "list" in self.errors:
            raise self.errors["list"]

        name_match = NAME_RE.search(query)
        parent_match = PARENT_RE.search(query)
        assert name_match and parent_match, f"unexpected query: {query}"

        name = unescape(name_match.group(1))
        parent = unescape(parent_match.group(1))
        want_folder = FOLDER_MIME in query

        matches = [
            {"id": item_id, "name": item["name"]}
            for item_id, item in self.items.items()
            if item["name"] == name
            and parent in item["parents"]
            and (item["mimeType"] == FOLDER_MIME) == want_folder
        ]
        return FakeRequest({"files": matches[:1]})

    def handle_create(self, kwargs):
        body = kwargs["body"]
        is_folder = body.get("mimeType") == FOLDER_MIME

        if is_folder:
            if "create_folder" in self.errors:
                raise self.errors["create_folder"]
            folder_id = self._new_id("folder")
            self.items[folder_id] = {
                "name": body["name"],
                "parents": body.get("parents", ["root"]),
                "mimeType": FOLDER_MIME,
            }
            self.created.append(body)
            return FakeRequest({"id": folder_id, "name": body["name"]})

        if "upload" in self.errors:
            raise self.errors["upload"]
        file_id = self._new_id("file")
        self.items[file_id] = {
            "name": body["name"],
            "parents": body["parents"],
            "mimeType": AUDIO_MIME,
        }
        self.created.append(body)
        return FakeRequest(
            {
                "id": file_id,
                "name": body["name"],
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
            }
        )

    def handle_update(self, kwargs):
        if "upload" in self.errors:
            raise self.errors["upload"]
        file_id = kwargs["fileId"]
        self.updated.append(file_id)
        item = self.items[file_id]
        return FakeRequest(
            {
                "id": file_id,
                "name": item["name"],
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
            }
        )
