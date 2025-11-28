import logging
import random
import time
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from telegram.constants import ChatAction

from config import ALLOWED_GROUP_IDS, ADMIN_ID
from services.ai_service import get_ai_response
from services.content_filter import filter_and_validate_response

logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
# Шанс ответа (1 к N). Чем больше число, тем реже отвечает бот.
REPLY_CHANCE = 3
# Кулдаун в секундах (30 минут)
REPLY_COOLDOWN = 30 * 60

async def random_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Случайно отвечает на сообщения в разрешенных группах с кулдауном.
    """
    chat_id = update.effective_chat.id
    user = update.effective_user

    # 1. Проверяем, что сообщение пришло из разрешенной группы и не от бота
    if not user or user.is_bot or chat_id not in ALLOWED_GROUP_IDS:
        return

    # Новая проверка: игнорируем сообщения с медиа (фото, видео, стикеры и т.д.)
    if update.message and (update.message.photo or update.message.video or update.message.animation or update.message.document or update.message.audio or update.message.voice or update.message.sticker or update.message.video_note):
        return

    # 2. Проверяем кулдаун
    current_time = time.time()
    last_reply_time = context.chat_data.get('last_random_reply_time', 0)

    time_since_last_reply = current_time - last_reply_time
    if time_since_last_reply < REPLY_COOLDOWN:
        return # Кулдаун еще не прошел
    logger.info(f"[ГРУППА] Кулдаун закончен. Прошло {time_since_last_reply:.1f} сек.")

    # 3. Проверяем шанс ответа
    roll = random.randint(1, REPLY_CHANCE)
    if roll != 1:
        return # В этот раз не отвечаем

    # --- Логика ответа ---
    message_text = update.message.text
    if not message_text or len(message_text.strip()) < 3:
        return # Не отвечаем на слишком короткие сообщения или стикеры

    # 1. Бот берет сообщение в чате (название) от пользователя (никнейм, айди): (сообщение)
    logger.info(f"[ГРУППА] Бот берет сообщение в чате {update.effective_chat.title} от пользователя {user.full_name} ({user.id}): '{message_text}'")
    
    logger.info(f"[ГРУППА] Запрос отправлен в ИИ для чата {update.effective_chat.title}.")

    try:
        # Получаем историю чата (последние 4 сообщения)
        chat_history = context.chat_data.get("chat_history", [])
        chat_history.append({"role": "user", "content": message_text})
        chat_history = chat_history[-4:] # Ограничиваем историю

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # Получаем ответ от ИИ
        response = await get_ai_response(
            message_history=chat_history,
            tg_id=user.id,
            username=user.full_name
        )

        ai_message = response.get("message")
        logger.info(f"[ГРУППА] Запрос отправлен и получен ответ от ИИ.")
        if ai_message:
            # Фильтруем ответ на всякий случай
            final_response, was_filtered = filter_and_validate_response(ai_message, is_group_reply=True)

            # Проверяем, что ответ не был отфильтрован и не является отказом
            if not was_filtered:
                # Отправляем ответ, только если он не пустой
                if final_response:
                    await update.message.reply_text(final_response)
                    # Устанавливаем кулдаун ТОЛЬКО ПОСЛЕ успешной отправки
                    context.chat_data['last_random_reply_time'] = current_time
                    # 3. Бот ответил, старт кулдауна (время)
                    logger.info(f"[ГРУППА] Бот ответил в чате {update.effective_chat.title}: '{final_response}'. Старт кулдауна на {REPLY_COOLDOWN} сек.")

                    # Сохраняем историю
                    chat_history.append({"role": "assistant", "content": final_response})
                    context.chat_data["chat_history"] = chat_history
                else:
                    logger.info(f"[ГРУППА] Ответ ИИ для чата {chat_id} был пустым после фильтрации. Ответ не отправлен, кулдаун не установлен.")
            else:
                logger.info(f"[ГРУППА] Ответ ИИ для чата {chat_id} был отфильтрован. Ответ не отправлен, кулдаун не установлен.")
        else:
            logger.warning(f"[ГРУППА] ИИ вернул пустой ответ для чата {chat_id}.")

    except Exception as e:
        logger.exception(f"Ошибка при генерации случайного ответа в группе: {e}")
        # В случае ошибки кулдаун не устанавливается, поэтому бот сможет
        # попробовать ответить на следующее подходящее сообщение.


group_reply_handler = MessageHandler(
    # Разрешаем работать и в обычных группах, и в супергруппах
    filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP), random_group_reply
)