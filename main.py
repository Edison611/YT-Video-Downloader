from fastapi import FastAPI, Query
from download import Download
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
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

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html>
      <head>
        <title>YouTube MP3 Downloader</title>
      </head>
      <body>
        <h2>Use /download?url=<video_url> to download videos or submit url in the following form</h2>
        <form action="/download" method="get">
          <input type="text" name="url" placeholder="Enter video URL" size="100" required />
          <br><br>
          <button type="submit">Download</button>
        </form>
      </body>
    </html>
    """

@app.get("/download")
def download(url: str = Query(...)):
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
