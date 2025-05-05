import requests
import time
import os
import re
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask, render_template, request, redirect, url_for, session, jsonify


# --- Загрузка Настроек ---
load_dotenv()
API_URL = os.getenv('TOKEN')
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
RANGE_NAME = os.getenv('RANGE_NAME')

# Настройки по умолчанию для веб-интерфейса
DEFAULT_MESSAGE_TEXT = "Привет! Это тестовая массовая рассылка."
DEFAULT_DELAY_BETWEEN_MESSAGES = 1  # Секунда по умолчанию

# Области доступа для Google Sheets API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# --- Flask Приложение ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')


# --- Функции ---

def log_message(logs_list, message, level="info"):
    """Добавляет сообщение в список логов для вывода в веб-интерфейс."""
    print(message)  # Оставляем вывод в консоль сервера для отладки
    logs_list.append({"message": message, "level": level})


def format_phone_number(raw_number, logs_list):
    """Форматирует номер телефона и логирует процесс."""
    if not isinstance(raw_number, str):
        log_message(
            logs_list, f"  Предупреждение: Получено не строковое значение: {raw_number}. Пропускаем.", "warning")
        return None

    digits = re.sub(r'\D', '', raw_number)

    if len(digits) == 11:
        if digits.startswith('8'):
            formatted = '7' + digits[1:]
            log_message(
                logs_list, f"    Форматирование: '{raw_number}' -> '{formatted}' (Замена 8 на 7)")
            return formatted
        elif digits.startswith('7'):
            log_message(
                logs_list, f"    Форматирование: '{raw_number}' -> '{digits}' (Уже верный формат)")
            return digits
        else:
            log_message(
                logs_list, f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 11 цифр, но начинается не с 7 или 8. Пропускаем.", "warning")
            return None
    elif len(digits) == 10:
        formatted = '7' + digits
        log_message(
            logs_list, f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 10 цифр. Добавляем '7' в начало -> '{formatted}'", "warning")
        return formatted
    else:
        log_message(
            logs_list, f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет неверную длину ({len(digits)}). Пропускаем.", "warning")
        return None


def get_phone_numbers_from_sheet(service, spreadsheet_id, range_name, logs_list):
    """Читает номера из Google Sheets с использованием переданного объекта service."""
    try:
        log_message(
            logs_list, f"Чтение данных из таблицы ID: {spreadsheet_id}, Диапазон: {range_name}")
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        values = result.get('values', [])

        formatted_numbers = []
        if not values:
            log_message(
                logs_list, 'Номера телефонов не найдены в указанном диапазоне.', "warning")
            return []
        else:
            log_message(
                logs_list, f"Найдено строк в таблице: {len(values)}. Начинаем обработку и форматирование:")
            try:
                start_row_match = re.search(r'(\d+):', range_name)
                start_row = int(start_row_match.group(1)
                                ) if start_row_match else 1
            except:
                start_row = 1

            for i, row in enumerate(values):
                current_row_num = start_row + i
                if row and row[0] and str(row[0]).strip():
                    raw_number = str(row[0]).strip()
                    log_message(
                        logs_list, f"  Строка {current_row_num}: Читаем '{raw_number}'")
                    formatted = format_phone_number(raw_number, logs_list)
                    if formatted:
                        if formatted not in formatted_numbers:
                            formatted_numbers.append(formatted)
                            log_message(
                                logs_list, f"    -> Добавлен валидный номер: {formatted}", "success")
                        else:
                            log_message(
                                logs_list, f"    -> Дубликат номера {formatted}, пропускаем.", "warning")
                else:
                    log_message(
                        logs_list, f"  Строка {current_row_num}: Пустая или некорректная строка, пропускаем.", "info")

            log_message(logs_list, "-" * 20)
            log_message(
                logs_list, f"Итоговый список уникальных валидных номеров для отправки ({len(formatted_numbers)} шт.).")
            log_message(logs_list, "-" * 20)
            return formatted_numbers

    except HttpError as err:
        log_message(
            logs_list, f"Произошла ошибка Google API при чтении номеров: {err}", "error")
        return None
    except Exception as e:
        log_message(
            logs_list, f"Произошла непредвиденная ошибка при чтении номеров: {e}", "error")
        return None


def send_message(api_url, phone_number, message, logs_list):
    """Отправляет сообщение через API и логирует результат."""
    chat_id = f"{phone_number}@c.us"
    payload = {
        "chatId": chat_id,
        "message": message,
    }
    headers = {'Content-Type': 'application/json'}

    try:
        log_message(logs_list, f"Отправка сообщения на {chat_id}...")
        # Увеличиваем таймаут, т.к. API может отвечать не мгновенно
        response = requests.post(
            api_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()  # Вызовет исключение для кодов 4xx/5xx

        response_text = "Не удалось декодировать ответ API"
        try:
            # Пытаемся декодировать ответ, как в оригинальном коде
            response_text = response.text.encode('latin1').decode('utf8')
        except UnicodeDecodeError:
            try:
                response_text = response.text.encode('utf-8').decode('utf-8')
            except Exception:
                response_text = response.text  # Если ничего не помогло, показываем как есть

        log_message(
            logs_list, f"  Успешно отправлено на {chat_id}. Ответ API: {response_text}", "success")
        return True

    except requests.exceptions.Timeout:
        log_message(
            logs_list, f"  Ошибка: Превышено время ожидания ответа от API при отправке на {chat_id}.", "error")
        return False
    except requests.exceptions.RequestException as e:
        error_msg = f"  Ошибка отправки на {chat_id}: {e}"
        response_text = ""
        if e.response is not None:
            try:
                response_text = e.response.text.encode('latin1').decode('utf8')
            except UnicodeDecodeError:
                try:
                    response_text = e.response.text.encode(
                        'utf-8').decode('utf-8')
                except Exception:
                    response_text = e.response.text
            error_msg += f" | Ответ сервера ({e.response.status_code}): {response_text}"
        log_message(logs_list, error_msg, "error")
        return False
    except Exception as e:
        log_message(
            logs_list, f"  Непредвиденная ошибка при отправке на {chat_id}: {e}", "error")
        return False


def create_google_service(logs_list):
    """Создает и возвращает объект service для Google API."""
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        log_message(
            logs_list, f"Ошибка: Файл сервисного аккаунта не найден или не указан: {SERVICE_ACCOUNT_FILE}", "error")
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        log_message(
            logs_list, "Успешная аутентификация в Google Sheets API (для чтения/записи).")
        return service
    except Exception as e:
        log_message(
            logs_list, f"Ошибка аутентификации в Google Sheets API: {e}", "error")
        return None


      
def create_new_report_sheet(service, spreadsheet_id, sheet_title, logs_list):
    """Создает новый лист в Google Таблице для отчета (в конце).""" # Обновили docstring
    try:
        log_message(logs_list, f"Попытка создать новый лист с именем: '{sheet_title}' (в конце)") # Обновили лог
        requests_body = {
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': sheet_title
                    }
                }
            }]
        }
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=requests_body
        ).execute()
        # Можно немного уточнить лог, что лист добавлен в конец
        log_message(logs_list, f"Успешно создан лист отчета: '{sheet_title}' (добавлен в конец)", "success")
        return True
    except HttpError as err:
        # Проверяем, возможно лист уже существует
        if 'already exists' in str(err):
             log_message(logs_list, f"Предупреждение: Лист '{sheet_title}' уже существует. Запись будет вестись в него.", "warning")
             return True # Считаем успехом, если лист уже есть
        else:
             log_message(logs_list, f"Ошибка Google API при создании листа '{sheet_title}': {err}. Убедитесь, что у сервисного аккаунта есть права редактора.", "error")
             return False
    except Exception as e:
        log_message(logs_list, f"Непредвиденная ошибка при создании листа '{sheet_title}': {e}", "error")
        return False

    


def write_report_to_sheet(service, spreadsheet_id, sheet_title, data_rows, logs_list):
    """Записывает строки данных в указанный лист."""
    try:
        range_to_write = f"'{sheet_title}'!A1"  # Начинаем с A1
        body = {
            'values': data_rows
        }
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_to_write,
            valueInputOption='USER_ENTERED',  # Обрабатывать данные как введенные пользователем
            insertDataOption='INSERT_ROWS',  # Вставлять строки, а не перезаписывать
            body=body
        ).execute()
        log_message(
            logs_list, f"Записано строк в отчет '{sheet_title}': {len(data_rows)} (Результат API: {result.get('updates').get('updatedCells')} ячеек)")
        return True
    except HttpError as err:
        log_message(
            logs_list, f"Ошибка Google API при записи данных в лист '{sheet_title}': {err}", "error")
        return False
    except Exception as e:
        log_message(
            logs_list, f"Непредвиденная ошибка при записи данных в лист '{sheet_title}': {e}", "error")
        return False


# --- Маршруты Flask ---
@app.route('/check_access', methods=['GET'])
def check_google_sheet_access():
    """Проверяет доступ к Google Sheet (только чтение для этой проверки)."""
    logs_check = []
    service_read_only = None

    # Создаем сервис с правами ТОЛЬКО НА ЧТЕНИЕ для проверки
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        return jsonify({'status': 'error', 'message': f'Файл ключа {SERVICE_ACCOUNT_FILE} не найден'})
    if not SPREADSHEET_ID or SPREADSHEET_ID == 'YOUR_SPREADSHEET_ID':
        return jsonify({'status': 'error', 'message': 'Не настроен ID таблицы (SPREADSHEET_ID)'})
    if not RANGE_NAME:
        return jsonify({'status': 'error', 'message': 'Не настроен диапазон (RANGE_NAME)'})

    try:
        creds_read = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
        service_read_only = build('sheets', 'v4', credentials=creds_read)
        log_message(
            logs_check, "Check Access: Google Sheets API (read-only) authentication successful.")

        sheet = service_read_only.spreadsheets()
        log_message(
            logs_check, f"Check Access: Reading from Sheet ID: {SPREADSHEET_ID}, Range: {RANGE_NAME}")
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])
        num_rows = len(values)
        log_message(
            logs_check, f"Check Access: Successfully read data. Found {num_rows} rows in range.")

        # Дополнительная проверка возможности записи (не выполняя запись)
        # Это менее надежно, но может дать подсказку пользователю
        try:
            creds_write = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets'])
            service_write_check = build(
                'sheets', 'v4', credentials=creds_write)
            # Просто пытаемся получить метаданные таблицы, что требует прав записи
            service_write_check.spreadsheets().get(
                spreadsheetId=SPREADSHEET_ID, fields='properties').execute()
            write_access_message = "Права на запись (редактор) скорее всего есть."
            write_access_status = "success"
        except HttpError as write_err:
            if write_err.resp.status == 403:
                write_access_message = "Ошибка: Нет прав на запись (редактор). Отчеты создаваться не будут!"
                write_access_status = "error"
            else:
                write_access_message = f"Не удалось проверить права на запись: {write_err}"
                write_access_status = "warning"
        except Exception as write_e:
            write_access_message = f"Не удалось проверить права на запись (другая ошибка): {write_e}"
            write_access_status = "warning"

        return jsonify({'status': 'success', 'count': num_rows, 'write_check': {'message': write_access_message, 'status': write_access_status}})

    except HttpError as err:
        reason = "Проверьте права доступа к таблице или правильность ID/Диапазона."
        try:
            if err.resp.status == 403:
                reason = "Доступ к чтению запрещен (403). Убедитесь, что email сервисного аккаунта добавлен хотя бы в читатели таблицы."
            elif err.resp.status == 404:
                reason = "Таблица не найдена (404). Проверьте правильность SPREADSHEET_ID."
            else:
                reason = f"Ошибка Google API ({err.resp.status}). {err._get_reason()}"
        except Exception:
            pass
        return jsonify({'status': 'error', 'message': reason})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Непредвиденная ошибка: {e}'})


@app.route('/')
def index():
    error = None
    if not API_URL or API_URL == "TOKEN":
        error = "Ошибка: Не указан API_URL в настройках (.env)!"
    # Убираем проверки Google Sheets отсюда, есть кнопка
    return render_template('index.html',
                           default_message=DEFAULT_MESSAGE_TEXT,
                           default_delay=DEFAULT_DELAY_BETWEEN_MESSAGES,
                           error=error)


@app.route('/send', methods=['POST'])
def send_messages_route():
    logs = []
    log_message(logs, "Запрос на запуск рассылки получен.")
    service = None  # Объект для работы с Google API
    report_sheet_title = None  # Имя листа для отчета
    reporting_enabled = False  # Флаг, удалось ли подготовить отчет

    # Проверка API_URL
    if not API_URL or API_URL == "TOKEN":
        log_message(
            logs, "Критическая ошибка: Не указан API_URL в .env!", "error")
        return render_template('results.html', logs=logs, successful_sends=0, failed_sends=0, total_processed=0, message_text="N/A", delay=0, report_info=None)

    message_text = request.form.get('message', DEFAULT_MESSAGE_TEXT)
    try:
        delay = int(request.form.get('delay', DEFAULT_DELAY_BETWEEN_MESSAGES))
        if delay < 0:
            delay = 0
    except ValueError:
        delay = DEFAULT_DELAY_BETWEEN_MESSAGES
        log_message(
            logs, f"Предупреждение: Некорректное значение задержки, используется значение по умолчанию: {delay} сек.", "warning")

    log_message(logs, f"Текст сообщения для отправки: \"{message_text}\"")
    log_message(logs, f"Задержка между сообщениями: {delay} сек.")

    # 1. Создаем Google Service для чтения и записи
    service = create_google_service(logs)
    if not service:
        log_message(
            logs, "Не удалось аутентифицироваться в Google API. Рассылка будет выполнена без чтения номеров из таблицы и без отчета.", "error")
        # В этом случае phone_numbers будет None, и рассылка не запустится
        phone_numbers = None
    else:
        # 2. Читаем номера из таблицы
        phone_numbers = get_phone_numbers_from_sheet(
            service, SPREADSHEET_ID, RANGE_NAME, logs)

    successful_sends = 0
    failed_sends = 0
    total_processed = 0
    # Информация об отчете для шаблона
    report_info = {"sheet_title": None, "status": "Отключено"}

    if phone_numbers is None:
        log_message(
            logs, "Не удалось получить номера телефонов из таблицы или произошла ошибка API. Рассылка отменена.", "error")
    elif not phone_numbers:
        log_message(
            logs, "Список валидных номеров для отправки пуст. Рассылка не будет запущена.", "warning")
    else:
        # --- Подготовка к записи отчета ---
        if service:  # Если сервис Google API был успешно создан
            report_sheet_title = datetime.now().strftime("%d.%m.%y %H:%M:%S")
            report_info["sheet_title"] = report_sheet_title
            if create_new_report_sheet(service, SPREADSHEET_ID, report_sheet_title, logs):
                # Двойные скобки для .append
                header_row = [["№", "Number", "Name", "Status", "Time"]]
                if write_report_to_sheet(service, SPREADSHEET_ID, report_sheet_title, header_row, logs):
                    reporting_enabled = True
                    report_info["status"] = "Активно"
                    log_message(
                        logs, f"Отчет будет записываться в лист '{report_sheet_title}'")
                else:
                    report_info["status"] = "Ошибка записи заголовка"
                    log_message(
                        logs, "Не удалось записать заголовок в лист отчета. Отчетность будет отключена.", "error")
            else:
                report_info["status"] = "Ошибка создания листа"
                log_message(
                    logs, "Не удалось создать лист для отчета. Отчетность будет отключена.", "error")
        else:
            report_info["status"] = "Сервис Google недоступен"
            log_message(
                logs, "Сервис Google Sheets недоступен, отчетность отключена.", "warning")
        # --- Конец подготовки отчета ---

        total_processed = len(phone_numbers)
        log_message(logs, f"Начинаем отправку {total_processed} сообщений...")

        # Будем накапливать строки для пакетной записи (опционально, можно писать по одной)
        rows_to_report = []

        for i, number in enumerate(phone_numbers):
            log_message(logs, "-" * 20)
            log_message(
                logs, f"Сообщение {i + 1} из {total_processed} на номер {number}")

            # Отправка сообщения
            success = send_message(API_URL, number, message_text, logs)

            # Запись в отчет (если включено)
            if reporting_enabled and service and report_sheet_title:
                report_time = datetime.now().strftime("%H:%M:%S")
                status = "Отправлено" if success else "Не отправлено"
                report_row = [i + 1, number, "", status,
                              report_time]  # Name пока пустое
                # Пишем строку сразу
                write_report_to_sheet(
                    service, SPREADSHEET_ID, report_sheet_title, [report_row], logs)
                # Или накапливаем для пакетной записи в конце (менее надежно при сбоях)
                # rows_to_report.append(report_row)

            if success:
                successful_sends += 1
            else:
                failed_sends += 1

            if i < total_processed - 1 and delay > 0:
                log_message(logs, f"  Пауза {delay} сек...")
                time.sleep(delay)

        # Если накапливали строки для отчета, записать их сейчас
        # if reporting_enabled and service and report_sheet_title and rows_to_report:
        #    log_message(logs, f"Запись {len(rows_to_report)} строк в итоговый отчет...")
        #    write_report_to_sheet(service, SPREADSHEET_ID, report_sheet_title, rows_to_report, logs)

        log_message(logs, "=" * 30)
        log_message(logs, "Рассылка завершена.")
        log_message(
            logs, f"Итого: Успешно отправлено: {successful_sends}, Не удалось отправить: {failed_sends}")
        if reporting_enabled:
            log_message(
                logs, f"Отчет сохранен в Google Таблице на листе: '{report_sheet_title}'")
        log_message(logs, "=" * 30)

    return render_template('results.html',
                           logs=logs,
                           successful_sends=successful_sends,
                           failed_sends=failed_sends,
                           total_processed=total_processed,
                           message_text=message_text,
                           delay=delay,
                           report_info=report_info)  # Передаем информацию об отчете


# --- Запуск приложения ---
if __name__ == '__main__':
    print("Проверка основных настроек...")
    # Проверяем только критичные для запуска Flask
    if not API_URL or API_URL == "TOKEN":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан API_URL в .env! Рассылка работать не будет.")
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан или не найден файл SERVICE_ACCOUNT_FILE: '{SERVICE_ACCOUNT_FILE}' в .env! Чтение номеров и отчетность работать не будут.")
    if not SPREADSHEET_ID or SPREADSHEET_ID == 'YOUR_SPREADSHEET_ID':
        print("!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан SPREADSHEET_ID в .env! Чтение номеров и отчетность работать не будут.")
    else:
        print("Основные настройки (.env) выглядят корректно.")

    print(f"Запуск Flask приложения... Откройте http://127.0.0.1:5000 (или http://<ваш_ip>:5000) в браузере.")
    # debug=False для продакшена, host='0.0.0.0' для доступа из сети
    app.run(host='0.0.0.0', port=5000, debug=True)
