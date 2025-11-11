import sqlite3
import logging
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Создаем папку для данных, если она не существует.
# На Railway этот путь будет указывать на подключенный том (Volume).
# Используем абсолютный путь для надежности на Railway
DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "token_usage.db")

def init_db():
    """
    Инициализирует базу данных.
    Создает таблицу 'usage' и добавляет колонку 'model_name', если их нет.
    """
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
                    ai_response TEXT NOT NULL,
                    model_name TEXT NOT NULL
                )
            """)

            # --- Проверка и добавление колонки для обратной совместимости ---
            # Получаем информацию о столбцах в таблице
            cursor.execute("PRAGMA table_info(usage)")
            columns = [column[1] for column in cursor.fetchall()]
            # Если колонки 'model_name' нет, добавляем её
            if 'model_name' not in columns:
                logger.info("Обновление схемы БД: добавляется колонка 'model_name'...")
                # Добавляем с дефолтным значением, чтобы не было ошибок на старых данных
                cursor.execute("ALTER TABLE usage ADD COLUMN model_name TEXT NOT NULL DEFAULT 'unknown'")
                logger.info("Колонка 'model_name' успешно добавлена.")

            conn.commit()
        logger.info(f"База данных '{DB_NAME}' успешно инициализирована.")
    except sqlite3.Error as e:
        logger.critical(f"Ошибка при инициализации базы данных SQLite: {e}")
        raise

def log_usage_to_db(username: str, user_message: str, usage_data, ai_response: str, lore_chunks_count: int = 0, model_name: str = "unknown"):
    """Записывает информацию о расходе токенов в базу данных SQLite."""
    if not usage_data:
        return

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO usage (timestamp, username, lore_chunks_sent, prompt_tokens, completion_tokens, total_tokens, user_message, ai_response, model_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    username,
                    lore_chunks_count,
                    usage_data.prompt_tokens,
                    usage_data.completion_tokens,
                    usage_data.total_tokens,
                    user_message,
                    ai_response,
                    model_name
                )
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка при записи в базу данных SQLite: {e}")

def get_stats_for_date(date_str: str) -> list[dict]:
    """
    Собирает статистику использования моделей за определенную дату.
    Возвращает список словарей, отсортированный по количеству запросов.
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени
            cursor = conn.cursor()
            cursor.execute("""
                SELECT model_name, COUNT(*) as requests, SUM(total_tokens) as total_tokens
                FROM usage
                WHERE date(timestamp) = ?
                GROUP BY model_name
                ORDER BY requests DESC
            """, (date_str,))
            stats = [dict(row) for row in cursor.fetchall()]
            return stats
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении статистики из БД: {e}")
        return []

def get_top_users_for_date(date_str: str, limit: int = 20) -> list[dict]:
    """
    Возвращает топ пользователей по количеству запросов за указанную дату.
    Каждый элемент списка — словарь: {'username': ..., 'requests': ..., 'total_tokens': ...}
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, COUNT(*) as requests, SUM(total_tokens) as total_tokens
                FROM usage
                WHERE date(timestamp) = ?
                GROUP BY username
                ORDER BY requests DESC, total_tokens DESC
                LIMIT ?
            """, (date_str, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении топа пользователей из БД: {e}")
        return []

def get_overall_user_stats_for_date(date_str: str) -> dict:
    """
    Собирает общую статистику по пользователям за указанную дату.
    Возвращает словарь с общим числом запросов, токенов и количеством уникальных пользователей.
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            # Считаем общее количество запросов и токенов
            cursor.execute("""
                SELECT COUNT(*), SUM(total_tokens)
                FROM usage
                WHERE date(timestamp) = ?
            """, (date_str,))
            total_requests, total_tokens = cursor.fetchone()

            # Считаем количество уникальных пользователей
            cursor.execute("""
                SELECT COUNT(DISTINCT username)
                FROM usage
                WHERE date(timestamp) = ?
            """, (date_str,))
            unique_users_count = cursor.fetchone()[0]

            return {"total_requests": total_requests or 0, "total_tokens": total_tokens or 0, "unique_users_count": unique_users_count or 0}
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении общей статистики пользователей из БД: {e}")
        return {"total_requests": 0, "total_tokens": 0, "unique_users_count": 0}
