import sqlite3
import logging
from datetime import datetime, timedelta
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Создаем папку для данных, если она не существует.
# На Railway этот путь будет указывать на подключенный том (Volume).
# Для локальной разработки создаем папку 'data' в корне проекта.
IS_RAILWAY = 'RAILWAY_STATIC_URL' in os.environ
DATA_DIR = "/app/data" if IS_RAILWAY else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Основная БД приложения теперь ponchik_db (SQLite файл)
DB_NAME = os.path.join(DATA_DIR, "ponchik_db.db")

def init_db():
    """
    Инициализирует базу данных.
    Создает таблицы 'usage' (для совместимости) и 'users' (новая схема).
    Сохраняет обратную совместимость, добавляя колонку 'model_name' в usage при необходимости.
    """
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            # Таблица usage (сохраняем для совместимости с предыдущей логикой)
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

            # Новая таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nickname TEXT,
                    tg_username TEXT,
                    tg_id INTEGER UNIQUE,
                    activation_date TEXT,
                    total_requests INTEGER DEFAULT 0
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
        # После инициализации выполняем очистку старых записей (по умолчанию сохраняем до и включая 'позавчера')
        try:
            purge_old_usage()
        except Exception as e:
            logger.error(f"Ошибка при запуске очистки старых записей: {e}")
    except sqlite3.Error as e:
        logger.critical(f"Ошибка при инициализации базы данных SQLite: {e}")
        raise

def log_usage_to_db(tg_id: int, username: str, user_message: str, usage_data, ai_response: str, lore_chunks_count: int = 0, model_name: str = "unknown"):
    """
    Записывает информацию о расходе токенов в таблицу 'usage'
    и одновременно увеличивает счетчик 'total_requests' в таблице 'users'.
    """
    if not usage_data:
        return

    # --- Шаг 1: Логирование в таблицу 'usage' ---
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

    # --- Шаг 2: Инкремент общего счетчика запросов ---
    increment_user_requests(tg_id=tg_id)


def create_or_update_user(nickname: Optional[str], tg_username: Optional[str], tg_id: Optional[int], activation_date: Optional[str] = None):
    """Создаёт пользователя если не существует или обновляет nickname/tg_username. Возвращает dict пользователя."""
    if tg_id is None:
        return None

    if activation_date is None:
        activation_date = datetime.now().strftime("%Y-%m-%d")

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            # Пытаемся вставить нового пользователя, если tg_id уникален
            cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
            row = cursor.fetchone()
            if row:
                # Обновляем данные
                cursor.execute(
                    "UPDATE users SET nickname = ?, tg_username = ? WHERE tg_id = ?",
                    (nickname, tg_username, tg_id)
                )
            else:
                cursor.execute(
                    "INSERT INTO users (nickname, tg_username, tg_id, activation_date, total_requests) VALUES (?, ?, ?, ?, ?)",
                    (nickname, tg_username, tg_id, activation_date, 0)
                )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            r = cursor.fetchone()
            if r:
                cols = [d[0] for d in cursor.description]
                return dict(zip(cols, r))
    except sqlite3.Error as e:
        logger.error(f"Ошибка при создании/обновлении пользователя: {e}")
    return None


def get_user_by_tg_id(tg_id: int) -> Optional[dict]:
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(f"Ошибка при чтении пользователя: {e}")
        return None


def increment_user_requests(tg_id: int, delta: int = 1):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET total_requests = total_requests + ? WHERE tg_id = ?", (delta, tg_id))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка при обновлении счетчика запросов пользователя: {e}")


def get_all_users() -> list[dict]:
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT nickname, tg_username, tg_id, activation_date, total_requests FROM users ORDER BY total_requests DESC")
            return [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}")
        return []


def purge_old_usage(retention_days: int = 2) -> int:
    """
    Удаляет записи из таблицы `usage`, у которых дата(timestamp) строго меньше чем
    (сегодня - retention_days). По умолчанию retention_days=2 — это означает,
    что сохраняются записи за сегодня, вчера и позавчера; всё, что старше позавчера,
    будет удалено.

    Возвращает количество удалённых записей.
    """
    try:
        cutoff_date = (datetime.now().date() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            # Удаляем строки с датой меньше cutoff_date
            cursor.execute("DELETE FROM usage WHERE date(timestamp) < ?", (cutoff_date,))
            deleted = cursor.rowcount if cursor.rowcount is not None else 0
            conn.commit()
        logger.info(f"Очистка БД: удалено {deleted} записей из 'usage' старше чем {cutoff_date}.")
        return deleted
    except sqlite3.Error as e:
        logger.error(f"Ошибка при очистке старых записей usage: {e}")
        return 0

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
