import os
import glob
from pydub import AudioSegment

video_dir = '/Users/ediso/Documents/Music/'  # Path where the videos are located
output_path = '/Users/ediso/Documents/MusicMP3/'  # Path where the converted MP3 files will be saved
extension_list = '*.m4a' # File extensions to look for

os.chdir(video_dir)
for extension in extension_list:
    for video in glob.glob(extension):
        mp3_filename = os.path.splitext(os.path.basename(video))[0] + '.mp3'
        AudioSegment.from_file(video).export("/Users/ediso/Documents/MusicMP3/" + str(mp3_filename), format='mp3')
        print("Completed Converting 1")
