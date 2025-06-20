from fastapi import FastAPI, Query
from download import Download
from fastapi.responses import FileResponse
import os
import glob
from converter import convert_to_mp3

app = FastAPI()

def remove_tmp_files():
    try:
        for file_path in glob.glob("/tmp/*"):
            if os.path.isfile(file_path):
                os.remove(file_path)
    except FileNotFoundError:
        pass

@app.get("/")
def root():
    return {"message": "Welcome to the Video Downloader API. Use /download?url=<video_url> to download videos."}

@app.get("/download")
def download_video(url: str = Query(...)):
    try:
        if not url:
            return {"error": "URL parameter is required."}
        remove_tmp_files()  # Clean up temporary files before download
        file_path, filename = Download(url)
        file_path, filename = convert_to_mp3(file_path)

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="audio/mp3"
        )
    except Exception as e:
        return {"error": str(e)}
