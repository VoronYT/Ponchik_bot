import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, filters
from datetime import date, timedelta

from database import get_top_users_for_date, get_overall_user_stats_for_date
from config import ADMIN_ID

logger = logging.getLogger(__name__)

async def topusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Команда /topusers: предлагает выбрать день (сегодня/вчера/позавчера) и показывает топ-20 пользователей
    по количеству запросов за выбранный день.
    Доступна только админу.
    """
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        logger.warning(f"Пользователь {user_id} попытался получить доступ к команде /topusers.")
        await update.message.reply_text("Эта команда доступна только админу.")
        return

    today = date.today()
    keyboard = [
        [
            InlineKeyboardButton("Сегодня", callback_data=f"topusers_{today.strftime('%Y-%m-%d')}"),
            InlineKeyboardButton("Вчера", callback_data=f"topusers_{(today - timedelta(days=1)).strftime('%Y-%m-%d')}"),
        ],
        [
            InlineKeyboardButton("Позавчера", callback_data=f"topusers_{(today - timedelta(days=2)).strftime('%Y-%m-%d')}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите дату для просмотра топа пользователей:", reply_markup=reply_markup)


async def topusers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Extract date string from callback data like 'topusers_2025-11-11'
    try:
        date_str = query.data.split('_')[1]
    except Exception:
        await query.edit_message_text("Неверные данные.")
        return

    logger.info(f"Администратор запросил топ пользователей за {date_str}.")

    # Получаем данные для топа и для общей статистики
    top_users = get_top_users_for_date(date_str, limit=20)
    overall_stats = get_overall_user_stats_for_date(date_str)

    if not top_users:
        await query.edit_message_text(f"За {date_str} нет данных по пользователям.")
        return

    # Рассчитываем средние значения
    unique_users_count = overall_stats.get("unique_users_count", 0)
    avg_requests = (overall_stats.get("total_requests", 0) / unique_users_count) if unique_users_count > 0 else 0
    avg_tokens = (overall_stats.get("total_tokens", 0) / unique_users_count) if unique_users_count > 0 else 0

    # Формируем сообщение
    header_lines = [
        f"🏆 Топ пользователей за {date_str}",
        "", # Пустая строка для отступа
        f"👥 Всего уникальных пользователей: {unique_users_count}",
        f"📈 Среднее кол-во запросов на пользователя: {avg_requests:.1f}",
        f"🪙 Среднее кол-во токенов на пользователя: {avg_tokens:,.0f}".replace(',', ' '),
        "", # Пустая строка для отступа
        f"(по количеству запросов, топ {len(top_users)})",
        "---"
    ]

    user_lines = []
    for idx, row in enumerate(top_users, start=1):
        username = row.get('username') or 'unknown'
        requests = row.get('requests', 0)
        total_tokens = row.get('total_tokens') or 0
        # форматируем: 1. @username (или id) — 123 запр., 4 567 ток.
        user_lines.append(f"{idx}. {username} — {requests} запр., {total_tokens:,} ток.")

    message = "\n\n".join(header_lines) + "\n\n" + "\n\n".join(user_lines)

    await query.edit_message_text(message)


topusers_handler = CommandHandler("topusers", topusers_command, filters=filters.ChatType.PRIVATE)
topusers_callback_handler = CallbackQueryHandler(topusers_callback, pattern="^topusers_")
