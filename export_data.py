import sqlite3
import logging
import os

# --- НАСТРОЙКИ ---
# Путь к локальной базе данных, из которой нужно экспортировать данные
SOURCE_DB_PATH = os.path.join('data', 'ponchik_db.db')
# Имя файла, в который будут сохранены SQL-команды
OUTPUT_SQL_FILE = 'migration_data.sql'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def escape_sql(value):
    """Экранирует одинарные кавычки в строках для SQL."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    # Заменяем одинарную кавычку на две одинарные кавычки
    return f"'{str(value).replace("'", "''")}'"

def export_to_sql():
    """Читает данные из локальной БД и генерирует SQL-файл для миграции."""
    if not os.path.exists(SOURCE_DB_PATH):
        logging.error(f"Файл базы данных не найден по пути: {SOURCE_DB_PATH}")
        return

    try:
        conn = sqlite3.connect(SOURCE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        with open(OUTPUT_SQL_FILE, 'w', encoding='utf-8') as f:
            logging.info(f"Открыт файл '{OUTPUT_SQL_FILE}' для записи SQL-команд.")

            # --- Экспорт таблицы 'users' ---
            logging.info("Экспортируем данные из таблицы 'users'...")
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            for user in users:
                # Используем INSERT OR IGNORE, чтобы не было ошибок, если пользователь уже существует на сервере
                sql = (
                    f"INSERT OR IGNORE INTO users (nickname, tg_username, tg_id, activation_date, total_requests) "
                    f"VALUES ({escape_sql(user['nickname'])}, {escape_sql(user['tg_username'])}, "
                    f"{escape_sql(user['tg_id'])}, {escape_sql(user['activation_date'])}, {escape_sql(user['total_requests'])});\n"
                )
                f.write(sql)
            logging.info(f"Сгенерировано {len(users)} команд для таблицы 'users'.")

            # --- Экспорт таблицы 'usage' ---
            logging.info("Экспортируем данные из таблицы 'usage'...")
            cursor.execute("SELECT * FROM usage")
            usages = cursor.fetchall()
            for usage in usages:
                # Здесь можно использовать просто INSERT, т.к. уникальных ключей нет
                sql = (
                    f"INSERT INTO usage (timestamp, username, lore_chunks_sent, prompt_tokens, completion_tokens, total_tokens, user_message, ai_response, model_name) "
                    f"VALUES ({escape_sql(usage['timestamp'])}, {escape_sql(usage['username'])}, {escape_sql(usage['lore_chunks_sent'])}, "
                    f"{escape_sql(usage['prompt_tokens'])}, {escape_sql(usage['completion_tokens'])}, {escape_sql(usage['total_tokens'])}, "
                    f"{escape_sql(usage['user_message'])}, {escape_sql(usage['ai_response'])}, {escape_sql(usage['model_name'])});\n"
                )
                f.write(sql)
            logging.info(f"Сгенерировано {len(usages)} команд для таблицы 'usage'.")

        logging.info(f"Экспорт успешно завершен. Все данные сохранены в файл: {OUTPUT_SQL_FILE}")

    except sqlite3.Error as e:
        logging.error(f"Произошла ошибка SQLite: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    export_to_sql()
