import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from telegram.constants import ChatAction

# Импортируем наш сервис для работы с ИИ
from services.ai_service import get_ai_response

logger = logging.getLogger(__name__)

async def echo_logic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отвечает на текстовое сообщение с помощью ИИ."""
    user = update.effective_user
    message_text = update.message.text
    logger.info(f"[РУ]{user.full_name} ({user.id}) написал: '{message_text}'")

    # Проверяем, подтвержден ли возраст, перед тем как отвечать
    if not context.user_data.get("age_verified"):
        logger.warning(f"Пользователь {user.full_name} ({user.id}) попытался написать боту без подтверждения возраста.")
        await update.message.reply_text("Сначала подтверди свой возраст, нажав /start.")
        return

    # Получаем или создаем историю сообщений для этого пользователя
    # context.user_data - это словарь, уникальный для каждого пользователя
    chat_history = context.user_data.get("chat_history", [])

    # Добавляем новое сообщение от пользователя в историю
    chat_history.append({"role": "user", "content": message_text})

    # Показываем индикатор "печатает..." для улучшения UX
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # **Оптимизация**: Ограничиваем историю, чтобы экономить токены.
    # Мы будем передавать в API только системный промпт и последние 10 сообщений.
    # Системный промпт добавляется в ai_service, поэтому здесь мы просто готовим историю.
    messages_to_send = chat_history[-10:]

    # Получаем ответ от ИИ и отправляем его пользователю
    # Передаем в API только ограниченную историю
    ai_response, used_model = await get_ai_response(messages_to_send, user.full_name)

    # Логируем ответ бота
    logger.info(f"[РУ]Бот ответил {user.full_name} ({user.id}) (модель: {used_model}): '{ai_response}'")

    # Добавляем ответ ИИ в историю
    chat_history.append({"role": "assistant", "content": ai_response})

    # Сохраняем обновленную историю обратно в user_data
    context.user_data["chat_history"] = chat_history

    await update.message.reply_text(ai_response)

async def echo_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Функция-обертка для регистрации в MessageHandler, предотвращает двойные вызовы."""
    await echo_logic(update, context)

# Создаем фильтр для текстовых сообщений, которые не являются командами, в личных чатах.
echo_filter = filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE

# Создаем сам обработчик, который мы будем импортировать в главном файле.
echo_handler = MessageHandler(echo_filter, echo_handler_func)
