from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📹 Получить видео", callback_data="video")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")]
    ])
