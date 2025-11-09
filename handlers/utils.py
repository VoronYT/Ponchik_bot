import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import BLACKLIST

logger = logging.getLogger(__name__)

def check_blacklist(func):
    """
    Декоратор для проверки, не находится ли пользователь в черном списке.
    Если пользователь в черном списке, бот ответит отказом и прекратит обработку команды.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user.id in BLACKLIST:
            logger.warning(f"Заблокированный пользователь пытается использовать бота: {user.id} (@{user.username})")
            await update.message.reply_text(
                "Извините, но вам был ограничен доступ к функциям этого бота. "
                "Если вы считаете, что это ошибка, свяжитесь с Вороном - https://vk.com/voronthestalker"
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper