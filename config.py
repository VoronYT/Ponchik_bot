import os
import logging
from dotenv import load_dotenv
from pathlib import Path

# Загружаем переменные из .env файла
load_dotenv()

logger = logging.getLogger(__name__)

def get_env_var(var_name: str, is_int: bool = False, is_list_of_int: bool = False, default=None):
    """
    Безопасно загружает переменную окружения и проверяет ее наличие.
    Если указан `default`, переменная становится необязательной.
    """
    value = os.getenv(var_name)
    if value is None:
        if default is not None:
            return default
        logger.critical(f"ОШИБКА: Обязательная переменная окружения {var_name} не найдена в .env файле.")
        raise ValueError(f"Переменная {var_name} не найдена")

    if is_int:
        try:
            return int(value)
        except ValueError:
            logger.critical(f"ОШИБКА: Переменная {var_name} ('{value}') должна быть числом.")
            raise ValueError(f"Переменная {var_name} должна быть числом")

    if is_list_of_int:
        try:
            return [int(item.strip()) for item in value.split(',')]
        except ValueError:
            logger.critical(f"ОШИБКА: Переменная {var_name} ('{value}') должна быть списком чисел, разделенных запятой.")
            raise ValueError(f"Переменная {var_name} должна быть списком чисел")

    return value

def load_prompt_from_file(filename: str) -> str:
    """Загружает текст промпта из файла."""
    try:
        prompt_path = Path(__file__).parent / filename
        return prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.critical(f"ОШИБКА: Файл с промптом '{filename}' не найден.")
        raise

try:
    # Загружаем все переменные, которые нам нужны
    BOT_TOKEN = get_env_var("BOT_TOKEN")
    GROQ_API_KEY = get_env_var("GROQ_API_KEY")
    SUPPORT_LINK = get_env_var("SUPPORT_LINK")
    # Загружаем ID администратора. Он должен быть числом.
    ADMIN_ID = get_env_var("ADMIN_ID", is_int=True)
    
    # Список заблокированных пользователей (ID)
    BLACKLIST = [
        # 123456789,  # @username - причина блокировки
        1754638261 #тестовый
    ]
    
    # Загружаем системный промпт из файла, а не из .env
    SYSTEM_PROMPT = load_prompt_from_file("system_prompt.txt")
except (ValueError, FileNotFoundError):
    # Если при загрузке произошла любая ошибка, которую мы отловили выше,
    # программа выведет сообщение в лог и завершится.
    exit()
