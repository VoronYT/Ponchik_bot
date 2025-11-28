import logging
import time
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, filters

from config import ADMIN_ID, ALLOWED_GROUP_IDS
# Импортируем значение кулдауна из настроек группового обработчика
from .group_handler import REPLY_COOLDOWN

logger = logging.getLogger(__name__)

async def cdcheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показывает оставшееся время кулдауна для случайных ответов в группе.
    Доступно только для ADMIN_ID в личных сообщениях.
    """
    user = update.effective_user
    if user.id != ADMIN_ID:
        # Игнорируем команду, если ее вызвал не админ
        return

    if not ALLOWED_GROUP_IDS:
        await update.message.reply_text("Функция случайных ответов в группе не настроена (список ALLOWED_GROUP_IDS пуст).")
        return

    response_lines = ["<b>Статус кулдаунов в чатах:</b>"]

    for group_id in ALLOWED_GROUP_IDS:
        try:
            chat = await context.bot.get_chat(group_id)
            chat_title = chat.title
        except Exception:
            chat_title = f"Неизвестный чат ({group_id})"

        last_reply_time = context.application.chat_data.get(group_id, {}).get('last_random_reply_time', 0)
        
        if last_reply_time == 0:
            response_lines.append(f"• <i>{chat_title}</i>: бот еще не отвечал, кулдаун не активен.")
            continue

        time_since_last_reply = time.time() - last_reply_time
        remaining_cooldown = REPLY_COOLDOWN - time_since_last_reply

        if remaining_cooldown > 0:
            response_lines.append(f"• <i>{chat_title}</i>: кулдаун активен. Осталось <b>{int(remaining_cooldown)}</b> сек.")
        else:
            response_lines.append(f"• <i>{chat_title}</i>: кулдаун не активен. Бот готов отвечать.")

    await update.message.reply_text("\n".join(response_lines), parse_mode='HTML')


cdcheck_handler = CommandHandler("cdcheck", cdcheck_command, filters=filters.ChatType.PRIVATE)