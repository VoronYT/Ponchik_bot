import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отвечает на медиафайлы сообщением о том, что бот их не распознает."""
    user = update.effective_user
    logger.info(f"Пользователь {user.full_name} ({user.id}) отправил медиафайл, который не поддерживается.")

    # Проверяем, подтвержден ли возраст, так как это общая проверка для всех взаимодействий
    if not context.user_data.get("age_verified"):
        logger.warning(f"Пользователь {user.full_name} ({user.id}) попытался отправить медиа без подтверждения возраста.")
        await update.message.reply_text("Сначала подтверди свой возраст, нажав /start.")
        return

    # Ответ в стиле Пончика
    response_text = "Сорян, но я пока не распознаю картинки, видео или аудио"
    await update.message.reply_text(response_text)

# Создаем фильтр для различных типов медиа в личных чатах.
media_filter = (
    filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE |
    filters.Sticker.ALL | filters.VIDEO_NOTE | filters.Document.ALL
) & filters.ChatType.PRIVATE

# Создаем сам обработчик, который мы будем импортировать в главном файле.
media_handler = MessageHandler(media_filter, handle_media)