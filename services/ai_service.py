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

# Список стоп-слов для исключения из поиска. Это предлоги, союзы, частицы и т.д.
STOP_WORDS = set([
    "а", "в", "и", "к", "на", "о", "об", "от", "по", "под", "при", "с", "со", "у", "же", "ли", "бы"
])

def get_stemmed_words(text: str) -> set:
    """Вспомогательная функция для получения набора основ слов из текста."""
    clean_text = ''.join(c for c in text.lower() if c.isalnum() or c.isspace())
    if not STEMMER:
        return {word for word in clean_text.split() if word not in STOP_WORDS}
    return {STEMMER.stem(word) for word in clean_text.split() if word not in STOP_WORDS}

# --- РУЧНОЙ СПИСОК ЛОКАЦИЙ ---
# Теперь мы не парсим локации из файлов, а задаем их здесь вручную.
# Это дает полный контроль над тем, какие локации "знает" бот.
KNOWN_LOCATIONS = {
    "кордон",
    "свалка",
    "агропром",
    "нии агропром",
    "подземелья агропрома",
    "бар",
    "бар 100 рентген",
    "темная долина",
    "тёмная долина", 
    "лаборатория x-18",
    "x-18",
    "x18",
    "дикая территория",
    "росток",
    "завод росток",
    "янтарь",
    "x-16",
    "x16",
    "лаборатория x-16",
    "армейские склады",
    "радар",
    "бункер управления выжигателем мозгов",
    "лаборатория x-10",
    "x-10",
    "x10",
    "припять",
    "саркофаг",
    "чаэс",
    "станция"
}

# --- РУЧНОЙ СПИСОК АНОМАЛИЙ ---
# Все виды аномалий и их вариации названий
ANOMALIES = {
    "воронка",
    "карусель",
    "мясорубка",
    "жарка",
    "электра",
    "телепорт",
    "трамплин"
}

# --- РУЧНОЙ СПИСОК МУТАНТОВ ---
# Все виды мутантов и их вариации названий
MUTANTS = {
    "кабан",
    "плоть",
    "слепой пёс",
    "слепая собака",
    "тушкан",
    "снорк",
    "кровосос",
    "излом",
    "контролёр",
    "полтергейст",
    "псевдогигант",
    "зомби",
    "зомбированный"
}

# --- РУЧНОЙ СПИСОК ГРУППИРОВОК ---
# Все группировки и их вариации названий
FACTIONS = {
    "одиночки",
    "одиночка",
    "бандиты",
    "долг",
    "свобода",
    "наёмники",
    "монолит",
    "военные",
    "учёные",
    "чистое небо",
    "ренегаты",
}

# --- РУЧНОЙ СПИСОК ВАЖНЫХ КЛЮЧЕВЫХ СЛОВ ---
# Дополнительные важные термины, не попавшие в другие категории
IMPORTANT_KEYWORDS_RAW = {
    "зона",
    "большая земля",
    "сталкеры",
    "группировки",
    "артефакты",
    "аномалии",
    "мутанты",
    "центр зоны",
    "выброс",
}

# --- Предварительная обработка важных ключевых слов ---
STEMMED_IMPORTANT_KEYWORDS = set()

# Добавляем стемы для всех категорий
for keyword in IMPORTANT_KEYWORDS_RAW:
    STEMMED_IMPORTANT_KEYWORDS.update(get_stemmed_words(keyword))

for anomaly in ANOMALIES:
    STEMMED_IMPORTANT_KEYWORDS.update(get_stemmed_words(anomaly))

for mutant in MUTANTS:
    STEMMED_IMPORTANT_KEYWORDS.update(get_stemmed_words(mutant))

for faction in FACTIONS:
    STEMMED_IMPORTANT_KEYWORDS.update(get_stemmed_words(faction))

# --- Точное сопоставление важных терминов (без стемминга) ---
# Используем для имён персонажей и других терминов, которые не должны ломаться стеммингом
EXACT_IMPORTANT_KEYWORDS = set()

def get_tokens(text: str) -> list:
    """Возвращает список токенов (слова) из текста в нижнем регистре, без стоп-слов."""
    clean_text = ''.join((c.lower() if (c.isalnum() or c.isspace()) else ' ') for c in text)
    return [w for w in clean_text.split() if w and w not in STOP_WORDS]

# Попробуем подключить морфологический анализатор для нормализации (лемматизации)
try:
    import pymorphy2
    MORPH = pymorphy2.MorphAnalyzer()
    logger.info("pymorphy2 найден — включена лемматизация важный терминов.")
except Exception:
    MORPH = None
    logger.debug("pymorphy2 не найден — лемматизация отключена. Установите pymorphy2 для улучшения распознавания имён.")

def get_lemmas(text: str) -> set:
    """Возвращает множество лемм (нормализованных форм) слов в тексте.

    Если pymorphy2 недоступен — возвращаем просто токены без стемминга.
    """
    tokens = get_tokens(text)
    if not MORPH:
        return set(tokens)
    lemmas = set()
    for t in tokens:
        try:
            lemmas.add(MORPH.parse(t)[0].normal_form)
        except Exception:
            lemmas.add(t)
    return lemmas

# Попробуем загрузить файл с персонажами (если есть) и добавить имена в точный набор
try:
    # Поддерживаем оба варианта папки: Lore и lore (Windows не чувствителен к регистру, но явный путь не помешает)
    characters_file_path = Path(__file__).resolve().parent.parent / "Lore" / "Персонажи и отношения.txt"
    if not characters_file_path.exists():
        characters_file_path = Path(__file__).resolve().parent.parent / "lore" / "Персонажи и отношения.txt"

    if characters_file_path.is_file():
        content = characters_file_path.read_text(encoding='utf-8')
        for line in content.splitlines():
            if ':' in line:
                # Часть до двоеточия может содержать несколько прозвищ/алиасов.
                # Поддерживаем разделители: запятая, слэш, точка с запятой, пайп, скобки.
                names_part = line.split(':', 1)[0].strip()
                # Разбиваем по разделителям и добавляем каждое имя отдельно
                for raw_name in re.split(r"[,/;|()]", names_part):
                    character_name = raw_name.strip().lower()
                    if character_name and not character_name.startswith('#'):
                        IMPORTANT_KEYWORDS_RAW.add(character_name)
                        EXACT_IMPORTANT_KEYWORDS.add(character_name)
        logger.info(f"Загружено {len(EXACT_IMPORTANT_KEYWORDS)} имён персонажей (точный набор)")
except Exception as e:
    logger.debug(f"Не удалось загрузить персонажей для точного сопоставления: {e}")

# Обновляем стеммированные важные ключевые слова на случай, если мы добавили персонажей
for exact in list(EXACT_IMPORTANT_KEYWORDS):
    STEMMED_IMPORTANT_KEYWORDS.update(get_stemmed_words(exact))

# Нормализованные леммы для точных ключевых слов — это поможет ловить имена в разных падежах
EXACT_IMPORTANT_LEMMAS = set()
for exact in EXACT_IMPORTANT_KEYWORDS:
    if MORPH:
        try:
            EXACT_IMPORTANT_LEMMAS.add(MORPH.parse(exact)[0].normal_form)
        except Exception:
            EXACT_IMPORTANT_LEMMAS.add(exact)
    else:
        EXACT_IMPORTANT_LEMMAS.add(exact)

# --- Предварительная обработка локаций ---
# Преобразуем каждую локацию в набор основ слов для более гибкого поиска.
# Например, "армейские склады" -> {"армейск", "склад"}
STEMMED_LOCATIONS = {loc: get_stemmed_words(loc) for loc in KNOWN_LOCATIONS}

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
                
                # --- Извлечение локации из первой строки эпизода ---
                first_line, rest_of_content = content.split('\n', 1)
                file_locations = set()
                match = re.search(r'Локация\s*[:—-]?\s*(.+)', first_line, re.IGNORECASE)
                if match:
                    # Берем все названия, разделяем по запятой, убираем точки и лишние пробелы
                    location_names_str = match.group(1).replace('.', '').strip()
                    found_locations = {name.strip().lower() for name in location_names_str.split(',') if name.strip()}
                    file_locations.update(found_locations)
                    logger.info(f"Для файла '{file_path.name}' определены локации: {list(file_locations)}")

                for chunk in content.split('\n\n'):
                    if chunk.strip():
                        # Сохраняем локации вместе с каждым чанком
                        chunk_text = chunk.strip()
                        EPISODE_CHUNKS.append({'source': relative_path_key, 'content': chunk_text, 'locations': file_locations, 'lemmas': get_lemmas(chunk_text)})
            except Exception as e:
                logger.error(f"Не удалось прочитать файл эпизода '{file_path}': {e}")

    # 2. Загружаем и разделяем на чанки общие файлы лора (в корне папки lore)
    for file_path in lore_dir.glob("*.txt"):
        relative_path_key = str(file_path.relative_to(lore_dir))
        try:
            content = file_path.read_text(encoding="utf-8")
            for chunk in content.split('\n\n'):
                if chunk.strip():
                    # У общих чанков нет привязанной локации
                    chunk_text = chunk.strip()
                    GENERAL_CHUNKS.append({'source': relative_path_key, 'content': chunk_text, 'locations': set(), 'lemmas': get_lemmas(chunk_text)})
        except Exception as e:
            logger.error(f"Не удалось прочитать общий файл лора '{file_path}': {e}")

    logger.info(f"Загружено {len(EPISODE_CHUNKS)} чанков из эпизодов и {len(GENERAL_CHUNKS)} общих чанков лора.")

except FileNotFoundError:
    logger.error("Папка 'lore' или её компоненты не найдены! Убедитесь, что существует структура 'lore/episodes/'")
except Exception as e:
    logger.exception(f"Ошибка при чтении файлов лора: {e}")

def retrieve_relevant_lore(user_query: str) -> tuple[str, int]:
    """
    Находит и возвращает самые релевантные фрагменты лора (RAG) и их количество.
    1. Определяет локацию из запроса
    2. Фильтрует чанки по этой локации
    3. Ищет в отфильтрованных чанках остальные ключевые слова
    """
    if not EPISODE_CHUNKS and not GENERAL_CHUNKS:
        return "", 0
    
    # Сначала определяем локацию из запроса
    query_lower = user_query.lower()
    query_stems = get_stemmed_words(user_query)
    if not query_stems:
        return "", 0
    
    # Логируем входящий запрос для отладки
    logger.info(f"Поиск по запросу: '{user_query}'")
    logger.info(f"Стеммированные слова запроса: {query_stems}")

    # --- 1. ПОИСК ЛОКАЦИИ В ЗАПРОСЕ ---
    query_locations = set()
    # Ищем точные совпадения локаций в запросе
    for loc in KNOWN_LOCATIONS:
        if loc.lower() in query_lower:
            query_locations.add(loc)
    
    if query_locations:
        logger.info(f"Найдены локации в запросе: {query_locations}")
    else:
        # Если точных совпадений нет, пробуем найти через стемминг
        for loc, loc_stems in STEMMED_LOCATIONS.items():
            if loc_stems.issubset(query_stems):
                query_locations.add(loc)
                logger.info(f"Найдена локация через стемминг: {loc}")

    # --- 2. ФИЛЬТРАЦИЯ ЧАНКОВ ПО ЛОКАЦИИ ---
    filtered_chunks = []
    
    if query_locations:
        logger.info("Фильтрация чанков по найденным локациям...")
        # Сначала проверяем чанки из эпизодов
        for chunk_data in EPISODE_CHUNKS:
            # Проверяем совпадение локаций в first_line
            chunk_locations = chunk_data.get('locations', set())
            if any(loc.lower() in [cl.lower() for cl in chunk_locations] for loc in query_locations):
                filtered_chunks.append(chunk_data)
        
        if not filtered_chunks:
            logger.info("В эпизодах не найдено чанков с указанной локацией")
    
    if not filtered_chunks:
        # Если по локации ничего не нашли или локация не указана,
        # используем все чанки для поиска
        filtered_chunks = EPISODE_CHUNKS + GENERAL_CHUNKS
        logger.info("Используем все чанки для поиска")

    # --- 3. ОЦЕНКА ЧАНКОВ И ПОИСК КЛЮЧЕВЫХ СЛОВ ---
    scored_chunks = []
    
    # Получаем все слова запроса, исключая стоп-слова и слова локаций
    query_keywords = set()
    for stem in query_stems:
        is_location_word = any(stem in loc_stems for loc_stems in STEMMED_LOCATIONS.values())
        if not is_location_word:
            query_keywords.add(stem)
    
    logger.info(f"Ключевые слова для поиска (после удаления локаций): {query_keywords}")
    # Сырые токены (без стемминга) и леммы запроса для точного сопоставления имён/терминов
    query_tokens = get_tokens(user_query)
    query_lemmas = get_lemmas(user_query)

    exact_token_matches = {t for t in query_tokens if t in EXACT_IMPORTANT_KEYWORDS}
    exact_lemma_matches = {l for l in query_lemmas if l in EXACT_IMPORTANT_LEMMAS}

    # Дополнительный механизм: попытка сопоставить точные имена по стемам/основам.
    # Это помогает ловить имена в разных падежах без наличия pymorphy2
    exact_stem_matches = set()
    try:
        if STEMMER:
            for exact in EXACT_IMPORTANT_KEYWORDS:
                try:
                    if STEMMER.stem(exact) in query_stems:
                        exact_stem_matches.add(exact)
                except Exception:
                    # На случай неожиданных символов в имени
                    if exact in query_tokens or exact in query_lemmas:
                        exact_stem_matches.add(exact)
        else:
            # Если стеммера нет, используем простую проверку вхождения
            for exact in EXACT_IMPORTANT_KEYWORDS:
                if exact in query_lower or exact in query_tokens:
                    exact_stem_matches.add(exact)
    except Exception:
        exact_stem_matches = set()

    if exact_stem_matches:
        logger.info(f"Найдены точные имена по стемам: {exact_stem_matches}")
        exact_token_matches.update(exact_stem_matches)
    if exact_token_matches or exact_lemma_matches:
        logger.info(f"Найдены точные совпадения важных терминов в запросе (tokens/lemmas): {exact_token_matches}/{exact_lemma_matches}")

    # Если в запросе есть точные имена (по токенам или по леммам), добавляем их стемы в ключевые слова
    for name in list(exact_token_matches) + list(exact_lemma_matches):
        query_keywords.update(get_stemmed_words(name))

    for chunk_data in filtered_chunks:
        chunk_content = chunk_data['content']
        chunk_stems = get_stemmed_words(chunk_content)
        
        # Базовая оценка по совпадению ключевых слов
        matched_keywords = query_keywords.intersection(chunk_stems)
        score = sum(2 + len(stem) for stem in matched_keywords)  # Увеличенный вес за ключевые слова

        # Бонус за точное упоминание важных терминов (имена персонажей и т.п.) в тексте чанка
        if exact_token_matches or exact_lemma_matches:
            lc_chunk = chunk_content.lower()
            # Поиск точных токенов (например, 'фура') по границам слова
            for exact in exact_token_matches:
                if re.search(r"\b" + re.escape(exact) + r"\b", lc_chunk):
                    score += 20
            # Поиск по леммам внутри заранее вычисленных лемм чанка
            chunk_lemmas = chunk_data.get('lemmas', set())
            matched_lemma_hits = exact_lemma_matches.intersection(chunk_lemmas)
            if matched_lemma_hits:
                score += 20 * len(matched_lemma_hits)
        
        # Бонусы:
        # 1. За точное совпадение локации в первой строке
        if query_locations and any(loc.lower() in str(chunk_data.get('locations','')).lower() for loc in query_locations):
            score += 10  # Большой бонус за точное совпадение локации
        
        # 2. За каждое найденное ключевое слово (поощряем полноту совпадения)
        coverage = len(matched_keywords) / len(query_keywords) if query_keywords else 0
        score *= (1 + coverage)  # Множитель за полноту
        
        # 3. Приоритет эпизодов над общими файлами
        if chunk_data in EPISODE_CHUNKS:
            score *= 1.2  # 20% бонус для эпизодов

        # Добавляем только если есть хоть какое-то совпадение
        if score > 0:
            log_entry = {
                'score': score,
                'content': chunk_content,
                'source': chunk_data['source'],
                'matched_keywords': list(matched_keywords),
                'locations': list(chunk_data.get('locations', set()))
            }
            scored_chunks.append(log_entry)
            logger.debug(f"Чанк набрал {score:.2f} очков. Найдены слова: {list(matched_keywords)}")

    if not scored_chunks:
        logger.info("Не найдено релевантных абзацев (нет совпадений по ключевым словам)")
        return "", 0

    # Сортируем по убыванию оценки
    scored_chunks.sort(key=lambda x: x['score'], reverse=True)
    
    # Берем [число] лучших чанка
    top_chunks = scored_chunks[:1]
    
    if not top_chunks:
        return "", 0

    logger.info(f"Найдено {len(top_chunks)} релевантных абзацев для ответа.")
    for i, chunk in enumerate(top_chunks):
        logger.info(f"  {i+1}. Оценка {chunk['score']:.2f}, Файл: {chunk['source']}, Слова: {chunk['matched_keywords']}")

    # Объединяем контент лучших чанков
    combined_content = "\n\n---\n\n".join([chunk['content'] for chunk in top_chunks])
    
    # Возвращаем объединенный контент и количество найденных чанков
    return combined_content, len(top_chunks)

# Инициализируем асинхронный клиент, настроенный на Groq
client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
    max_retries=0,  # Отключаем автоматические повторные попытки при ошибке 429
    timeout=20.0,   # Устанавливаем общий таймаут на ответ в 20 секунд
)

# Список моделей для переключения в случае достижения лимитов.
MODELS_TO_TRY = [
    "groq/compound",
    "groq/compound-mini",
    "llama-3.3-70b-versatile",
    "moonshotai/kimi-k2-instruct",
    "moonshotai/kimi-k2-instruct-0905",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-32b"
]

# --- СЛОВАРЬ С СУТОЧНЫМИ ЛИМИТАМИ ТОКЕНОВ ДЛЯ КАЖДОЙ МОДЕЛИ ---
MODEL_TOKEN_LIMITS = {
    "groq/compound": 123,
    "groq/compound-mini": 123,
    "llama-3.3-70b-versatile": 100_000,
    "moonshotai/kimi-k2-instruct": 300_000,
    "moonshotai/kimi-k2-instruct-0905": 300_000,
    "openai/gpt-oss-120b": 200_000,
    "openai/gpt-oss-20b": 200_000,
    "llama-3.1-8b-instant": 500_000,
    "meta-llama/llama-4-maverick-17b-128e-instruct": 500_000,
    "qwen/qwen3-32b": 500_000
}

def _strip_think_tags(text: str) -> str:
    """Полностью удаляет блоки <think>...</think> из текста и очищает пробелы по краям."""
    # Используем re.sub для замены всего, что находится между <think> и </think> (включая сами теги) на пустую строку.
    # re.DOTALL позволяет точке (.) соответствовать также и символу переноса строки
    processed_text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return processed_text.strip()

async def get_ai_response(message_history: list, username: str) -> dict:
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
            
            # Устанавливаем лимит токенов для всех моделей, кроме qwen/qwen3-32b
            max_tokens_for_model = None if model == "qwen/qwen3-32b" else 150

            response = await client.chat.completions.create(
                model=model,
                messages=messages_with_prompt,
                temperature=0.5,
                max_tokens=max_tokens_for_model,
            )
            raw_message = response.choices[0].message.content
            ai_message = _strip_think_tags(raw_message)
            # Temporary log: raw AI message before processing
            logger.info(f"Raw AI Message: {raw_message}")

            # Логируем использование токенов в консоль и в БД
            logger.info(f"Token Usage: {username} - {response.usage.total_tokens} (Total)")
            log_usage_to_db(username, user_query, response.usage, ai_message, lore_chunks_count, model)
            return {
                "message": ai_message,
                "model": model,
                "tokens": response.usage.total_tokens
            }
        except RateLimitError:
            logger.warning(f"Достигнут лимит для модели ({model}). Переключаюсь на следующую.")
            continue  # Переходим к следующей модели в цикле
        except Exception as e:
            # Специальная обработка ошибки "Request Entity Too Large"
            if "Error code: 413" in str(e) and "Request Entity Too Large" in str(e):
                logger.warning(f"Ошибка 413 (Request Too Large) с моделью {model}. Попытка отправить запрос без лора.")
                # get_ai_response_without_lore тоже должна возвращать словарь
                return await get_ai_response_without_lore(message_history, model, username)

            logger.error(f"Критическая ошибка при обращении к Groq API с моделью {model}: {e}")
            return {"message": "Хм, чёт у меня какие-то неполадки... Напиши потом.", "model": "error"}

    # Этот код выполнится, только если все модели из списка исчерпали лимиты
    logger.error("Все доступные модели исчерпали свои лимиты.")
    return {
        "message": "Мля, я заманался с тобой болтать. Приходи в другой раз. (токены закончились, напиши через несколько часов)",
        "model": "limit_exceeded"
    }
    

async def get_ai_response_without_lore(message_history: list, model: str, username: str) -> dict:
    """Запасной метод для отправки запроса без RAG-контекста."""
    try:
        logger.info(f"Повторная отправка запроса в Groq (модель: {model}) без лора.")
        base_prompt = SYSTEM_PROMPT
        messages_with_prompt = [{"role": "system", "content": base_prompt}] + message_history

        # Устанавливаем лимит токенов для всех моделей, кроме qwen/qwen3-32b
        max_tokens_for_model = None if model == "qwen/qwen3-32b" else 150

        response = await client.chat.completions.create(
            model=model,
            messages=messages_with_prompt,
            temperature=0.5,
            max_tokens=max_tokens_for_model,
        )
        raw_message = response.choices[0].message.content
        ai_message = _strip_think_tags(raw_message)
        logger.info(f"Token Usage (without lore): {username} - {response.usage.total_tokens} (Total)")
        log_usage_to_db(username, message_history[-1]['content'], response.usage, ai_message, lore_chunks_count=0, model_name=model)
        return {
            "message": ai_message,
            "model": model,
            "tokens": response.usage.total_tokens
        }
    except Exception as e:
        logger.error(f"Критическая ошибка при обращении к Groq API с моделью {model}: {e}")
        return {"message": "Хм, чёт у меня какие-то неполадки... Напиши потом.", "model": "error"}