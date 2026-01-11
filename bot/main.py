import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile

from config import ALLOWED_USERS, BOT_TOKEN
from keyboards import main_kb
from recorder.recorder import VideoRecorder


bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ИНИЦИАЛИЗИРУЕМ РЕКОРДЕР ОДИН РАЗ
recorder = VideoRecorder()


@dp.message(F.text == "/start")
async def start(msg: Message):
    if msg.from_user.id not in ALLOWED_USERS:
        return
    await msg.answer("🎥 Камера активна", reply_markup=main_kb())


@dp.callback_query(F.data == "video")
async def send_video(call: CallbackQuery):
    path = recorder.get_last_video()

    if not path or not os.path.exists(path):
        await call.message.answer("⏳ Видео ещё записывается")
        return

    await call.message.answer_video(FSInputFile(path))


@dp.callback_query(F.data == "status")
async def status(call: CallbackQuery):
    await call.message.answer("🟢 Камера работает")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
