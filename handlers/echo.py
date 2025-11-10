import logging
from telegram import Update
import re
from telegram.ext import ContextTypes, MessageHandler, filters
from telegram.constants import ChatAction

# Импортируем утилиты и нужные компоненты из сервиса ИИ
from services.ai_service import get_ai_response, retrieve_relevant_lore
from handlers.utils import check_blacklist

logger = logging.getLogger(__name__)

def is_spam(text: str) -> bool:
    """
    Проверяет, является ли текст бессмысленным набором символов.
    Возвращает True, если сообщение похоже на спам.
    """
    length = len(text)
    if length < 100: # Короткие сообщения не проверяем
        return False

    # Считаем количество букв и цифр
    alnum_count = sum(1 for char in text if char.isalnum())
    # Считаем количество уникальных символов
    unique_chars = len(set(text))

    # Если в длинном сообщении очень мало букв/цифр или очень мало уникальных символов, считаем это спамом.
    return (alnum_count / length < 0.3) or (unique_chars < 10 and length > 200)

def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы для Telegram MarkdownV2."""
    # Список символов, которые нужно экранировать
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

from maintenance import BOT_MAINTENANCE

@check_blacklist
async def echo_logic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отвечает на текстовое сообщение с помощью ИИ."""
    user = update.effective_user
    message_text = update.message.text
    logger.info(f"[РУ]{user.full_name} ({user.id}) написал: '{message_text}'")

    # Проверяем, не находится ли бот в режиме обновления
    if BOT_MAINTENANCE:
        await update.message.reply_text("[РУ]Бот на обновлении. Напиши попозже!")
        return

    # Проверяем, подтвержден ли возраст, перед тем как отвечать
    if not context.user_data.get("age_verified"):
        logger.warning(f"Пользователь {user.full_name} ({user.id}) попытался написать боту без подтверждения возраста.")
        await update.message.reply_text("Сначала подтверди свой возраст, нажав /start.")
        return

    # --- Этапы 1 и 2: Поиск релевантного лора и формирование промпта ---
    # Получаем или создаем историю сообщений для этого пользователя
    chat_history = context.user_data.get("chat_history", [])
    # Добавляем сообщение пользователя в историю, только если это не команда
    if not message_text.startswith('/'):
        chat_history.append({"role": "user", "content": message_text})

    # Находим релевантные абзацы
    relevant_lore_chunk, lore_chunks_count = retrieve_relevant_lore(message_text)

    # Формируем полный промпт, который был бы отправлен в ИИ
    from config import SYSTEM_PROMPT
    full_prompt_for_ai = SYSTEM_PROMPT
    if relevant_lore_chunk:
        full_prompt_for_ai += f"\n\nВОСПОМИНАНИЕ ИЗ ТВОЕЙ ИСТОРИИ ДЛЯ КОНТЕКСТА:\n{relevant_lore_chunk}"
    
    # --- Этап 3: Отправка запроса в ИИ ---
    # Обрезаем историю до последних 6 сообщений, чтобы не превышать лимит контекста
    context.user_data["chat_history"] = chat_history[-6:]

    try:
        # Показываем статус набора текста
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        # Получаем ответ от ИИ
        response = await get_ai_response(chat_history, user.username or str(user.id))
        if len(response) == 3:
            ai_message, used_model, total_tokens = response
        elif len(response) == 2:
            ai_message, used_model = response
            total_tokens = 0  # Или другое значение по умолчанию
        else:
            logger.error(f"Unexpected response from get_ai_response: {response}")

        # Если получили ответ, отсылаем пользователю
        if ai_message:
            await update.message.reply_text(ai_message)
            logger.info(f"[РУ]Бот ответил {user.full_name} ({user.id}) (модель: {used_model}) (token usage: {total_tokens or 'N/A'}): '{ai_message}'")
            # Сохраняем ответ ассистента в историю только если это был успешный ответ от модели
            # (т.е. used_model это название модели, а не 'error' или 'limit_exceeded')
            if isinstance(used_model, str) and not any(err in used_model for err in ['error', 'limit_exceeded']):
                chat_history.append({"role": "assistant", "content": ai_message})
                context.user_data["chat_history"] = chat_history
        else:
            logger.warning("ИИ вернул пустой ответ.")
            await update.message.reply_text("Извини, ничего не нашлось. Попробуй переформулировать запрос.")
    except Exception as e:
        logger.exception(f"Ошибка при запросе к ИИ: {e}")
        await update.message.reply_text("У меня какие-то проблемы с ИИ сейчас — попробуй позже.")

async def echo_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Функция-обертка для регистрации в MessageHandler, предотвращает двойные вызовы."""
    await echo_logic(update, context)

# Создаем фильтр для текстовых сообщений, которые не являются командами, в личных чатах.
echo_filter = filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE

# Создаем сам обработчик, который мы будем импортировать в главном файле.
echo_handler = MessageHandler(echo_filter, echo_handler_func)
