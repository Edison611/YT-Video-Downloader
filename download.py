import tempfile
from pytubefix import YouTube
from pytubefix.cli import on_progress
import os

def Download(link):
    print("Starting download... for", link)
    youtubeObject = YouTube(link, client='WEB_EMBED')
    tmp_dir = tempfile.gettempdir()
    file_name = "".join(c for c in f"{youtubeObject.title}.m4a" if c.isalnum() or c in (' ', '.', '_')).strip()

    # youtubeObject = youtubeObject.streams.get_highest_resolution() # Used for Video Downloads
    youtubeObject = youtubeObject.streams.get_audio_only()
    full_path = youtubeObject.download(output_path=tmp_dir, filename=file_name)


    print("Download is completed successfully at: ", full_path)

    return full_path, file_name
