from pytubefix import YouTube
from pytubefix.cli import on_progress
# from pytube import YouTube


def Download(link):
    youtubeObject = YouTube(link, on_progress_callback = on_progress)
    # youtubeObject = youtubeObject.streams.get_highest_resolution() # Used for Video Downloads
    youtubeObject = youtubeObject.streams.get_audio_only()
    youtubeObject.download(output_path="/Users/ediso/Documents/Music/")
    # except:
    #     print("An error has occurred")
    print("Download is completed successfully")


CLIENTS = {
    1: "WEB",
    2: "WEB_EMBED",
    3: "WEB_MUSIC",
    4: "WEB_CREATOR",
    5: "WEB_SAFARI",
    6: "ANDROID",
    7: "ANDROID_MUSIC",
    8: "ANDROID_CREATOR",
    9: "ANDROID_VR",
    10: "ANDROID_PRODUCER",
    11: "ANDROID_TESTSUITE",
    12: "IOS",
    13: "IOS_MUSIC",
    14: "IOS_CREATOR",
    15: "MWEB",
    16: "TV_EMBED",
    17: "MEDIA_CONNECT",
}


def Download2(url, settings, filetype: str):
    """Download filetype (video or audio) with one of the clients from the CLIENTS list."""
    for _, client in CLIENTS.items():
        try:
            # Try to reach filetype and create YouTube object
            print(f'Trying to reach {filetype} with "{client}" client', "yellow")
            yt = (
                YouTube(url=url, client=client, on_progress_callback=on_progress)
                .streams.filter(**settings["params"])
                .order_by(settings["order_by"])
                .desc()
                .first()
            )

            # Download filetype (video or audio)
            print(f'Downloading "{(yt.title)}" ' f'{settings["intro_message"]}')
            yt.download(filename=f"{filetype}.mp4", skip_existing=False, timeout=10, max_retries=5)
            print(f'\n{settings["out_message"]}', "blue")

            # Return from function if success
            return
        except Exception as e:
            print(f'Error occured while downloading via "{client}" client: {e}\n', "red")

    raise Exception("Failed to download asset with all available clients")



link = input("Enter the YouTube video URL: ")
Download(link)
# https://youtu.be/tzug3Dm37NQ