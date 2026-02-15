import yt_dlp

def download_audio(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": r"C:\Users\ediso\Documents\Music\%(title)s.%(ext)s",
        "extractaudio": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],  # VERY important
                "player_skip": ["webpage"]
            }
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


if __name__ == "__main__":
    link = input("Enter YouTube link: ")
    download_audio(link)
    print("Download completed successfully")
