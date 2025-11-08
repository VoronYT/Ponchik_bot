import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, filters

from config import SUPPORT_LINK

logger = logging.getLogger(__name__)

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет сообщение со ссылкой на поддержку."""
    user = update.effective_user
    logger.info(f"Пользователь {user.full_name} ({user.id}) запросил ссылку на поддержку.")

    text = "Если хочешь поддержать творчество Ворона, можешь сделать это по ссылке ниже. (Каждая копейка идёт на хавчик для меня!)"
    
    keyboard = [
        [InlineKeyboardButton("💰 Поддержать Ворона", url=SUPPORT_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup)

support_handler = CommandHandler("support", support_command, filters=filters.ChatType.PRIVATE)
