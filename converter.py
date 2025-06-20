import os
import glob
from pydub import AudioSegment

def convert_to_mp3(video_path):
    print("Starting conversion for:", video_path)
    mp3_filename = os.path.splitext(os.path.basename(video_path))[0] + '.mp3'
    print(video_path)
    print(mp3_filename)
    output_file = os.path.join("/tmp/", mp3_filename)

    AudioSegment.from_file(video_path).export(output_file, format='mp3')
    print("Conversion completed successfully:", output_file)

    return output_file, mp3_filename
