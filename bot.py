import logging
import sys
import re

import os
# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
# Переносим настройку в самое начало, чтобы она применялась ко всем импортируемым модулям.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", # Стандартный формат
    level=logging.INFO, # Базовый уровень для всех логгеров
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)] # Явно указываем обработчик
)

# --- Кастомная настройка форматов для чистоты логов ---
# Создаем новый, короткий форматтер, который выводит только время и само сообщение.
short_formatter = logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Создаем новый обработчик, который будет использовать этот короткий форматтер.
short_handler = logging.StreamHandler(sys.stdout)
short_handler.setFormatter(short_formatter)

# Применяем короткий формат к нужным нам логгерам.
for logger_name in ["handlers.echo", "handlers.support_command", "httpx", "services.lore_retrieval"]:
    logger_to_customize = logging.getLogger(logger_name)
    logger_to_customize.handlers = []  # Удаляем старые обработчики, чтобы избежать дублирования.
    logger_to_customize.addHandler(short_handler)
    logger_to_customize.propagate = False  # Запрещаем передавать сообщения "выше" корневому логгеру.


# Удаляем дублирующийся импорт, оставляем один более полный
from telegram.ext import Application, PicklePersistence
from telegram import Update
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
from handlers.support_command import support_handler
from handlers.stats_command import stats_handler, stats_callback_handler
from handlers.topusers_command import topusers_handler, topusers_callback_handler
from handlers.helpadm_command import helpadm_handler
from handlers.getdb_command import getdb_handler
from handlers.globalmessage_command import globalmessage_handler
from handlers.member_updates import member_update_handler
#sample
class HttpxLogFilter(logging.Filter):
    """
    Фильтр для сокращения логов от библиотеки httpx.
    - Преобразует '... 200 OK' в 'Request 200 OK'.
    - Полностью скрывает ошибки '429 Too Many Requests', т.к. у нас есть свой лог.
    """
    _pattern = re.compile(r'HTTP Request: \w+ .* "HTTP/\d\.\d (\d{3} [A-Z ]+)"')

    def filter(self, record: logging.LogRecord) -> bool:
        # Применяем фильтр только к INFO-логам от httpx
        if record.name == 'httpx' and record.levelno == logging.INFO:
            message = record.getMessage()
            # Сначала проверяем на ошибку 429
            if "429 Too Many Requests" in message:
                return False # Не пропускаем эту запись в лог

            match = self._pattern.match(message)
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
        BotCommand("reset", "Очистить историю диалога"),
        BotCommand("support", "Поддержать Ворона")
    ]
    await application.bot.set_my_commands(commands)
    logging.getLogger(__name__).info("Команды в меню успешно установлены.")

def main() -> None:
    """Запуск бота."""
    logger = logging.getLogger(__name__)
    logger.info("Запуск бота...")

    # Инициализируем базу данных для логов токенов
    init_db()

    # Временный диагностический код удалён (db_watcher).

    # Определяем путь к папке с данными
    # Railway имеет переменные окружения: PORT, RAILWAY_ENVIRONMENT, DATABASE_URL и т.д.
    # Проверяем наличие RAILWAY_ENVIRONMENT или PORT (более надежные маркеры Railway)
    IS_RAILWAY = 'RAILWAY_ENVIRONMENT' in os.environ or ('PORT' in os.environ and os.path.exists('/app'))
    DATA_DIR = "/app/data" if IS_RAILWAY else os.path.join(os.path.dirname(__file__), 'data')

    # Убедимся, что папка для данных существует
    os.makedirs(DATA_DIR, exist_ok=True)

    # Создаем объект для сохранения данных. Файл будет создан в той же папке.
    persistence = PicklePersistence(filepath=os.path.join(DATA_DIR, "ponchik_bot_persistence"))
    # Создаем приложение, передаем ему токен бота и объект для сохранения данных.
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )

    # --- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ---
    # Важен порядок: сначала специфичные (команды, диалоги), затем более общие (текст, медиа).

    application.add_handler(start_handler)
    application.add_handler(reset_handler)
    application.add_handler(support_handler)
    application.add_handler(stats_handler)
    application.add_handler(confirm_age_handler)
    application.add_handler(stats_callback_handler) # Обработчик кнопок статистики
    application.add_handler(topusers_handler)
    application.add_handler(topusers_callback_handler)
    application.add_handler(helpadm_handler) # Команда помощи для админа
    application.add_handler(getdb_handler) # Команда для получения БД
    application.add_handler(globalmessage_handler) # Команда для глобальной рассылки
    application.add_handler(member_update_handler) # Обработчик входа/выхода/бана
    application.add_handler(media_handler)
    application.add_handler(echo_handler) # Общий обработчик текста ставим в конце

    # Запускаем бота (он будет работать, пока вы не остановите процесс, например, нажав Ctrl+C)
    application.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY, Update.CHAT_MEMBER])

if __name__ == "__main__":
    main()
