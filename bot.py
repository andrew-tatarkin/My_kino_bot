import telebot
import sqlite3
import logging
import os
from dotenv import load_dotenv
from telebot import types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
from telebot import custom_filters

# ==================== ТОКЕН ====================
load_dotenv()

TOKEN = os.getenv('TOKEN')

if not TOKEN:
    raise ValueError("❌ TOKEN не найден!")

logging.basicConfig(level=logging.INFO)

state_storage = StateMemoryStorage()
bot = telebot.TeleBot(TOKEN, state_storage=state_storage)
bot.add_custom_filter(custom_filters.StateFilter(bot))


# ==================== СОСТОЯНИЯ (FSM) ====================
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

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
ADMIN_PASSWORD = "0000"
admin_users = set()   # сюда буду добавлять user_id тех, кто ввёл правильный пароль

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    
       # Таблица утверждённых фильмов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            rating REAL,                    -- средняя/финальная оценка (для совместимости)
            poster TEXT,
            description TEXT,
            added_by INTEGER,
            added_date TEXT DEFAULT CURRENT_TIMESTAMP,
            user_rating REAL,               -- оценка от пользователя
            admin_rating REAL               -- оценка как админа
        )
    ''')
    
    # Таблица предложений (ожидают одобрения)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT,
            rating REAL,                    -- оценка того, кто предложил
            poster TEXT,
            description TEXT,
            suggested_by INTEGER NOT NULL,  -- user_id предложившего
            suggested_date TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'   -- pending / approved / rejected
        )
    ''')
    
    conn.commit()
    conn.close()

# Инициализируем базу при запуске
init_db()


# ==================== ГЛАВНОЕ МЕНЮ ====================
def get_main_menu(is_admin=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add('📽 Предложить фильм', '🎲 Случайный фильм')
    markup.add('📋 Посмотреть фильмы')
    
    if is_admin:
        markup.add('🔧 Админ-панель', '🗑 Удалить фильм')
    return markup

def is_admin(user_id):
    return user_id in admin_users

# ==================== СТАРТ ====================
@bot.message_handler(commands=['start'])
def start(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    is_adm = is_admin(message.from_user.id)
    
    bot.send_message(message.chat.id, 
        "👋 Добро пожаловать в кино-трекер!\n\n"
        "По умолчанию ты в режиме пользователя.\n"
        f"Чтобы стать админом — введи пароль: `XXXX` ", 
        parse_mode='Markdown')
    
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=get_main_menu(is_adm))


# ==================== ПАРОЛЬ ДЛЯ АДМИНА ====================
@bot.message_handler(func=lambda m: m.text == ADMIN_PASSWORD and not is_admin(m.from_user.id))
def login_admin(message):
    admin_users.add(message.from_user.id)
    bot.send_message(message.chat.id, "✅ Ты теперь админ! Доступны дополнительные функции.")
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(True))


# ==================== ПРЕДЛОЖЕНИЕ ФИЛЬМА ====================
@bot.message_handler(func=lambda m: m.text == '📽 Предложить фильм')
def start_suggestion(message):
    bot.set_state(message.from_user.id, SuggestionStates.waiting_title, message.chat.id)
    bot.send_message(message.chat.id, "Напиши **название фильма**, который хочешь предложить:")

@bot.message_handler(state=SuggestionStates.waiting_title)
def get_title(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['title'] = message.text.strip()
    
    # Кнопки для категорий
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    categories = ['Экшен', 'Легендарные', 'Детективы', 'Триллер', 'Одноразовые', 'Драма', 'Комедия', 'Ужасы', 'Другое']
    markup.add(*categories)
    
    bot.set_state(message.from_user.id, SuggestionStates.waiting_category, message.chat.id)
    bot.send_message(message.chat.id, "Выбери категорию или напиши свою:", reply_markup=markup)

@bot.message_handler(state=SuggestionStates.waiting_category)
def get_category(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['category'] = message.text.strip()
    
    bot.set_state(message.from_user.id, SuggestionStates.waiting_rating, message.chat.id)
    bot.send_message(message.chat.id, "Твоя оценка фильма (дробная, например 8.7 или 9.0):")

@bot.message_handler(state=SuggestionStates.waiting_rating)
def get_rating(message):
    try:
        rating = float(message.text.replace(',', '.'))
        with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
            data['rating'] = rating
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введи число (можно с точкой или запятой). Например: 8.5")
        return
    
    bot.set_state(message.from_user.id, SuggestionStates.waiting_poster, message.chat.id)
    bot.send_message(message.chat.id, 
        "Ссылка на постер (опционально).\n"
        "Можешь пропустить — просто напиши «пропустить» или «-»")

@bot.message_handler(state=SuggestionStates.waiting_poster)
def get_poster(message):
    poster = message.text.strip()
    if poster.lower() in ['пропустить', '-', 'нет', 'н', 'skip']:
        poster = None
    
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['poster'] = poster
    
    bot.set_state(message.from_user.id, SuggestionStates.waiting_description, message.chat.id)
    bot.send_message(message.chat.id, 
        "Твой комментарий / описание фильма (опционально).\n"
        "Можешь пропустить — напиши «пропустить»")

@bot.message_handler(state=SuggestionStates.waiting_description)
def save_suggestion(message):
    description = message.text.strip()
    if description.lower() in ['пропустить', '-', 'нет', 'н', 'skip']:
        description = None

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        conn = sqlite3.connect('movies.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO suggestions (title, category, rating, poster, description, suggested_by)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data['title'], data['category'], data['rating'], data['poster'], description, message.from_user.id))
        conn.commit()
        conn.close()

    bot.delete_state(message.from_user.id, message.chat.id)
    bot.send_message(message.chat.id, "✅ Предложение отправлено на модерацию!\nСпасибо!")
    
    is_adm = message.from_user.id in admin_users
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_adm))


# ==================== АДМИН-ПАНЕЛЬ (с красивыми Inline-кнопками) ====================
@bot.message_handler(func=lambda m: m.text == '🔧 Админ-панель' and is_admin(m.from_user.id))
def admin_panel(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT id, title, category, rating, suggested_by FROM suggestions WHERE status = 'pending'")
    suggestions = c.fetchall()
    conn.close()

    if suggestions:
        for sug in suggestions:
            sug_id, title, cat, rating, user_id = sug
            text = f"📌 Предложение #{sug_id}\n" \
                   f"Название: {title}\n" \
                   f"Категория: {cat}\n" \
                   f"Оценка пользователя: {rating}\n" \
                   f"От: {user_id}"

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{sug_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{sug_id}")
            )
            bot.send_message(message.chat.id, text, reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "✅ Нет новых предложений на модерацию.")

    # Красивые Inline-кнопки управления админ-режимом
    control_markup = types.InlineKeyboardMarkup(row_width=2)
    control_markup.add(
        types.InlineKeyboardButton("🚪 Выйти из админа", callback_data="admin_logout"),
        types.InlineKeyboardButton("↩ Вернуться в меню", callback_data="back_to_menu")
    )
    
    bot.send_message(message.chat.id, 
        "⚙️ Управление админ-режимом:", 
        reply_markup=control_markup)

    # ==================== ВЫХОД ИЗ АДМИН-РЕЖИМА ====================
@bot.message_handler(func=lambda m: m.text == '🚪 Выйти из админа')
def logout_admin(message):
    if message.from_user.id in admin_users:
        admin_users.remove(message.from_user.id)
        bot.send_message(message.chat.id, "🚪 Ты вышел из админ-режима.\nТеперь ты обычный пользователь.")
    else:
        bot.send_message(message.chat.id, "Ты и так не в админ-режиме.")
    
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(False))


# ==================== ВЕРНУТЬСЯ В ГЛАВНОЕ МЕНЮ ====================
@bot.message_handler(func=lambda m: m.text == '↩ Вернуться в главное меню')
def back_to_menu(message):
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))



        # ==================== ПОСМОТРЕТЬ ФИЛЬМЫ (доступно всем) ====================
@bot.message_handler(func=lambda m: m.text in ['📋 Посмотреть фильмы', '📋 Мои фильмы'])
def show_movies(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("""SELECT title, category, rating, description, user_rating, admin_rating 
                 FROM movies ORDER BY category, title""")
    films = c.fetchall()
    conn.close()

    if not films:
        bot.send_message(message.chat.id, "Пока нет фильмов в коллекции.")
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))
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

    bot.send_message(message.chat.id, text)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))


    # ==================== УДАЛЕНИЕ ФИЛЬМА ====================



@bot.message_handler(func=lambda m: m.text == '🗑 Удалить фильм' and is_admin(m.from_user.id))
def start_delete(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    bot.set_state(message.from_user.id, DeleteStates.waiting_delete_confirm, message.chat.id)
    
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT id, title, category, rating FROM movies ORDER BY category, title")
    films = c.fetchall()
    conn.close()

    if not films:
        bot.send_message(message.chat.id, "Коллекция пуста, удалять нечего.")
        bot.delete_state(message.from_user.id, message.chat.id)
        return

    text = "Выбери фильм для удаления (отправь номер):\n\n"
    for fid, title, cat, rating in films:
        text += f"{fid}. {title} ({cat}) — {rating}\n"

    bot.send_message(message.chat.id, text)

@bot.message_handler(state=DeleteStates.waiting_delete_confirm)
def confirm_delete(message):
    try:
        film_id = int(message.text.strip())
        conn = sqlite3.connect('movies.db')
        c = conn.cursor()
        c.execute("DELETE FROM movies WHERE id = ?", (film_id,))
        deleted = c.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            bot.send_message(message.chat.id, f"✅ Фильм с ID {film_id} успешно удалён.")
        else:
            bot.send_message(message.chat.id, "❌ Фильм с таким ID не найден.")
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введи число (ID фильма).")

    bot.delete_state(message.from_user.id, message.chat.id)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(True))

    # ==================== CALLBACK (одобрить / отклонить) ====================
        # Обработка нажатий на кнопки
# ==================== ОБРАБОТКА INLINE-КНОПОК ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    bot.answer_callback_query(call.id)

    if call.data.startswith("approve_"):
        sug_id = int(call.data.split("_")[1])
        bot.set_state(call.from_user.id, ApproveStates.waiting_final_rating, call.message.chat.id)
        with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
            data['approve_id'] = sug_id
        bot.send_message(call.message.chat.id, f"Одобряем предложение #{sug_id}.\nТвоя финальная оценка (дробная):")

    elif call.data.startswith("reject_"):
        sug_id = int(call.data.split("_")[1])
        conn = sqlite3.connect('movies.db')
        c = conn.cursor()
        c.execute("UPDATE suggestions SET status='rejected' WHERE id=?", (sug_id,))
        conn.commit()
        conn.close()
        bot.send_message(call.message.chat.id, f"❌ Предложение #{sug_id} отклонено.")

    elif call.data == "admin_logout":
        if call.from_user.id in admin_users:
            admin_users.remove(call.from_user.id)
            bot.send_message(call.message.chat.id, "🚪 Ты вышел из админ-режима.\nТеперь ты обычный пользователь.")
        bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=get_main_menu(False))

    elif call.data == "back_to_menu":
        bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(call.from_user.id)))

# ==================== ОДОБРЕНИЕ: оценка админа (теперь отдельно) ====================
@bot.message_handler(state=ApproveStates.waiting_final_rating)
def get_final_rating(message):
    try:
        admin_rating = float(message.text.replace(',', '.'))
    except ValueError:
        admin_rating = None  # можно пропустить

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['admin_rating'] = admin_rating
        data['final_rating'] = admin_rating  # для совместимости со старым кодом
    
    bot.set_state(message.from_user.id, ApproveStates.waiting_final_description, message.chat.id)
    bot.send_message(message.chat.id, "Твой комментарий (или «пропустить»):")


@bot.message_handler(state=ApproveStates.waiting_final_description)
def save_approved_movie(message):
    desc = None if message.text.lower() in ['пропустить', '-', 'нет', 'skip'] else message.text.strip()
    
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        sug_id = data.get('approve_id')
        admin_rating = data.get('admin_rating')

        conn = sqlite3.connect('movies.db')
        c = conn.cursor()

        # Получаем данные предложения
        c.execute("""SELECT title, category, poster, description, suggested_by, rating 
                     FROM suggestions WHERE id = ?""", (sug_id,))
        row = c.fetchone()
        
        if not row:
            bot.send_message(message.chat.id, "Ошибка: предложение не найдено.")
            conn.close()
            bot.delete_state(message.from_user.id, message.chat.id)
            return

        title, category, poster, old_desc, added_by, user_rating = row
        final_desc = desc or old_desc

        # Проверка на дубликат по названию
        c.execute("SELECT id FROM movies WHERE title = ? COLLATE NOCASE", (title,))
        if c.fetchone():
            bot.send_message(message.chat.id, 
                f"❌ Фильм «{title}» уже есть в коллекции!\n"
                "Повторное добавление запрещено.")
            conn.close()
            bot.delete_state(message.from_user.id, message.chat.id)
            return

        # Добавляем фильм
        c.execute('''INSERT INTO movies 
                     (title, category, rating, poster, description, added_by, user_rating, admin_rating)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (title, category, admin_rating or user_rating, poster, final_desc, 
                   added_by, user_rating, admin_rating))
        
        c.execute("UPDATE suggestions SET status = 'approved' WHERE id = ?", (sug_id,))
        conn.commit()
        conn.close()

    bot.delete_state(message.from_user.id, message.chat.id)
    bot.send_message(message.chat.id, 
        f"✅ Фильм «{title}» успешно добавлен!\n"
        f"Оценка пользователя: {user_rating}\n"
        f"Твоя оценка: {admin_rating if admin_rating else 'не указана'}")
    
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(True))

# ==================== МОИ ФИЛЬМЫ ====================
@bot.message_handler(func=lambda m: m.text in ['📋 Посмотреть фильмы', '📋 Мои фильмы'])
def show_movies(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("""SELECT title, category, rating, description, user_rating, admin_rating 
                 FROM movies ORDER BY category, title""")
    films = c.fetchall()
    conn.close()

    if not films:
        bot.send_message(message.chat.id, "Пока нет фильмов в коллекции.")
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))
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

    bot.send_message(message.chat.id, text)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))


    # ==================== СЛУЧАЙНЫЙ ФИЛЬМ ====================
@bot.message_handler(func=lambda m: m.text == '🎲 Случайный фильм')
def random_movie(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("""SELECT title, category, rating, description, poster, user_rating, admin_rating 
                 FROM movies ORDER BY RANDOM() LIMIT 1""")
    film = c.fetchone()
    conn.close()

    if not film:
        bot.send_message(message.chat.id, "Коллекция пока пуста. Добавь хотя бы один фильм!")
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))
        return

    title, category, rating, desc, poster, user_r, admin_r = film

    text = f"🎲 Случайный фильм:\n\n" \
           f"📌 {title}\n" \
           f"🔹 Категория: {category}\n" \
           f"⭐ Оценка: {rating:.1f}"
    
    if user_r:
        text += f" (польз: {user_r:.1f})"
    if admin_r:
        text += f" | админ: {admin_r:.1f}"
    
    if desc:
        text += f"\n\n💬 {desc}"

    if poster and poster.startswith("http"):
        bot.send_photo(message.chat.id, poster, caption=text)
    else:
        bot.send_message(message.chat.id, text)

    bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(is_admin(message.from_user.id)))


    # ==================== ВЫХОД ИЗ АДМИН-РЕЖИМА ====================
    @bot.message_handler(func=lambda m: m.text == '🚪 Выйти из админ-режима')
    def logout_admin(message):
        if message.from_user.id in admin_users:
            admin_users.remove(message.from_user.id)
            bot.send_message(message.chat.id, "🚪 Ты успешно вышел из админ-режима.\nТеперь ты обычный пользователь.")
        else:
            bot.send_message(message.chat.id, "Ты и так не в админ-режиме.")
        
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(False))


    @bot.message_handler(commands=['exit', 'logout'])
    def exit_command(message):
        if message.from_user.id in admin_users:
            admin_users.remove(message.from_user.id)
            bot.send_message(message.chat.id, "🚪 Ты успешно вышел из админ-режима.")
        else:
            bot.send_message(message.chat.id, "Ты и так не в админ-режиме.")
        
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_menu(False))

@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    bot.send_message(message.chat.id, "Я тебя не понимаю. Нажми /start, чтобы открыть меню.")


print("Бот запущен — Этап 6.5 (Админ Панель)")
bot.infinity_polling(none_stop=True, interval=1)