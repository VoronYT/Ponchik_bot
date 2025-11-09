import logging
from openai import AsyncOpenAI, RateLimitError
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Улучшение: Добавляем стеммер для более гибкого поиска ---
try:
    from nltk.stem.snowball import SnowballStemmer
    # Инициализируем стеммер для русского языка
    STEMMER = SnowballStemmer("russian")
except ImportError: # NLTK might not be installed
    logger.warning("Библиотека NLTK не найдена. Поиск будет работать без стемминга. Для установки: pip install nltk")
    STEMMER = None
from config import GROQ_API_KEY, SYSTEM_PROMPT
# Импортируем нашу новую функцию для логирования в БД
from database import log_usage_to_db

# --- Система управления лором ---
# Новая структура: храним сразу готовые абзацы (чанки)
EPISODE_CHUNKS = []
GENERAL_CHUNKS = []

try:
    lore_dir = Path(__file__).resolve().parent.parent / "lore"
    episodes_dir = lore_dir / "episodes"
    
    # 1. Загружаем и разделяем на чанки файлы эпизодов
    if episodes_dir.is_dir():
        for file_path in episodes_dir.glob("*.txt"):
            relative_path_key = str(file_path.relative_to(lore_dir))
            try:
                content = file_path.read_text(encoding="utf-8")
                for chunk in content.split('\n\n'):
                    if chunk.strip():
                        EPISODE_CHUNKS.append({'source': relative_path_key, 'content': chunk.strip()})
            except Exception as e:
                logger.error(f"Не удалось прочитать файл эпизода '{file_path}': {e}")

    # 2. Загружаем и разделяем на чанки общие файлы лора (в корне папки lore)
    for file_path in lore_dir.glob("*.txt"):
        relative_path_key = str(file_path.relative_to(lore_dir))
        try:
            content = file_path.read_text(encoding="utf-8")
            for chunk in content.split('\n\n'):
                if chunk.strip():
                    GENERAL_CHUNKS.append({'source': relative_path_key, 'content': chunk.strip()})
        except Exception as e:
            logger.error(f"Не удалось прочитать общий файл лора '{file_path}': {e}")

    logger.info(f"Загружено {len(EPISODE_CHUNKS)} чанков из эпизодов и {len(GENERAL_CHUNKS)} общих чанков лора.")

except FileNotFoundError:
    logger.error("Папка 'lore' или её компоненты не найдены! Убедитесь, что существует структура 'lore/episodes/'")
except Exception as e:
    logger.exception(f"Ошибка при чтении файлов лора: {e}")

def get_stemmed_words(text: str) -> set:
    """Вспомогательная функция для получения набора основ слов из текста."""
    clean_text = ''.join(c for c in text.lower() if c.isalnum() or c.isspace())
    if not STEMMER:
        return {word for word in clean_text.split() if word not in STOP_WORDS}
    return {STEMMER.stem(word) for word in clean_text.split() if word not in STOP_WORDS}

# Список стоп-слов для исключения из поиска. Это предлоги, союзы, частицы и т.д.
STOP_WORDS = set([
    "а", "в", "и", "к", "на", "о", "об", "от", "по", "под", "при", "с", "со", "у", "же", "ли", "бы"
])

def retrieve_relevant_lore(user_query: str) -> tuple[str, int]:
    """
    Находит и возвращает самые релевантные фрагменты лора (RAG) и их количество.
    Отбирает несколько лучших абзацев, если их релевантность близка к максимальной.
    """
    if not EPISODE_CHUNKS and not GENERAL_CHUNKS:
        return "", 0

    query_stems = get_stemmed_words(user_query)
    if not query_stems:
        return "", 0

    # --- Этап 1: Оценка всех абзацев ---
    scored_chunks = []
    # Сначала оцениваем приоритетные чанки (эпизоды)
    for chunk_data in EPISODE_CHUNKS + GENERAL_CHUNKS:
        chunk_content = chunk_data['content']
        chunk_stems = get_stemmed_words(chunk_content)
        score = sum(1 + len(stem) // 3 for stem in query_stems.intersection(chunk_stems))
        
        # Приоритет эпизодов: даем им небольшой бонус к очкам
        if chunk_data in EPISODE_CHUNKS:
            score += 1

        if score > 0:
            scored_chunks.append({'score': score, 'content': chunk_content, 'source': chunk_data['source']})

    if not scored_chunks:
        logger.info("Релевантных абзацев в лоре не найдено (нет совпадений по ключевым словам).")
        return "", 0

    # Сортируем все найденные абзацы по очкам (от большего к меньшему)
    scored_chunks.sort(key=lambda x: x['score'], reverse=True)

    # --- Этап 2: Динамический отбор лучших абзацев ---
    max_score = scored_chunks[0]['score']
    # Устанавливаем порог. Например, 75% от лучшего результата. И минимальный порог в 3 очка.
    score_threshold = max(max_score * 0.85, 3)
    
    # Отбираем все чанки, которые проходят порог, но не более 2-х штук
    top_scored_chunks = [
        chunk for chunk in scored_chunks
        if chunk['score'] >= score_threshold
    ][:2]

    if top_scored_chunks:
        # Собираем информацию для детального логирования
        log_details = [f"'{chunk['source']}' ({chunk['score']} очков)" for chunk in top_scored_chunks]
        logger.info(f"Найдено {len(top_scored_chunks)} релевантных абзацев (лучший результат: {max_score} очков).")
        logger.info(f"Отправлено в ИИ: {len(top_scored_chunks)} абзац(а) из: {', '.join(log_details)}.")

        top_chunks_content = [chunk['content'] for chunk in top_scored_chunks]
        # Объединяем все отобранные абзацы в один блок контекста
        combined_chunks = "\n\n---\n\n".join(top_chunks_content)
        return combined_chunks, len(top_chunks_content)

    logger.info(f"Релевантных абзацев в лоре не найдено (лучший результат {max_score} очков не прошел порог).")
    return "", 0

# Инициализируем асинхронный клиент, настроенный на Groq

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
    max_retries=0,  # Отключаем автоматические повторные попытки при ошибке 429
    timeout=20.0,   # Устанавливаем общий таймаут на ответ в 20 секунд
)

# Список моделей для переключения в случае достижения лимитов.
# Бот будет пробовать их по порядку.
MODELS_TO_TRY = [
    "groq/compound",
    "groq/compound-mini",
    "llama-3.3-70b-versatile",
    "moonshotai/kimi-k2-instruct",
    "moonshotai/kimi-k2-instruct-0905",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "allam-2-7b",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-32b"
]

# --- СЛОВАРЬ С СУТОЧНЫМИ ЛИМИТАМИ ТОКЕНОВ ДЛЯ КАЖДОЙ МОДЕЛИ ---
# !!! ВАЖНО: Эти значения нужно будет поддерживать в актуальном состоянии вручную.
# Укажите здесь суточный лимит токенов для каждой модели, которую вы используете.
MODEL_TOKEN_LIMITS = {
    "groq/compound": 123,
    "groq/compound-mini": 123,
    "llama-3.3-70b-versatile": 100_000,
    "moonshotai/kimi-k2-instruct": 300_000,
    "moonshotai/kimi-k2-instruct-0905": 300_000,
    "openai/gpt-oss-120b": 200_000,
    "openai/gpt-oss-20b": 200_000,
    "allam-2-7b": 500_000,
    "llama-3.1-8b-instant": 500_000,
    "meta-llama/llama-4-maverick-17b-128e-instruct": 500_000,
    "qwen/qwen3-32b": 500_000,
}

# Рекомендованные:
    # "llama-3.1-8b-instant",
    # "llama-3.3-70b-versatile",
    # "qwen/qwen3-32b"

#Список всех моделей groq
    # "groq/compound",
    # "groq/compound-mini",
    # "meta-llama/llama-4-scout-17b-16e-instruct",
    # "llama-3.3-70b-versatile",
    # "moonshotai/kimi-k2-instruct",
    # "moonshotai/kimi-k2-instruct-0905",
    # "openai/gpt-oss-120b",
    # "openai/gpt-oss-20b",
    # "allam-2-7b",
    # "llama-3.1-8b-instant",
    # "meta-llama/llama-4-maverick-17b-128e-instruct",
    # "qwen/qwen3-32b"

def _strip_think_tags(text: str) -> str:
    """Удаляет из ответа модели блоки <think>...</think>."""
    # re.DOTALL позволяет точке (.) соответствовать также и символам новой строки,
    # что важно для многострочных блоков <think>.
    cleaned_text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    return cleaned_text.strip()

async def get_ai_response(message_history: list, username: str) -> tuple[str, str]:
    """
    Отправляет историю сообщений в Groq. При достижении лимита одной модели,
    автоматически переключается на следующую из списка.
    """
    # 1. Извлекаем релевантную информацию из лора на основе последнего сообщения пользователя
    user_query = message_history[-1]['content']
    relevant_lore_chunk, lore_chunks_count = retrieve_relevant_lore(user_query)

    # 2. Формируем динамический системный промпт
    dynamic_system_prompt = SYSTEM_PROMPT

    # Добавляем найденный чанк из эпизода, если он есть
    if relevant_lore_chunk:
        dynamic_system_prompt += f"\n\nВОСПОМИНАНИЕ ИЗ ТВОЕЙ ИСТОРИИ ДЛЯ КОНТЕКСТА:\n{relevant_lore_chunk}"

    messages_with_prompt = [{"role": "system", "content": dynamic_system_prompt}] + message_history

    for model in MODELS_TO_TRY:
        try:
            logger.info(f"Отправка запроса в Groq (модель: {model}) с последним сообщением: '{user_query}'")
            # Добавляем stop-последовательности, чтобы попытаться предотвратить
            # генерацию служебных тегов вроде <think>...</think> и ограничиваем длину.
            response = await client.chat.completions.create(
                model=model,
                messages=messages_with_prompt,
                temperature=0.5,
                max_tokens=150,  # Ограничиваем длину ответа ~100-200 словами
                stop=["<think>", "</think>"],
            )
            raw_message = response.choices[0].message.content
            ai_message = _strip_think_tags(raw_message)

            # Если модель всё же вернула теги <think>...</think>, делаем одну повторную попытку
            # с более строгой системной инструкцией (и тем же стопом). Это уменьшит шанс
            # генерации внутренних размышлений.
            raw_low = raw_message.lower() if isinstance(raw_message, str) else ''
            if '<think>' in raw_low or '</think>' in raw_low:
                logger.warning(f"Модель {model} вернула теги <think> — делаю одну повторную попытку без них для {username}.")
                strict_system = dynamic_system_prompt + "\n\nВажное правило: НИКОГДА не выводи внутренние размышления, метатеги или теги вида <think>...</think>. Отвечай 1-3 предложениями, прямо и без мета-комментариев."
                retry_messages = [{"role": "system", "content": strict_system}] + message_history
                try:
                    retry_resp = await client.chat.completions.create(
                        model=model,
                        messages=retry_messages,
                        temperature=0.5,
                        max_tokens=150,
                        stop=["<think>", "</think>"],
                    )
                    raw_retry = retry_resp.choices[0].message.content
                    ai_message = _strip_think_tags(raw_retry)
                    # если повторный ответ тоже содержит теги, зафиксируем это и все равно уберём теги
                    if '<think>' in (raw_retry.lower() if isinstance(raw_retry, str) else ''):
                        logger.warning(f"Повторная попытка для {username} всё ещё вернула <think>-теги; теги будут удалены.")
                        ai_message = _strip_think_tags(raw_retry) + "\n\n(Внутренние размышления были удалены из ответа.)"
                        # логируем использование токенов и результаты повторной попытки
                        logger.info(f"Token Usage (retry): {username} - {getattr(retry_resp.usage, 'total_tokens', 'n/a')} (Total)")
                        log_usage_to_db(username, user_query, getattr(retry_resp, 'usage', None), ai_message, lore_chunks_count, model)
                    else:
                        # логируем токены от успешной повторной попытки
                        logger.info(f"Token Usage (retry): {username} - {getattr(retry_resp.usage, 'total_tokens', 'n/a')} (Total)")
                        log_usage_to_db(username, user_query, getattr(retry_resp, 'usage', None), ai_message, lore_chunks_count, model)
                except Exception as e2:
                    logger.error(f"Ошибка при повторной попытке удаления <think>-тегов для модели {model}: {e2}")
                    # В случае падения при повторной попытке оставляем уже очищенный первичный ответ
                    ai_message = _strip_think_tags(raw_message) + "\n\n(Первичный ответ содержал внутренние размышления, они удалены.)"
            # Логируем использование токенов в консоль и в БД
            logger.info(f"Token Usage: {username} - {response.usage.total_tokens} (Total)")
            log_usage_to_db(username, user_query, response.usage, ai_message, lore_chunks_count, model)
            return ai_message, model
        except RateLimitError:
            logger.warning(f"Достигнут лимит для модели ({model}). Переключаюсь на следующую.")
            continue  # Переходим к следующей модели в цикле
        except Exception as e:
            # Специальная обработка ошибки "Request Entity Too Large"
            if "Error code: 413" in str(e) and "Request Entity Too Large" in str(e):
                logger.warning(f"Ошибка 413 (Request Too Large) с моделью {model}. Попытка отправить запрос без лора.")
                return await get_ai_response_without_lore(message_history, model, username)

            logger.error(f"Критическая ошибка при обращении к Groq API с моделью {model}: {e}")
            return "Хм, чёт у меня какие-то неполадки... Напиши потом.", "error"

    # Этот код выполнится, только если все модели из списка исчерпали лимиты
    logger.error("Все доступные модели исчерпали свои лимиты.")
    return "Мля, я заманался с тобой болтать. Приходи в другой раз. (токены закончились, напиши через несколько часов)", "limit_exceeded"

async def get_ai_response_without_lore(message_history: list, model: str, username: str) -> tuple[str, str]:
    """
    Запасной метод для отправки запроса без RAG-контекста, если первоначальный запрос был слишком большим.
    """
    try:
        logger.info(f"Повторная отправка запроса в Groq (модель: {model}) без лора.")
        # Даже в этом случае, мы можем попробовать отправить описание персонажей, т.к. оно не очень большое
        base_prompt = SYSTEM_PROMPT # В аварийном режиме отправляем только базовый промпт

        messages_with_prompt = [{"role": "system", "content": base_prompt}] + message_history
        response = await client.chat.completions.create(
            model=model,
            messages=messages_with_prompt,
            temperature=0.5,
            max_tokens=150,  # Ограничиваем длину ответа ~100-200 словами
        )
        raw_message = response.choices[0].message.content
        ai_message = _strip_think_tags(raw_message)
        # Логируем использование токенов в консоль и в БД
        logger.info(f"Token Usage (without lore): {username} - {response.usage.total_tokens} (Total)")
        log_usage_to_db(username, message_history[-1]['content'], response.usage, ai_message, lore_chunks_count=0, model_name=model)
        return ai_message, model
    except Exception as e:
        logger.error(f"Критическая ошибка при обращении к Groq API с моделью {model}: {e}")
        return "Хм, чёт у меня какие-то неполадки... Напиши потом.", "error"
