import ffmpeg, os
from config import *

async def convert_to_mp4(raw_path):
    name = os.path.basename(raw_path).replace(".avi", ".mp4")
    mp4_path = f"{VIDEO_DIR}/{name}"

    (
        ffmpeg
        .input(raw_path)
        .output(
            mp4_path,
            vcodec="libx264",
            pix_fmt="yuv420p",
            preset="fast",
            movflags="+faststart"
        )
        .overwrite_output()
        .run(quiet=True)
    )

    os.remove(raw_path)
    return mp4_path
