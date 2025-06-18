from fastapi import FastAPI, Query
from download import Download
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import os

app = FastAPI()

def remove_file(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

@app.get("/")
def root():
    return {"message": "Welcome to the Video Downloader API. Use /download?url=<video_url> to download videos."}

@app.get("/download")
def download_video(url: str = Query(...)):
    try:
        file_path, filename = Download(url)
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="audio/mp4",
            # background=BackgroundTask(remove_file, file_path)
        )
    except Exception as e:
        return {"error": str(e)}
