import os
import glob
from pydub import AudioSegment

video_dir = '/Users/edisony611/Documents/Music/MusicMP4'  # Path where the videos are located
extension_list = '*.mp4'

os.chdir(video_dir)
for extension in extension_list:
    for video in glob.glob(extension):
        mp3_filename = os.path.splitext(os.path.basename(video))[0] + '.mp3'
        AudioSegment.from_file(video).export("/Users/edisony611/Documents/Music/" + str(mp3_filename), format='mp3')
        print("Done 1")
