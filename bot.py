import os
import logging
import asyncio
from dotenv import load_dotenv

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

import aiosqlite

load_dotenv()

# ==================== Глобальные переменные ====================
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '0000')
admin_users = set()
TOKEN = os.getenv('TOKEN')

if not TOKEN:
    raise ValueError("❌ TOKEN не найден в .env файле!")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


logging.basicConfig(level=logging.INFO)

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
    waiting_search_query = State()  # Ожидание поискового запроса

# ==================== Главное меню ====================
def get_main_menu(is_admin: bool = False):
    kb = [
        [KeyboardButton(text="📽 Предложить фильм"), KeyboardButton(text="🎲 Случайный фильм")],
        [KeyboardButton(text="📋 Посмотреть фильмы")]
    ]
    if is_admin:
        kb.append([KeyboardButton(text="🔧 Админ-панель"), KeyboardButton(text="🗑 Удалить фильм")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def is_admin(user_id: int) -> bool:
    return user_id in admin_users

# ==================== Старт ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в кино-трекер!\n\n"
        "По умолчанию ты в режиме пользователя.\n"
        f"Чтобы стать админом — введи пароль: `XXXX`",
        parse_mode="Markdown",
        reply_markup=get_main_menu(False)
    )

# ==================== Логин админа ====================
@dp.message(F.text == ADMIN_PASSWORD)
async def login_admin(message: types.Message):
    if message.from_user.id not in admin_users:
        admin_users.add(message.from_user.id)
        await message.answer("✅ Ты теперь админ!", reply_markup=get_main_menu(True))
    else:
        await message.answer("Ты уже в админ-режиме.")

# ==================== Админ-панель ====================
@dp.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return

    async with aiosqlite.connect('movies.db') as db:
        async with db.execute(
            "SELECT id, title, category, rating, suggested_by FROM suggestions WHERE status = 'pending'"
        ) as cursor:
            suggestions = await cursor.fetchall()

    if not suggestions:
        await message.answer("✅ Нет новых предложений на модерацию.")
    else:
        for sug in suggestions:
            sug_id, title, cat, rating, user_id = sug
            text = f"📌 Предложение #{sug_id}\nНазвание: {title}\nКатегория: {cat}\nОценка: {rating}\nОт: {user_id}"

            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{sug_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{sug_id}")
            ]])
            await message.answer(text, reply_markup=markup)

    # Кнопки управления
    control = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚪 Выйти из админа", callback_data="admin_logout"),
        InlineKeyboardButton(text="↩ Вернуться в меню", callback_data="back_to_menu")
    ]])
    await message.answer("⚙️ Управление админ-режимом:", reply_markup=control)



# ==================== Callback обработчик (с уведомлением пользователя) ====================
@dp.callback_query(
    F.data.startswith("approve_") |
    F.data.startswith("reject_") |
    (F.data == "admin_logout") |
    (F.data == "back_to_menu")
)
async def callback_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()

    if call.data.startswith("approve_"):
        sug_id = int(call.data.split("_")[1])
        await state.set_state(ApproveStates.waiting_final_rating)
        await state.update_data(approve_id=sug_id)
        await call.message.answer(f"Одобряем предложение #{sug_id}.\nТвоя финальная оценка (дробная):")

    elif call.data.startswith("reject_"):
        sug_id = int(call.data.split("_")[1])
        
        # Получаем название фильма для уведомления пользователя
        async with aiosqlite.connect('movies.db') as db:
            async with db.execute("SELECT title, suggested_by FROM suggestions WHERE id = ?", (sug_id,)) as cursor:
                row = await cursor.fetchone()
        
        if row:
            title, suggested_by = row
            await bot.send_message(
                suggested_by, 
                f"❌ Ваш фильм «{title}» был отклонён администратором."
            )

        async with aiosqlite.connect('movies.db') as db:
            await db.execute("UPDATE suggestions SET status='rejected' WHERE id=?", (sug_id,))
            await db.commit()

        await call.message.answer(f"❌ Предложение #{sug_id} отклонено.")

    elif call.data == "admin_logout":
        if call.from_user.id in admin_users:
            admin_users.remove(call.from_user.id)
            await call.message.answer("🚪 Ты вышел из админ-режима.")
        await call.message.answer("Главное меню:", reply_markup=get_main_menu(False))

    elif call.data == "back_to_menu":
        await call.message.answer("Главное меню:", reply_markup=get_main_menu(is_admin(call.from_user.id)))

# ==================== Одобрение фильма ====================
@dp.message(ApproveStates.waiting_final_rating)
async def get_final_rating(message: types.Message, state: FSMContext):
    try:
        rating = float(message.text.replace(',', '.'))
        await state.update_data(admin_rating=rating)
    except ValueError:
        await message.answer("Введи число, например 8.7")
        return
    await state.set_state(ApproveStates.waiting_final_description)
    await message.answer("Твой комментарий к фильму (или «пропустить»):")

# ==================== Одобрение фильма с уведомлением пользователя ====================
@dp.message(ApproveStates.waiting_final_rating)
async def get_final_rating(message: types.Message, state: FSMContext):
    try:
        rating = float(message.text.replace(',', '.'))
        await state.update_data(admin_rating=rating)
    except ValueError:
        await message.answer("Введи число, например 8.7")
        return
    await state.set_state(ApproveStates.waiting_final_description)
    await message.answer("Твой комментарий к фильму (или «пропустить»):")

@dp.message(ApproveStates.waiting_final_description)
async def save_approved_movie(message: types.Message, state: FSMContext):
    data = await state.get_data()
    desc = None if message.text.lower() in ['пропустить', '-', 'нет', 'skip'] else message.text.strip()
    sug_id = data.get('approve_id')
    admin_rating = data.get('admin_rating')

    async with aiosqlite.connect('movies.db') as db:
        async with db.execute(
            "SELECT title, category, poster, description, suggested_by, rating FROM suggestions WHERE id = ?", 
            (sug_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            title, category, poster, old_desc, added_by, user_rating = row
            final_desc = desc or old_desc

            # Проверка на дубликат
            async with db.execute("SELECT id FROM movies WHERE title = ? COLLATE NOCASE", (title,)) as cursor:
                if await cursor.fetchone():
                    await message.answer(f"❌ Фильм «{title}» уже есть в коллекции!")
                    await state.clear()
                    return

            # Добавляем фильм
            await db.execute('''
                INSERT INTO movies 
                (title, category, rating, poster, description, added_by, user_rating, admin_rating)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, category, admin_rating or user_rating, poster, final_desc, added_by, user_rating, admin_rating))

            await db.execute("UPDATE suggestions SET status = 'approved' WHERE id = ?", (sug_id,))
            await db.commit()

            # Уведомляем пользователя, что фильм принят
            await bot.send_message(
                added_by,
                f"✅ Ваш фильм «{title}» был принят администратором!\n"
                f"Оценка администратора: {admin_rating if admin_rating else 'не указана'}"
            )

    await state.clear()
    await message.answer(
        f"✅ Фильм «{title}» успешно добавлен!\n"
        f"Оценка пользователя: {user_rating}\n"
        f"Твоя оценка: {admin_rating if admin_rating else 'не указана'}"
    )
    await message.answer("Главное меню:", reply_markup=get_main_menu(True))

# ==================== Просмотр фильмов ====================
@dp.message(F.text.in_({"📋 Посмотреть фильмы", "📋 Мои фильмы"}))
async def show_movies(message: types.Message):
    async with aiosqlite.connect('movies.db') as db:
        async with db.execute("""
            SELECT title, category, rating, description, user_rating, admin_rating 
            FROM movies ORDER BY category, title
        """) as cursor:
            films = await cursor.fetchall()

    if not films:
        await message.answer("Пока нет фильмов в коллекции.")
        await message.answer("Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))
        return

    text = "📚 Коллекция фильмов:\n"
    current_cat = None
    for title, cat, avg_rating, desc, user_r, admin_r in films:
        if cat != current_cat:
            text += f"\n🔹 {cat}:\n"
            current_cat = cat
        text += f"• {title} — {avg_rating:.1f}"
        if user_r is not None:
            text += f" (польз: {user_r:.1f})"
        if admin_r is not None:
            text += f" | админ: {admin_r:.1f}"
        text += "\n"
        if desc:
            text += f"   ↳ {desc}\n"

    await message.answer(text)
    await message.answer("Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))

# ==================== Случайный фильм ====================
@dp.message(F.text == "🎲 Случайный фильм")
async def random_movie(message: types.Message):
    async with aiosqlite.connect('movies.db') as db:
        async with db.execute("""
            SELECT title, category, rating, description, poster, user_rating, admin_rating 
            FROM movies ORDER BY RANDOM() LIMIT 1
        """) as cursor:
            film = await cursor.fetchone()

    if not film:
        await message.answer("Коллекция пока пуста.")
        await message.answer("Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))
        return

    title, category, rating, desc, poster, user_r, admin_r = film

    text = f"🎲 Случайный фильм:\n\n📌 {title}\n🔹 Категория: {category}\n⭐ Оценка: {rating:.1f}"
    if user_r:
        text += f" (польз: {user_r:.1f})"
    if admin_r:
        text += f" | админ: {admin_r:.1f}"
    if desc:
        text += f"\n\n💬 {desc}"

    if poster and poster.startswith("http"):
        await bot.send_photo(message.chat.id, poster, caption=text)
    else:
        await message.answer(text)

    await message.answer("Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))

    
# ==================== УДАЛЕНИЕ ФИЛЬМОВ ====================

@dp.message(F.text == "🗑 Удалить фильм")
async def start_delete(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Доступно только админу.")
        return

    await state.set_state(DeleteStates.waiting_search_query)
    await message.answer(
        "Введите название фильма или напишите «все» для полного списка:\n"
        "Напишите «отмена», чтобы выйти."
    )


@dp.message(DeleteStates.waiting_search_query)
async def process_search(message: types.Message, state: FSMContext):
    if message.text.lower() in ['отмена', 'назад', 'выход']:
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_main_menu(True))
        return

    query = message.text.strip().lower()

    async with aiosqlite.connect('movies.db') as db:
        if query == "все":
            sql = "SELECT id, title, category, rating FROM movies ORDER BY category, title"
            params = ()
        else:
            sql = "SELECT id, title, category, rating FROM movies WHERE LOWER(title) LIKE ? ORDER BY title"
            params = (f"%{query}%",)

        async with db.execute(sql, params) as cursor:
            films = await cursor.fetchall()

    if not films:
        await message.answer("Ничего не найдено. Попробуйте другое название или «отмена».")
        return

    builder = InlineKeyboardBuilder()
    for fid, title, cat, rating in films[:25]:
        builder.row(InlineKeyboardButton(
            text=f"❌ {title} ({cat}) — {rating}",
            callback_data=f"delete_film:{fid}"
        ))

    await message.answer(
        f"Найдено {len(films)} фильмов.\nНажмите на фильм для удаления:",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.startswith("delete_film:"))
async def confirm_delete(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    film_id = int(callback.data.split(":")[1])

    async with aiosqlite.connect('movies.db') as db:
        async with db.execute("SELECT title FROM movies WHERE id = ?", (film_id,)) as cur:
            row = await cur.fetchone()

    if not row:
        await callback.message.edit_text("Фильм уже удалён ранее.")
        await state.clear()
        return

    title = row[0]

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_yes:{film_id}"),
        InlineKeyboardButton(text="❌ Нет, отменить", callback_data="delete_no")
    ]])

    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить этот фильм?\n\n**{title}**",
        reply_markup=confirm_kb,
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("delete_yes:"))
async def execute_delete(callback: types.CallbackQuery):
    await callback.answer()
    film_id = int(callback.data.split(":")[1])

    async with aiosqlite.connect('movies.db') as db:
        async with db.execute("SELECT title FROM movies WHERE id = ?", (film_id,)) as cur:
            row = await cur.fetchone()
            title = row[0] if row else "Неизвестный фильм"

        await db.execute("DELETE FROM movies WHERE id = ?", (film_id,))
        await db.commit()

    await callback.message.edit_text(f"✅ Фильм «{title}» успешно удалён.")


@dp.callback_query(F.data == "delete_no")
async def cancel_delete(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("❌ Удаление отменено.")
    await state.clear()


# ==================== Предложить фильм ====================
@dp.message(F.text == "📽 Предложить фильм")
async def start_suggestion(message: types.Message, state: FSMContext):
    await state.set_state(SuggestionStates.waiting_title)
    await message.answer("Напиши **название фильма**, который хочешь предложить:")

@dp.message(SuggestionStates.waiting_title)
async def get_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    categories = ['Экшен', 'Легендарные', 'Детективы', 'Триллер', 'Одноразовые', 'Драма', 'Комедия', 'Ужасы', 'Мультфильмы', 'Другое']
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=c)] for c in categories],
        resize_keyboard=True, one_time_keyboard=True
    )
    await state.set_state(SuggestionStates.waiting_category)
    await message.answer("Выбери категорию или напиши свою:", reply_markup=kb)

@dp.message(SuggestionStates.waiting_category)
async def get_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text.strip())
    await state.set_state(SuggestionStates.waiting_rating)
    await message.answer("Твоя оценка фильма (дробная, например 8.7):")

@dp.message(SuggestionStates.waiting_rating)
async def get_rating(message: types.Message, state: FSMContext):
    try:
        rating = float(message.text.replace(',', '.'))
        if not (0 <= rating <= 10):
            await message.answer("Оценка должна быть в диапазоне от 0 до 10!")
        return
        await state.update_data(rating=rating)
    except ValueError:
        await message.answer("Пожалуйста, введи число. Например: 8.5")
        return
    await state.set_state(SuggestionStates.waiting_poster)
    await message.answer("Ссылка на постер (опционально).\nНапиши «пропустить», если нет.") #333333333333333333333333333333333333333333333333333333333333333333333

@dp.message(SuggestionStates.waiting_poster)
async def get_poster(message: types.Message, state: FSMContext):
    poster = None if message.text.lower() in ['пропустить', '-', 'нет', 'skip'] else message.text.strip()
    await state.update_data(poster=poster)
    await state.set_state(SuggestionStates.waiting_description)
    await message.answer("Твой комментарий / описание (опционально).\nНапиши «пропустить», если не нужно.")

@dp.message(SuggestionStates.waiting_description)
async def save_suggestion(message: types.Message, state: FSMContext):
    data = await state.get_data()
    desc = None if message.text.lower() in ['пропустить', '-', 'нет', 'skip'] else message.text.strip()

    async with aiosqlite.connect('movies.db') as db:
        await db.execute('''
            INSERT INTO suggestions (title, category, rating, poster, description, suggested_by)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data['title'], data['category'], data['rating'], data['poster'], desc, message.from_user.id))
        await db.commit()

    await state.clear()
    await message.answer("✅ Предложение отправлено на модерацию!")
    await message.answer("Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))

# ==================== Админ-панель ====================
@dp.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return

    async with aiosqlite.connect('movies.db') as db:
        async with db.execute(
            "SELECT id, title, category, rating, suggested_by FROM suggestions WHERE status = 'pending'"
        ) as cursor:
            suggestions = await cursor.fetchall()

    if not suggestions:
        await message.answer("✅ Нет новых предложений на модерацию.")
    else:
        for sug in suggestions:
            sug_id, title, cat, rating, user_id = sug
            text = f"📌 Предложение #{sug_id}\nНазвание: {title}\nКатегория: {cat}\nОценка: {rating}\nОт: {user_id}"

            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{sug_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{sug_id}")
            ]])
            await message.answer(text, reply_markup=markup)

    # Кнопки управления админ-режимом
    control = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚪 Выйти из админа", callback_data="admin_logout"),
        InlineKeyboardButton(text="↩ Вернуться в меню", callback_data="back_to_menu")
    ]])
    await message.answer("⚙️ Управление админ-режимом:", reply_markup=control)


# ==================== Реакция на незнакомые команды ====================
@dp.message()
async def unknown_command(message: types.Message):
    await message.answer("Я тебя не понимаю. Нажми /start, чтобы открыть меню.")



# ==================== Запуск ====================
async def main():
    await init_db()
    print("✅ Бот на aiogram успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())