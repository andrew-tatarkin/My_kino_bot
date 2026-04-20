import os
import logging
from dotenv import load_dotenv
import telebot
from telebot import types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage

load_dotenv()

TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("❌ TOKEN не найден!")

bot = telebot.TeleBot(TOKEN)
storage = StateMemoryStorage()
bot.add_custom_filter(telebot.custom_filters.StateFilter(bot))

logging.basicConfig(level=logging.INFO)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '0000')
admin_users = set()

# ==================== База данных ====================
def init_db():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('''
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
    c.execute('''
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
    conn.commit()
    conn.close()

init_db()

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
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add('📽 Предложить фильм', '🎲 Случайный фильм')
    markup.add('📋 Посмотреть фильмы')
    if is_admin:
        markup.add('🔧 Админ-панель', '🗑 Удалить фильм')
    return markup

def is_admin(user_id):
    return user_id in admin_users

# ==================== Старт ====================
@bot.message_handler(commands=['start'])
def start(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    is_adm = is_admin(message.from_user.id)
    
    bot.send_message(message.chat.id, 
        "👋 Добро пожаловать в кино-трекер!\n\n"
        f"Чтобы стать админом — введи пароль: `{ADMIN_PASSWORD}`", 
        parse_mode='Markdown')
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=get_main_menu(is_adm))

print("✅ Бот инициализирован успешно")

# ==================== Запуск  ====================
if __name__ == "__main__":
    bot.remove_webhook()
    print("🚀 Бот запущен и ожидает сообщений...")
    bot.infinity_polling(none_stop=True, interval=1, timeout=30)