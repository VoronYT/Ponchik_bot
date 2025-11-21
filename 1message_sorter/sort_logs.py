import re
from collections import defaultdict
import os
from datetime import datetime

def sort_log_file(input_filename: str, output_filename: str):
    """
    Фильтрует и сортирует лог-файл, создавая читаемый диалог "вопрос-ответ".
    Служебные логи (Token Usage и т.д.) собираются в отдельный раздел.
    """
    # Регулярные выражения для поиска вопросов и ответов в логах.
    # Используем DOTALL для обработки многострочных логов
    # ВАЖНО: Логи с Railway могут не содержать закрывающей кавычки, поэтому её опциональна
    # Вопрос: 2025-11-08 15:20:12 - [РУ]Voron (12345) написал: 'Привет, Пончик!' 
    # или: 2025-11-08 15:20:12 - [РУ]Voron (12345) написал: 'Привет, Пончик
    question_pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - \[РУ\]([^(]+) \(\d+\) написал: '((?:[^']|\\')*)(?:'|$)",
        re.DOTALL
    )
    # Ответ: 2025-11-08 15:20:15 - [РУ]Бот ответил Voron (12345) (модель: llama): 'Здарова...' или без кавычки в конце
    answer_pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - \[РУ\]Бот ответил ([^(]+) \(\d+\).*?\(модель: ([^)]+)\)(?:\s*(\(token usage:\s*\d+\)))?.*?: '((?:[^']|\\')*?)(?:'|$)",
        re.DOTALL
    )

    # Словарь для хранения вопросов, на которые еще не было ответа.
    # Используем defaultdict(list), чтобы хранить несколько вопросов от одного юзера.
    pending_questions = defaultdict(list)
    # Словарь для хранения всех диалогов, сгруппированных по пользователю (все типы вместе).
    all_dialogs = defaultdict(list)
    # Список для сбора служебных логов (Token Usage и т.д.), которые не должны быть в диалогах
    service_logs = []

    print(f"Читаю файл '{input_filename}'...")

    try:
        with open(input_filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Разбиваем логи по логам Railway (начинаются с ISO timestamp: YYYY-MM-DDTHH:MM:SS.microseconds Z)
        # или по логам, начинающимся с YYYY-MM-DD HH:MM:SS
        # Используем lookahead для разделения, оставляя разделитель в начале каждого лога
        log_chunks = re.split(r'(?=\d{4}-\d{2}-\d{2}[T ])', content)
        
        for log_chunk in log_chunks:
            if not log_chunk.strip():
                continue
                
            # Каждый log_chunk может быть многострочным
            question_match = question_pattern.search(log_chunk)
            answer_match = answer_pattern.search(log_chunk)

            if question_match:
                # Нашли вопрос пользователя
                timestamp = question_match.group(1)
                username = question_match.group(2).strip()
                question_text = question_match.group(3)
                # Сохраняем вопрос вместе с его временной меткой
                pending_questions[username].append((timestamp, question_text))

            elif answer_match:
                # Нашли ответ бота
                timestamp = answer_match.group(1)
                username = answer_match.group(2).strip()
                model_used = answer_match.group(3)
                token_usage = answer_match.group(4) or ""
                answer_text = answer_match.group(5)

                # --- УЛУЧШЕННАЯ ЛОГИКА СОПОСТАВЛЕНИЯ ---
                # Ищем самый последний вопрос, который был задан ДО этого ответа.
                # Это решает проблему, когда ответы приходят не по порядку или не на все вопросы.
                best_match_index = -1
                for i, (q_ts, q_text) in enumerate(pending_questions[username]):
                    if q_ts < timestamp:
                        best_match_index = i
                    else:
                        # Вопросы отсортированы по времени, так что дальше можно не искать.
                        break
                
                # Если ответ выглядит как служебная ошибка/сообщение о лимите —
                # считаем его неответом и перемещаем в блок НЕОТВЕЧЕННЫХ,
                # чтобы такие пары оказались внизу итогового файла.
                error_phrases = {
                    "Хм, чёт у меня какие-то неполадки... Напиши потом.",
                    "Мля, я заманался с тобой болтать. Приходи в другой раз. (токены закончились, напиши через несколько часов)"
                }
                answer_lower = answer_text.lower()
                is_error_response = any(phrase in answer_text for phrase in error_phrases) or any(k in answer_lower for k in ("токен", "токены", "неполад", "напиши потом"))

                if best_match_index != -1:
                    # Мы нашли подходящий вопрос. Извлекаем его.
                    question_timestamp, question_text = pending_questions[username].pop(best_match_index)
                    if is_error_response:
                        # Помещаем в общий список с пометкой об ошибке
                        dialog_entry = (
                            f"({question_timestamp})\n"
                            f"👤 Пользователь: {username}\n"
                            f"❓ Вопрос: {question_text}\n"
                            f"🤖 Ответ: [ОШИБКА] {answer_text}\n\n"
                        )
                        all_dialogs[username].append((question_timestamp, dialog_entry))
                    else:
                        # Включаем (token usage: N) если он присутствует в исходном логе
                        tu_part = f" {token_usage}" if token_usage else ""
                        dialog_entry = (
                            f"({question_timestamp})\n"
                            f"👤 Пользователь: {username}\n"
                            f"❓ Вопрос: {question_text}\n"
                            f"🤖 Ответ (модель: {model_used}{tu_part}): {answer_text}\n\n"
                        )
                        all_dialogs[username].append((question_timestamp, dialog_entry))
            else:
                # Это служебный лог (Token Usage, попытка без подтверждения возраста и т.д.)
                # Сохраняем его для справочной информации
                if log_chunk.strip():  # Пропускаем пустые строки
                    service_logs.append(log_chunk)

        # --- НОВЫЙ ШАГ: Обработка оставшихся вопросов без ответов ---
        # После обработки всего файла, проверяем, остались ли неотвеченные вопросы.
        for username, questions in pending_questions.items():
            if questions:
                for question_timestamp, question_text in questions:
                    dialog_entry = (
                        f"({question_timestamp})\n"
                        f"👤 Пользователь: {username}\n"
                        f"❓ Вопрос: {question_text}\n"
                        f"🤖 Ответ: [НЕТ ОТВЕТА]\n\n"
                    )
                    # Добавляем в основной список вместе с остальными диалогами
                    all_dialogs[username].append((question_timestamp, dialog_entry))

        # --- ФИНАЛЬНЫЙ ШАГ: Сборка и запись результата ---
        # Группируем все диалоги по пользователям и сортируем
        final_output = []
        total_dialogs = 0

        sorted_usernames = sorted(all_dialogs.keys())
        for i, username in enumerate(sorted_usernames):
            # Добавляем заголовок с именем пользователя
            final_output.append(f"\n{'*'*50}\n")
            final_output.append(f"👤 ПОЛЬЗОВАТЕЛЬ: {username}\n")
            final_output.append(f"{'*'*50}\n\n")
            
            # Сортируем диалоги пользователя по времени
            dialogs = sorted(all_dialogs[username], key=lambda x: x[0])
            final_output.extend([dialog[1] for dialog in dialogs])
            total_dialogs += len(dialogs)

        # Добавляем служебные логи в конец (для справки)
        if service_logs:
            final_output.append(f"\n\n{'='*60}\n")
            final_output.append("📋 СЛУЖЕБНЫЕ ЛОГИ (Service Logs - не вошли в диалоги)\n")
            final_output.append(f"{'='*60}\n\n")
            final_output.extend(service_logs)

        print(f"Обработка завершена. Найдено {total_dialogs} диалогов, {len(service_logs)} служебных логов.")

        with open(output_filename, 'w', encoding='utf-8') as f:
            f.writelines(final_output)
        
        print(f"Результат сохранен в файл '{output_filename}'.")

    except FileNotFoundError:
        print(f"Ошибка: Файл '{input_filename}' не найден. Убедитесь, что он находится в этой же папке.")
    except Exception as e:
        print(f"Произошла непредвиденная ошибка: {e}")


if __name__ == "__main__":
    # Определяем директорию, в которой находится сам скрипт.
    # Это делает скрипт независимым от того, из какой папки его запускают.
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Формируем полные пути к файлам
    input_log_file = os.path.join(script_dir, "input.txt")
    output_dialog_file = os.path.join(script_dir, "sorted_dialogs.txt")
    
    sort_log_file(input_log_file, output_dialog_file)