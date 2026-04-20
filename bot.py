import os
import logging
import asyncio
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

import aiosqlite

load_dotenv()
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("❌ TOKEN не найден в .env")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

logging.basicConfig(level=logging.INFO)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '0000')
admin_users = set()

# ==================== База данных ====================
async def init_db():
    async with aiosqlite.connect('movies.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                rating REAL,
                poster TEXT,
                description TEXT,
                added_by INTEGER,
                user_rating REAL,
                admin_rating REAL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT,
                rating REAL,
                poster TEXT,
                description TEXT,
                suggested_by INTEGER,
                status TEXT DEFAULT 'pending'
            )
        ''')
        await db.commit()

# ==================== Состояния ====================
class SuggestionStates(StatesGroup):
    waiting_title = State()
    waiting_category = State()
    waiting_rating = State()
    waiting_poster = State()
    waiting_description = State()

class ApproveStates(StatesGroup):
    waiting_final_rating = State()
    waiting_final_description = State()

class DeleteStates(StatesGroup):
    waiting_delete_confirm = State()

# ==================== Главное меню ====================
def get_main_menu(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📽 Предложить фильм", "🎲 Случайный фильм")
    kb.add("📋 Посмотреть фильмы")
    if is_admin:
        kb.add("🔧 Админ-панель", "🗑 Удалить фильм")
    return kb

# ==================== Старт ====================
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в кино-трекер!\n\n"
        f"Чтобы стать админом — введи пароль: `{ADMIN_PASSWORD}`",
        parse_mode="Markdown",
        reply_markup=get_main_menu(False)
    )

# ==================== Логин админа ====================
@dp.message_handler(lambda message: message.text == ADMIN_PASSWORD)
async def login_admin(message: types.Message):
    if message.from_user.id not in admin_users:
        admin_users.add(message.from_user.id)
        await message.answer("✅ Ты теперь админ!", reply_markup=get_main_menu(True))
    else:
        await message.answer("Ты уже админ.")

# ==================== Запуск ====================
async def main():
    await init_db()
    print("✅ Бот успешно запущен!")
    executor.start_polling(dp, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())