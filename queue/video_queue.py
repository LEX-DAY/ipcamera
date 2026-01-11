import asyncio
from recorder.ffmpeg_worker import convert_to_mp4

queue = asyncio.Queue()

async def worker():
    while True:
        raw = await queue.get()
        await convert_to_mp4(raw)
        queue.task_done()
