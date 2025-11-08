import logging
import sys
import re

import os
# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
# Переносим настройку в самое начало, чтобы она применялась ко всем импортируемым модулям.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Удаляем дублирующийся импорт, оставляем один более полный
from telegram.ext import Application, PicklePersistence
from telegram import BotCommand

# Импортируем новую функцию для инициализации БД
from database import init_db
# Импортируем токен из централизованной конфигурации
from config import BOT_TOKEN

# Импортируем готовые обработчики из их модулей
# Теперь при импорте этих модулей логирование уже будет настроено.
from handlers.start_command import start_handler
from handlers.echo import echo_handler
from handlers.reset_command import reset_handler, confirm_age_handler
from handlers.media_handler import media_handler

class HttpxLogFilter(logging.Filter):
    """
    Фильтр для сокращения логов от библиотеки httpx.
    Преобразует 'HTTP Request: POST ... "HTTP/1.1 200 OK"' в 'Request 200 OK'.
    """
    _pattern = re.compile(r'HTTP Request: \w+ .* "HTTP/\d\.\d (\d{3} [A-Z ]+)"')

    def filter(self, record: logging.LogRecord) -> bool:
        # Применяем фильтр только к INFO-логам от httpx
        if record.name == 'httpx' and record.levelno == logging.INFO:
            match = self._pattern.match(record.getMessage())
            if match:
                # Извлекаем статус (например, "200 OK") и заменяем сообщение
                record.msg = f"Request {match.group(1)}"
                record.args = () # Очищаем аргументы, чтобы избежать ошибок форматирования
        return True # Пропускаем все записи дальше

# Создаем и применяем наш кастомный фильтр к логгеру httpx
httpx_logger = logging.getLogger("httpx")
httpx_logger.addFilter(HttpxLogFilter())

async def post_init(application: Application) -> None:
    """
    Эта функция выполняется один раз после запуска бота.
    Она устанавливает список команд, которые будут видны в кнопке меню.
    """
    commands = [
        BotCommand("start", "Перезапустить бота"),
        BotCommand("reset", "Очистить историю диалога")
    ]
    await application.bot.set_my_commands(commands)
    logging.getLogger(__name__).info("Команды в меню успешно установлены.")

def main() -> None:
    """Запуск бота."""
    logger = logging.getLogger(__name__)
    logger.info("Запуск бота...")

    # Инициализируем базу данных для логов токенов
    init_db()

    # Определяем путь к папке с данными
    DATA_DIR = "data"

    # Создаем объект для сохранения данных. Файл будет создан в той же папке.
    persistence = PicklePersistence(filepath=os.path.join(DATA_DIR, "ponchik_bot_persistence"))
    # Создаем приложение, передаем ему токен бота и объект для сохранения данных.
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).post_init(post_init).build()

    # Регистрируем обработчики из модулей
    application.add_handler(start_handler)
    application.add_handler(echo_handler)
    application.add_handler(reset_handler)
    application.add_handler(confirm_age_handler)
    application.add_handler(media_handler)

    # Запускаем бота (он будет работать, пока вы не остановите процесс, например, нажав Ctrl+C)
    application.run_polling()

if __name__ == "__main__":
    main()
