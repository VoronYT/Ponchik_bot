import logging
import random
import asyncio
from telegram import Update, ChatMember
from telegram.ext import ContextTypes, ChatMemberHandler

from config import ALLOWED_GROUP_IDS
logger = logging.getLogger(__name__)

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Отслеживает изменения в статусе участников чата.
    Реагирует, когда пользователя блокируют (банят).
    """
    # Список фраз для реакции на бан (теперь прописан в коде)
    ban_reaction_phrases = [
        "Пользователь {user_full_name} был забанен! Туда ему и дорога!",
        "А вот и полетел в бан {user_full_name}! Кто-то расстроен?",
        "{user_full_name} был забанен. Туда его нахер!",
        "Был забанен {user_full_name}... Эх, жаль (нет)",
        "{user_full_name} улетел в бан. Ибо нехрен выделываться!"
    ]
    chat_id = update.effective_chat.id

    if ALLOWED_GROUP_IDS and int(chat_id) not in ALLOWED_GROUP_IDS:
        # Если список разрешенных групп задан и текущей группы в нем нет - выходим.
        return

    if not update.chat_member or not update.chat_member.new_chat_member:
        # Если в обновлении нет нужной информации, выходим.
        return

    # Получаем информацию о старом и новом статусе участника
    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    user = update.chat_member.new_chat_member.user

    # Проверяем, что новый статус - "забанен", а старый - нет.
    # Это гарантирует, что мы реагируем именно на событие бана, а не на другие изменения.
    if new_status == ChatMember.BANNED and old_status != ChatMember.BANNED:
        # Выбираем случайную фразу из списка
        random_phrase = random.choice(ban_reaction_phrases)
        # Форматируем сообщение, подставляя имя пользователя
        message_to_send = random_phrase.format(user_full_name=user.full_name)

        logger.info(f"Пользователь {user.full_name} ({user.id}) был забанен в чате {update.effective_chat.title} ({update.effective_chat.id}). Отправка сообщения через 1 секунду.")
        
        # Добавляем задержку в 1 секунду
        await asyncio.sleep(1)
        
        # Отправляем сообщение в чат о бане
        await update.effective_chat.send_message(message_to_send)


# Создаем обработчик, который будет срабатывать на любые изменения в составе чата
ban_reply = ChatMemberHandler(track_chats, ChatMemberHandler.ANY_CHAT_MEMBER)
