import sqlite3
import logging
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Создаем папку для данных, если она не существует.
# На Railway этот путь будет указывать на подключенный том (Volume).
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "token_usage.db")

def init_db():
    """Инициализирует базу данных и создает таблицу, если она не существует."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    username TEXT NOT NULL,
                    lore_chunks_sent INTEGER NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    user_message TEXT NOT NULL,
                    ai_response TEXT NOT NULL
                )
            """)
            conn.commit()
        logger.info(f"База данных '{DB_NAME}' успешно инициализирована.")
    except sqlite3.Error as e:
        logger.critical(f"Ошибка при инициализации базы данных SQLite: {e}")
        raise

def log_usage_to_db(username: str, user_message: str, usage_data, ai_response: str, lore_chunks_count: int = 0):
    """Записывает информацию о расходе токенов в базу данных SQLite."""
    if not usage_data:
        return

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO usage (timestamp, username, lore_chunks_sent, prompt_tokens, completion_tokens, total_tokens, user_message, ai_response) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, lore_chunks_count, usage_data.prompt_tokens, usage_data.completion_tokens, usage_data.total_tokens, user_message, ai_response))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка при записи в базу данных SQLite: {e}")