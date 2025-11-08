import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, filters

logger = logging.getLogger(__name__)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Очищает историю диалога с ботом."""
    user_id = update.effective_user.id
    if context.user_data:
        context.user_data.clear()
        logger.info(f"Все данные для пользователя {user_id} были очищены.")
        await update.message.reply_text("Все твои данные стёрты. Нажми /start, чтобы начать заново.")
    else:
        await update.message.reply_text("Стирать нечего, я тебя и так не помню.")

async def confirm_age_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатие на кнопку подтверждения возраста."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    context.user_data["age_verified"] = True
    logger.info(f"Пользователь {user.full_name} ({user.id}) подтвердил свой возраст.")

    # Убираем кнопку из сообщения, оставляя только текст.
    await query.edit_message_reply_markup(reply_markup=None)

# Создаем обработчик для команды /reset
reset_handler = CommandHandler("reset", reset, filters=filters.ChatType.PRIVATE)

# Создаем обработчик для кнопки подтверждения возраста
confirm_age_handler = CallbackQueryHandler(confirm_age_callback, pattern="^confirm_age$")
