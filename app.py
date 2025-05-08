import requests
import time
import os
import re
import random
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask, render_template, request, jsonify


# --- Загрузка Настроек ---
load_dotenv()
API_URL = os.getenv("TOKEN")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
RANGE_NAME = os.getenv("RANGE_NAME")
REPORT_SPREADSHEET_ID = os.getenv("REPORT_SPREADSHEET_ID")

# Настройки по умолчанию для веб-интерфейса
DEFAULT_MESSAGE_TEXT = ""
DEFAULT_DELAY_BETWEEN_MESSAGES = 5

# Области доступа для Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- Flask Приложение ---
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")


def log_message(logs_list, message, level="info"):
    print(message)
    logs_list.append({"message": message, "level": level})


def format_phone_number(raw_number, logs_list):
    if not isinstance(raw_number, str):
        log_message(
            logs_list,
            f"  Предупреждение: Получено не строковое значение: {raw_number}. Пропускаем.",
            "warning",
        )
        return None
    digits = re.sub(r"\D", "", raw_number)
    if len(digits) == 11:
        if digits.startswith("8"):
            formatted = "7" + digits[1:]
            log_message(
                logs_list,
                f"    Форматирование: '{raw_number}' -> '{formatted}' (Замена 8 на 7)",
            )
            return formatted
        elif digits.startswith("7"):
            log_message(
                logs_list,
                f"    Форматирование: '{raw_number}' -> '{digits}' (Уже верный формат)",
            )
            return digits
        else:
            log_message(
                logs_list,
                f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 11 цифр, но начинается не с 7 или 8. Пропускаем.",
                "warning",
            )
            return None
    elif len(digits) == 10:
        formatted = "7" + digits
        log_message(
            logs_list,
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 10 цифр. Добавляем '7' в начало -> '{formatted}'",
            "warning",
        )
        return formatted
    else:
        log_message(
            logs_list,
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет неверную длину ({len(digits)}). Пропускаем.",
            "warning",
        )
        return None


def get_phone_numbers_from_sheet(service, source_spreadsheet_id, range_name, logs_list):
    try:
        log_message(
            logs_list,
            f"Чтение данных из таблицы ID: {source_spreadsheet_id}, Диапазон: {range_name}",
        )
        sheet = service.spreadsheets()
        result = (
            sheet.values()
            .get(spreadsheetId=source_spreadsheet_id, range=range_name)
            .execute()
        )
        values = result.get("values", [])
        formatted_numbers = []
        if not values:
            log_message(
                logs_list,
                "Номера телефонов не найдены в указанном диапазоне.",
                "warning",
            )
            return []
        else:
            log_message(
                logs_list,
                f"Найдено строк в таблице: {len(values)}. Начинаем обработку и форматирование:",
            )
            try:
                start_row_match = re.search(r"(\d+):", range_name)
                start_row = int(start_row_match.group(1)) if start_row_match else 1
            except:
                start_row = 1
            for i, row in enumerate(values):
                current_row_num = start_row + i
                if row and row[0] and str(row[0]).strip():
                    raw_number = str(row[0]).strip()
                    log_message(
                        logs_list, f"  Строка {current_row_num}: Читаем '{raw_number}'"
                    )
                    formatted = format_phone_number(raw_number, logs_list)
                    if formatted:
                        if formatted not in formatted_numbers:
                            formatted_numbers.append(formatted)
                            log_message(
                                logs_list,
                                f"    -> Добавлен валидный номер: {formatted}",
                                "success",
                            )
                        else:
                            log_message(
                                logs_list,
                                f"    -> Дубликат номера {formatted}, пропускаем.",
                                "warning",
                            )
                else:
                    log_message(
                        logs_list,
                        f"  Строка {current_row_num}: Пустая или некорректная строка, пропускаем.",
                        "info",
                    )
            log_message(logs_list, "-" * 20)
            log_message(
                logs_list,
                f"Итоговый список уникальных валидных номеров для отправки ({len(formatted_numbers)} шт.).",
            )
            log_message(logs_list, "-" * 20)
            return formatted_numbers
    except HttpError as err:
        log_message(
            logs_list,
            f"Произошла ошибка Google API при чтении номеров из таблицы {source_spreadsheet_id}: {err}",
            "error",
        )
        return None
    except Exception as e:
        log_message(
            logs_list,
            f"Произошла непредвиденная ошибка при чтении номеров из таблицы {source_spreadsheet_id}: {e}",
            "error",
        )
        return None


def send_message(api_url, phone_number, message, logs_list):
    chat_id = f"{phone_number}@c.us"
    payload = {"chatId": chat_id, "message": message}
    headers = {"Content-Type": "application/json"}
    try:
        log_message(logs_list, f"Отправка сообщения на {chat_id}...")
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        response_text = "Не удалось декодировать ответ API"
        try:
            response_text = response.text.encode("latin1").decode("utf8")
        except UnicodeDecodeError:
            try:
                response_text = response.text.encode("utf-8").decode("utf-8")
            except Exception:
                response_text = response.text
        log_message(
            logs_list,
            f"  Успешно отправлено на {chat_id}. Ответ API: {response_text}",
            "success",
        )
        return True
    except requests.exceptions.Timeout:
        log_message(
            logs_list,
            f"  Ошибка: Превышено время ожидания ответа от API при отправке на {chat_id}.",
            "error",
        )
        return False
    except requests.exceptions.RequestException as e:
        error_msg = f"  Ошибка отправки на {chat_id}: {e}"
        response_text = ""
        if e.response is not None:
            try:
                response_text = e.response.text.encode("latin1").decode("utf8")
            except UnicodeDecodeError:
                try:
                    response_text = e.response.text.encode("utf-8").decode("utf-8")
                except Exception:
                    response_text = e.response.text
            error_msg += f" | Ответ сервера ({e.response.status_code}): {response_text}"
        log_message(logs_list, error_msg, "error")
        return False
    except Exception as e:
        log_message(
            logs_list,
            f"  Непредвиденная ошибка при отправке на {chat_id}: {e}",
            "error",
        )
        return False


def create_google_service(logs_list):
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        log_message(
            logs_list,
            f"Ошибка: Файл сервисного аккаунта не найден или не указан: {SERVICE_ACCOUNT_FILE}",
            "error",
        )
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        log_message(
            logs_list,
            "Успешная аутентификация в Google Sheets API (для чтения/записи).",
        )
        return service
    except Exception as e:
        log_message(
            logs_list, f"Ошибка аутентификации в Google Sheets API: {e}", "error"
        )
        return None


def create_new_report_sheet(service, target_spreadsheet_id, sheet_title, logs_list):
    """Создает новый лист в УКАЗАННОЙ Google Таблице для отчета."""
    try:
        log_message(
            logs_list,
            f"Попытка создать новый лист с именем: '{sheet_title}' в таблице ID: {target_spreadsheet_id}",
        )
        requests_body = {
            "requests": [
                {"addSheet": {"properties": {"title": sheet_title, "index": 0}}}
            ]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=target_spreadsheet_id, body=requests_body
        ).execute()
        log_message(
            logs_list,
            f"Успешно создан лист отчета: '{sheet_title}' в таблице ID: {target_spreadsheet_id}",
            "success",
        )
        return True
    except HttpError as err:
        if "already exists" in str(err).lower():  # Проверка на существование листа
            log_message(
                logs_list,
                f"Предупреждение: Лист '{sheet_title}' уже существует в таблице ID: {target_spreadsheet_id}. Запись будет вестись в него.",
                "warning",
            )
            return True
        else:
            log_message(
                logs_list,
                f"Ошибка Google API при создании листа '{sheet_title}' в таблице ID: {target_spreadsheet_id}: {err}. Убедитесь, что у сервисного аккаунта есть права редактора.",
                "error",
            )
            return False
    except Exception as e:
        log_message(
            logs_list,
            f"Непредвиденная ошибка при создании листа '{sheet_title}' в таблице ID: {target_spreadsheet_id}: {e}",
            "error",
        )
        return False


def write_report_to_sheet(
    service, target_spreadsheet_id, sheet_title, data_rows, logs_list
):
    """Записывает строки данных в указанный лист УКАЗАННОЙ таблицы."""
    try:
        range_to_write = f"'{sheet_title}'!A1"
        body = {"values": data_rows}
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=target_spreadsheet_id,
                range=range_to_write,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
        updated_cells = result.get("updates", {}).get("updatedCells", "N/A")
        log_message(
            logs_list,
            f"Записано строк в отчет '{sheet_title}' (таблица ID: {target_spreadsheet_id}): {len(data_rows)} (Результат API: {updated_cells} ячеек)",
        )
        return True
    except HttpError as err:
        log_message(
            logs_list,
            f"Ошибка Google API при записи данных в лист '{sheet_title}' (таблица ID: {target_spreadsheet_id}): {err}",
            "error",
        )
        return False
    except Exception as e:
        log_message(
            logs_list,
            f"Непредвиденная ошибка при записи данных в лист '{sheet_title}' (таблица ID: {target_spreadsheet_id}): {e}",
            "error",
        )
        return False


# --- Маршруты Flask ---
@app.route("/check_access", methods=["GET"])
def check_google_sheet_access():
    """Проверяет доступ к Google Sheet и возвращает количество строк в поле 'count'."""

    # Проверки конфигурации
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        return jsonify(
            {
                "status": "error",
                "message": f"Файл ключа {SERVICE_ACCOUNT_FILE} не найден",
                "count": 0,  # Можно добавить count: 0 при ошибках конфигурации
            }
        )
    if not SPREADSHEET_ID or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        return jsonify(
            {
                "status": "error",
                "message": "Не настроен ID таблицы (SPREADSHEET_ID)",
                "count": 0,
            }
        )
    if not RANGE_NAME:
        return jsonify(
            {
                "status": "error",
                "message": "Не настроен диапазон (RANGE_NAME)",
                "count": 0,
            }
        )

    try:
        creds_read = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        service_read_only = build("sheets", "v4", credentials=creds_read)
        # log_message(logs_check, "Check Access: Google Sheets API (read-only) authentication successful.") # Для логов сервера

        sheet = service_read_only.spreadsheets()
        # log_message(logs_check, f"Check Access: Reading from Sheet ID: {SPREADSHEET_ID}, Range: {RANGE_NAME}")
        result = (
            sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        )
        values = result.get(
            "values", []
        )  # values будет пустым списком, если ничего не найдено
        num_rows = len(values)  # num_rows будет 0, если values пуст
        # log_message(logs_check, f"Check Access: Successfully read data. Found {num_rows} rows in range.")

        # Проверка прав на запись (оставляем как есть)
        write_access_message = "Проверка прав на запись не проводилась."
        write_access_status = "unknown"
        try:
            creds_write = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets"
                ],  # Полные права для проверки
            )
            service_write_check = build("sheets", "v4", credentials=creds_write)
            service_write_check.spreadsheets().get(
                spreadsheetId=SPREADSHEET_ID,
                fields="properties",  # Проверяем для основной таблицы
            ).execute()
            write_access_message = (
                "Права на запись (редактор) для основной таблицы скорее всего есть."
            )
            write_access_status = "success"
        except HttpError as write_err:
            if write_err.resp.status == 403:
                write_access_message = "Ошибка: Нет прав на запись (редактор) для основной таблицы. Отчеты на этот же лист создаваться не будут (если настроено)!"
                write_access_status = "error"
            else:
                write_access_message = f"Не удалось проверить права на запись для основной таблицы: {write_err}"
                write_access_status = "warning"
        except Exception as write_e:
            write_access_message = f"Не удалось проверить права на запись для основной таблицы (другая ошибка): {write_e}"
            write_access_status = "warning"

        # Формируем сообщение об успехе, которое включает количество строк
        success_message = f"Доступ к базе номеров (ID: {SPREADSHEET_ID[:10]}...) получен. Найдено строк для обработки: {num_rows}."

        return jsonify(
            {
                "status": "success",
                "message": success_message,  # Передаем сообщение, уже содержащее num_rows
                "count": num_rows,  # Явно передаем count для использования клиентом
                "write_check": {
                    "message": write_access_message,
                    "status": write_access_status,
                },
            }
        )

    except HttpError as err:
        reason = "Проверьте права доступа к таблице или правильность ID/Диапазона."
        try:
            if err.resp.status == 403:
                reason = f"Доступ к чтению таблицы (ID: {SPREADSHEET_ID[:10]}...) запрещен (403). Убедитесь, что email сервисного аккаунта добавлен хотя бы в читатели таблицы."
            elif err.resp.status == 404:
                reason = f"Таблица (ID: {SPREADSHEET_ID[:10]}...) не найдена (404). Проверьте правильность SPREADSHEET_ID."
            else:
                reason = f"Ошибка Google API ({err.resp.status}) при доступе к таблице (ID: {SPREADSHEET_ID[:10]}...): {err._get_reason()}"
        except Exception:
            pass  # Используем стандартную причину, если не удалось разобрать
        return jsonify(
            {"status": "error", "message": reason, "count": 0}
        )  # Возвращаем count: 0 при ошибке
    except Exception as e:
        return jsonify(
            {"status": "error", "message": f"Непредвиденная ошибка: {e}", "count": 0}
        )  # Возвращаем count: 0 при ошибке


@app.route("/")
def index():
    error = None
    if not API_URL or API_URL == "TOKEN":
        error = "Ошибка: Не указан TOKEN в настройках (.env)!"
    return render_template(
        "index.html",
        default_delay=DEFAULT_DELAY_BETWEEN_MESSAGES,
        default_message=DEFAULT_MESSAGE_TEXT,
        error=error,
    )


@app.route("/send", methods=["POST"])
def send_messages_route():
    logs = []
    log_message(logs, "Запрос на запуск рассылки получен.")
    service = None
    report_sheet_title = None
    reporting_to_google_sheets_enabled = False
    delay_info_for_template = {"type": "Фиксированная", "value": 0}

    # Определяем целевой ID таблицы для отчетов
    actual_report_spreadsheet_id = None
    if (
        REPORT_SPREADSHEET_ID
        and REPORT_SPREADSHEET_ID != "YOUR_REPORT_SPREADSHEET_ID_HERE"
    ):
        actual_report_spreadsheet_id = REPORT_SPREADSHEET_ID

    report_info = {
        "sheet_title": None,
        "status": "Отключено (REPORT_SPREADSHEET_ID не задан или некорректен)",
        "target_file_id": actual_report_spreadsheet_id
        if actual_report_spreadsheet_id
        else "N/A",
    }

    if not API_URL or API_URL == "TOKEN":
        log_message(logs, "Критическая ошибка: Не указан TOKEN в .env!", "error")
        return render_template(
            "results.html",
            logs=logs,
            successful_sends=0,
            failed_sends=0,
            total_processed=0,
            message_text="N/A",
            delay_info=delay_info_for_template,
            report_info=report_info,
        )

    message_text = request.form.get("message", DEFAULT_MESSAGE_TEXT)
    random_delay_enabled = request.form.get("random_delay_enabled") == "yes"
    fixed_delay_value = 0  # Для хранения значения фиксированной задержки

    if random_delay_enabled:
        log_message(logs, "Выбран режим случайной задержки (5-15 сек).")
        delay_info_for_template["type"] = "Случайная (5-15 сек)"
        # fixed_delay_value остается 0, так как не используется
    else:
        try:
            fixed_delay_value = int(
                request.form.get("delay", DEFAULT_DELAY_BETWEEN_MESSAGES)
            )
            if fixed_delay_value < 0:
                fixed_delay_value = 0
            log_message(
                logs, f"Выбран режим фиксированной задержки: {fixed_delay_value} сек."
            )
            delay_info_for_template["value"] = fixed_delay_value
        except ValueError:
            fixed_delay_value = DEFAULT_DELAY_BETWEEN_MESSAGES
            log_message(
                logs,
                f"Предупреждение: Некорректное значение фиксированной задержки, используется значение по умолчанию: {fixed_delay_value} сек.",
                "warning",
            )
            delay_info_for_template["value"] = fixed_delay_value

    log_message(logs, f'Текст сообщения для отправки: "{message_text}"')

    service = create_google_service(logs)
    phone_numbers = None
    if service:
        # Читаем номера из ИСХОДНОЙ таблицы (SPREADSHEET_ID)
        phone_numbers = get_phone_numbers_from_sheet(
            service, SPREADSHEET_ID, RANGE_NAME, logs
        )
    else:
        log_message(
            logs,
            "Не удалось аутентифицироваться в Google API. Чтение номеров и отчетность невозможны.",
            "error",
        )

    successful_sends = 0
    failed_sends = 0
    total_processed = 0

    if phone_numbers is None:
        log_message(
            logs, "Не удалось получить номера телефонов. Рассылка отменена.", "error"
        )
    elif not phone_numbers:
        log_message(
            logs,
            "Список валидных номеров для отправки пуст. Рассылка не будет запущена.",
            "warning",
        )
    else:
        if service and actual_report_spreadsheet_id:
            report_sheet_title = datetime.now().strftime("%d.%m.%y %H-%M-%S")
            report_info["sheet_title"] = report_sheet_title
            # Создаем лист в ЦЕЛЕВОЙ ТАБЛИЦЕ ОТЧЕТОВ
            if create_new_report_sheet(
                service, actual_report_spreadsheet_id, report_sheet_title, logs
            ):
                header_row = [["№", "Number", "Name", "Status", "Time"]]
                if write_report_to_sheet(
                    service,
                    actual_report_spreadsheet_id,
                    report_sheet_title,
                    header_row,
                    logs,
                ):
                    reporting_to_google_sheets_enabled = True
                    report_info["status"] = "Активно"
                    log_message(
                        logs,
                        f"Отчет будет записываться в таблицу ID: {actual_report_spreadsheet_id} на лист '{report_sheet_title}'",
                    )
                else:
                    report_info["status"] = "Ошибка записи заголовка в файл отчетов"
                    log_message(
                        logs,
                        "Не удалось записать заголовок. Отчетность в Google Sheets будет отключена.",
                        "error",
                    )
            else:
                report_info["status"] = "Ошибка создания листа в файле отчетов"
                log_message(
                    logs,
                    "Не удалось создать лист для отчета. Отчетность в Google Sheets будет отключена.",
                    "error",
                )
        elif not actual_report_spreadsheet_id:
            log_message(
                logs,
                "REPORT_SPREADSHEET_ID не настроен. Отчеты в Google Sheets создаваться не будут.",
                "info",
            )
        elif not service:
            report_info["status"] = "Отключено (сервис Google недоступен)"
            log_message(
                logs,
                "Сервис Google Sheets недоступен, отчетность в Google Sheets отключена.",
                "warning",
            )

        total_processed = len(phone_numbers)
        log_message(logs, f"Начинаем отправку {total_processed} сообщений...")

        for i, number in enumerate(phone_numbers):
            log_message(logs, "-" * 20)
            log_message(
                logs, f"Сообщение {i + 1} из {total_processed} на номер {number}"
            )
            success_send = send_message(API_URL, number, message_text, logs)

            if (
                reporting_to_google_sheets_enabled
                and service
                and report_sheet_title
                and actual_report_spreadsheet_id
            ):
                report_time = datetime.now().strftime("%H:%M:%S")
                status_text = "Отправлено" if success_send else "Не отправлено"
                report_row = [i + 1, number, "", status_text, report_time]
                # Пишем в ЦЕЛЕВУЮ ТАБЛИЦУ ОТЧЕТОВ
                write_report_to_sheet(
                    service,
                    actual_report_spreadsheet_id,
                    report_sheet_title,
                    [report_row],
                    logs,
                )

            if success_send:
                successful_sends += 1
            else:
                failed_sends += 1

            if i < total_processed - 1:
                current_actual_delay = 0
                if random_delay_enabled:
                    current_actual_delay = random.uniform(
                        5, 15
                    )  # Случайная от 5 до 15 секунд
                    log_message(
                        logs, f"  Случайная пауза: {current_actual_delay:.2f} сек..."
                    )
                    time.sleep(current_actual_delay)
                elif fixed_delay_value > 0:
                    current_actual_delay = fixed_delay_value
                    log_message(
                        logs, f"  Фиксированная пауза {current_actual_delay} сек..."
                    )
                    time.sleep(current_actual_delay)
                else:
                    log_message(logs, "  Пауза не используется (0 сек).")

        log_message(logs, "=" * 30)
        log_message(logs, "Рассылка завершена.")
        log_message(
            logs,
            f"Итого: Успешно отправлено: {successful_sends}, Не удалось отправить: {failed_sends}",
        )
        if reporting_to_google_sheets_enabled:
            log_message(
                logs,
                f"Отчет сохранен в Google Таблице (ID: {actual_report_spreadsheet_id}) на листе: '{report_sheet_title}'",
            )
        log_message(logs, "=" * 30)

    return render_template(
        "results.html",
        logs=logs,
        successful_sends=successful_sends,
        failed_sends=failed_sends,
        total_processed=total_processed,
        message_text=message_text,
        delay_info=delay_info_for_template,  # Передаем словарь с информацией о задержке
        report_info=report_info,
    )


# --- Запуск приложения ---
if __name__ == "__main__":
    print("Проверка основных настроек...")
    critical_error = False
    if not API_URL or API_URL == "TOKEN":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан TOKEN в .env! Рассылка работать не будет."
        )
        critical_error = True
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан или не найден файл SERVICE_ACCOUNT_FILE: '{SERVICE_ACCOUNT_FILE}' в .env! Чтение номеров и отчетность работать не будут."
        )
        critical_error = True
    if not SPREADSHEET_ID or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан SPREADSHEET_ID (таблица с номерами) в .env! Чтение номеров работать не будет."
        )
        critical_error = True

    if not critical_error:
        print(
            "Основные настройки для запуска (.env) выглядят корректно. Дополнительные проверки доступа к Google Sheets доступны через веб-интерфейс."
        )

    print(
        "Запуск Flask приложения... Откройте http://127.0.0.1:5000 (или http://<ваш_ip>:5000) в браузере."
    )
    app.run(host="0.0.0.0", port=5000, debug=True)
=======
<<<<<<< HEAD
import requests
import time
import os
import re
import random
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask, render_template, request, jsonify


# --- Загрузка Настроек ---
load_dotenv()
API_URL = os.getenv("TOKEN")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
RANGE_NAME = os.getenv("RANGE_NAME")

# Настройки по умолчанию для веб-интерфейса
DEFAULT_MESSAGE_TEXT = ""
DEFAULT_DELAY_BETWEEN_MESSAGES = 5

# Области доступа для Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- Flask Приложение ---
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# --- Функции ---


def log_message(logs_list, message, level="info"):
    """Добавляет сообщение в список логов для вывода в веб-интерфейс."""
    print(message)  # Оставляем вывод в консоль сервера для отладки
    logs_list.append({"message": message, "level": level})


def format_phone_number(raw_number, logs_list):
    """Форматирует номер телефона и логирует процесс."""
    if not isinstance(raw_number, str):
        log_message(
            logs_list,
            f"  Предупреждение: Получено не строковое значение: {raw_number}. Пропускаем.",
            "warning",
        )
        return None

    digits = re.sub(r"\D", "", raw_number)

    if len(digits) == 11:
        if digits.startswith("8"):
            formatted = "7" + digits[1:]
            log_message(
                logs_list,
                f"    Форматирование: '{raw_number}' -> '{formatted}' (Замена 8 на 7)",
            )
            return formatted
        elif digits.startswith("7"):
            log_message(
                logs_list,
                f"    Форматирование: '{raw_number}' -> '{digits}' (Уже верный формат)",
            )
            return digits
        else:
            log_message(
                logs_list,
                f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 11 цифр, но начинается не с 7 или 8. Пропускаем.",
                "warning",
            )
            return None
    elif len(digits) == 10:
        formatted = "7" + digits
        log_message(
            logs_list,
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 10 цифр. Добавляем '7' в начало -> '{formatted}'",
            "warning",
        )
        return formatted
    else:
        log_message(
            logs_list,
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет неверную длину ({len(digits)}). Пропускаем.",
            "warning",
        )
        return None


def get_phone_numbers_from_sheet(service, spreadsheet_id, range_name, logs_list):
    """Читает номера из Google Sheets с использованием переданного объекта service."""
    try:
        log_message(
            logs_list,
            f"Чтение данных из таблицы ID: {spreadsheet_id}, Диапазон: {range_name}",
        )
        sheet = service.spreadsheets()
        result = (
            sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        )
        values = result.get("values", [])

        formatted_numbers = []
        if not values:
            log_message(
                logs_list,
                "Номера телефонов не найдены в указанном диапазоне.",
                "warning",
            )
            return []
        else:
            log_message(
                logs_list,
                f"Найдено строк в таблице: {len(values)}. Начинаем обработку и форматирование:",
            )
            try:
                start_row_match = re.search(r"(\d+):", range_name)
                start_row = int(start_row_match.group(1)) if start_row_match else 1
            except:
                start_row = 1

            for i, row in enumerate(values):
                current_row_num = start_row + i
                if row and row[0] and str(row[0]).strip():
                    raw_number = str(row[0]).strip()
                    log_message(
                        logs_list, f"  Строка {current_row_num}: Читаем '{raw_number}'"
                    )
                    formatted = format_phone_number(raw_number, logs_list)
                    if formatted:
                        if formatted not in formatted_numbers:
                            formatted_numbers.append(formatted)
                            log_message(
                                logs_list,
                                f"    -> Добавлен валидный номер: {formatted}",
                                "success",
                            )
                        else:
                            log_message(
                                logs_list,
                                f"    -> Дубликат номера {formatted}, пропускаем.",
                                "warning",
                            )
                else:
                    log_message(
                        logs_list,
                        f"  Строка {current_row_num}: Пустая или некорректная строка, пропускаем.",
                        "info",
                    )

            log_message(logs_list, "-" * 20)
            log_message(
                logs_list,
                f"Итоговый список уникальных валидных номеров для отправки ({len(formatted_numbers)} шт.).",
            )
            log_message(logs_list, "-" * 20)
            return formatted_numbers

    except HttpError as err:
        log_message(
            logs_list, f"Произошла ошибка Google API при чтении номеров: {err}", "error"
        )
        return None
    except Exception as e:
        log_message(
            logs_list,
            f"Произошла непредвиденная ошибка при чтении номеров: {e}",
            "error",
        )
        return None


def send_message(api_url, phone_number, message, logs_list):
    """Отправляет сообщение через API и логирует результат."""
    chat_id = f"{phone_number}@c.us"
    payload = {
        "chatId": chat_id,
        "message": message,
    }
    headers = {"Content-Type": "application/json"}

    try:
        log_message(logs_list, f"Отправка сообщения на {chat_id}...")
        # Увеличиваем таймаут, т.к. API может отвечать не мгновенно
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()  # Вызовет исключение для кодов 4xx/5xx

        response_text = "Не удалось декодировать ответ API"
        try:
            # Пытаемся декодировать ответ, как в оригинальном коде
            response_text = response.text.encode("latin1").decode("utf8")
        except UnicodeDecodeError:
            try:
                response_text = response.text.encode("utf-8").decode("utf-8")
            except Exception:
                response_text = (
                    response.text
                )  # Если ничего не помогло, показываем как есть

        log_message(
            logs_list,
            f"  Успешно отправлено на {chat_id}. Ответ API: {response_text}",
            "success",
        )
        return True

    except requests.exceptions.Timeout:
        log_message(
            logs_list,
            f"  Ошибка: Превышено время ожидания ответа от API при отправке на {chat_id}.",
            "error",
        )
        return False
    except requests.exceptions.RequestException as e:
        error_msg = f"  Ошибка отправки на {chat_id}: {e}"
        response_text = ""
        if e.response is not None:
            try:
                response_text = e.response.text.encode("latin1").decode("utf8")
            except UnicodeDecodeError:
                try:
                    response_text = e.response.text.encode("utf-8").decode("utf-8")
                except Exception:
                    response_text = e.response.text
            error_msg += f" | Ответ сервера ({e.response.status_code}): {response_text}"
        log_message(logs_list, error_msg, "error")
        return False
    except Exception as e:
        log_message(
            logs_list,
            f"  Непредвиденная ошибка при отправке на {chat_id}: {e}",
            "error",
        )
        return False


def create_google_service(logs_list):
    """Создает и возвращает объект service для Google API."""
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        log_message(
            logs_list,
            f"Ошибка: Файл сервисного аккаунта не найден или не указан: {SERVICE_ACCOUNT_FILE}",
            "error",
        )
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        log_message(
            logs_list,
            "Успешная аутентификация в Google Sheets API (для чтения/записи).",
        )
        return service
    except Exception as e:
        log_message(
            logs_list, f"Ошибка аутентификации в Google Sheets API: {e}", "error"
        )
        return None


def create_new_report_sheet(service, spreadsheet_id, sheet_title, logs_list):
    """Создает новый лист в Google Таблице для отчета."""  # Обновили docstring
    try:
        log_message(
            logs_list, f"Попытка создать новый лист с именем: '{sheet_title}'"
        )  # Обновили лог
        requests_body = {
            "requests": [{"addSheet": {"properties": {"title": sheet_title}}}]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=requests_body
        ).execute()

        log_message(
            logs_list,
            f"Успешно создан лист отчета: '{sheet_title}'",
            "success",
        )
        return True
    except HttpError as err:
        # Проверяем, возможно лист уже существует
        if "already exists" in str(err):
            log_message(
                logs_list,
                f"Предупреждение: Лист '{sheet_title}' уже существует. Запись будет вестись в него.",
                "warning",
            )
            return True  # Считаем успехом, если лист уже есть
        else:
            log_message(
                logs_list,
                f"Ошибка Google API при создании листа '{sheet_title}': {err}. Убедитесь, что у сервисного аккаунта есть права редактора.",
                "error",
            )
            return False
    except Exception as e:
        log_message(
            logs_list,
            f"Непредвиденная ошибка при создании листа '{sheet_title}': {e}",
            "error",
        )
        return False


def write_report_to_sheet(service, spreadsheet_id, sheet_title, data_rows, logs_list):
    """Записывает строки данных в указанный лист."""
    try:
        range_to_write = f"'{sheet_title}'!A1"  # Начинаем с A1
        body = {"values": data_rows}
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_to_write,
                valueInputOption="USER_ENTERED",  # Обрабатывать данные как введенные пользователем
                insertDataOption="INSERT_ROWS",  # Вставлять строки, а не перезаписывать
                body=body,
            )
            .execute()
        )
        log_message(
            logs_list,
            f"Записано строк в отчет '{sheet_title}': {len(data_rows)} (Результат API: {result.get('updates').get('updatedCells')} ячеек)",
        )
        return True
    except HttpError as err:
        log_message(
            logs_list,
            f"Ошибка Google API при записи данных в лист '{sheet_title}': {err}",
            "error",
        )
        return False
    except Exception as e:
        log_message(
            logs_list,
            f"Непредвиденная ошибка при записи данных в лист '{sheet_title}': {e}",
            "error",
        )
        return False


# --- Маршруты Flask ---
@app.route("/check_access", methods=["GET"])
def check_google_sheet_access():
    """Проверяет доступ к Google Sheet (только чтение для этой проверки)."""
    logs_check = []
    service_read_only = None

    # Создаем сервис с правами ТОЛЬКО НА ЧТЕНИЕ для проверки
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        return jsonify(
            {
                "status": "error",
                "message": f"Файл ключа {SERVICE_ACCOUNT_FILE} не найден",
            }
        )
    if not SPREADSHEET_ID or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        return jsonify(
            {"status": "error", "message": "Не настроен ID таблицы (SPREADSHEET_ID)"}
        )
    if not RANGE_NAME:
        return jsonify(
            {"status": "error", "message": "Не настроен диапазон (RANGE_NAME)"}
        )

    try:
        creds_read = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        service_read_only = build("sheets", "v4", credentials=creds_read)
        log_message(
            logs_check,
            "Check Access: Google Sheets API (read-only) authentication successful.",
        )

        sheet = service_read_only.spreadsheets()
        log_message(
            logs_check,
            f"Check Access: Reading from Sheet ID: {SPREADSHEET_ID}, Range: {RANGE_NAME}",
        )
        result = (
            sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        )
        values = result.get("values", [])
        num_rows = len(values)
        log_message(
            logs_check,
            f"Check Access: Successfully read data. Found {num_rows} rows in range.",
        )

        # Дополнительная проверка возможности записи (не выполняя запись)
        # Это менее надежно, но может дать подсказку пользователю
        try:
            creds_write = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service_write_check = build("sheets", "v4", credentials=creds_write)
            # Просто пытаемся получить метаданные таблицы, что требует прав записи
            service_write_check.spreadsheets().get(
                spreadsheetId=SPREADSHEET_ID, fields="properties"
            ).execute()
            write_access_message = "Права на запись (редактор) скорее всего есть."
            write_access_status = "success"
        except HttpError as write_err:
            if write_err.resp.status == 403:
                write_access_message = "Ошибка: Нет прав на запись (редактор). Отчеты создаваться не будут!"
                write_access_status = "error"
            else:
                write_access_message = (
                    f"Не удалось проверить права на запись: {write_err}"
                )
                write_access_status = "warning"
        except Exception as write_e:
            write_access_message = (
                f"Не удалось проверить права на запись (другая ошибка): {write_e}"
            )
            write_access_status = "warning"

        return jsonify(
            {
                "status": "success",
                "count": num_rows,
                "write_check": {
                    "message": write_access_message,
                    "status": write_access_status,
                },
            }
        )

    except HttpError as err:
        reason = "Проверьте права доступа к таблице или правильность ID/Диапазона."
        try:
            if err.resp.status == 403:
                reason = "Доступ к чтению запрещен (403). Убедитесь, что email сервисного аккаунта добавлен хотя бы в читатели таблицы."
            elif err.resp.status == 404:
                reason = (
                    "Таблица не найдена (404). Проверьте правильность SPREADSHEET_ID."
                )
            else:
                reason = f"Ошибка Google API ({err.resp.status}). {err._get_reason()}"
        except Exception:
            pass
        return jsonify({"status": "error", "message": reason})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Непредвиденная ошибка: {e}"})


@app.route("/")
def index():
    error = None
    if not API_URL or API_URL == "TOKEN":
        error = "Ошибка: Не указан API_URL в настройках (.env)!"
    return render_template(
        "index.html",
        default_delay=DEFAULT_DELAY_BETWEEN_MESSAGES,
        error=error,
    )


@app.route('/send', methods=['POST'])
def send_messages_route():
    logs = []
    log_message(logs, "Запрос на запуск рассылки получен.")
    service = None
    report_sheet_title = None
    reporting_enabled = False
    delay_info_for_template = {"type": "Фиксированная", "value": 0} # Для передачи в шаблон

    if not API_URL or API_URL == "TOKEN":
        log_message(logs, "Критическая ошибка: Не указан API_URL в .env!", "error")
        return render_template('results.html', logs=logs, successful_sends=0, failed_sends=0, total_processed=0, message_text="N/A", delay_info=delay_info_for_template, report_info=None)

    message_text = request.form.get('message', DEFAULT_MESSAGE_TEXT)
    
    random_delay_enabled = request.form.get('random_delay_enabled') == 'yes'
    delay = 0

    if random_delay_enabled:
        log_message(logs, "Выбран режим случайной задержки (5-15 сек).")
        delay_info_for_template["type"] = "Случайная (5-15 сек)"
        # Фиксированное значение delay не используется, но оставим 0 для информации
    else:
        try:
            delay = int(request.form.get('delay', DEFAULT_DELAY_BETWEEN_MESSAGES))
            if delay < 0: 
                delay = 0
            log_message(logs, f"Выбран режим фиксированной задержки: {delay} сек.")
            delay_info_for_template["value"] = delay
        except ValueError:
            delay = DEFAULT_DELAY_BETWEEN_MESSAGES
            log_message(logs, f"Предупреждение: Некорректное значение фиксированной задержки, используется значение по умолчанию: {delay} сек.", "warning")
            delay_info_for_template["value"] = delay

    log_message(logs, f"Текст сообщения для отправки: \"{message_text}\"")

    service = create_google_service(logs)
    if not service:
        log_message(logs, "Не удалось аутентифицироваться в Google API. Рассылка будет выполнена без чтения номеров из таблицы и без отчета.", "error")
        phone_numbers = None
    else:
        phone_numbers = get_phone_numbers_from_sheet(service, SPREADSHEET_ID, RANGE_NAME, logs)

    successful_sends = 0
    failed_sends = 0
    total_processed = 0
    report_info = {"sheet_title": None, "status": "Отключено"}

    if phone_numbers is None:
        log_message(logs, "Не удалось получить номера телефонов из таблицы или произошла ошибка API. Рассылка отменена.", "error")
    elif not phone_numbers:
        log_message(logs, "Список валидных номеров для отправки пуст. Рассылка не будет запущена.", "warning")
    else:
        if service:
            report_sheet_title = datetime.now().strftime("%d.%m.%y %H-%M-%S") # Изменил разделитель времени для имени файла
            report_info["sheet_title"] = report_sheet_title
            if create_new_report_sheet(service, SPREADSHEET_ID, report_sheet_title, logs):
                header_row = [["№", "Number", "Name", "Status", "Time"]]
                if write_report_to_sheet(service, SPREADSHEET_ID, report_sheet_title, header_row, logs):
                    reporting_enabled = True
                    report_info["status"] = "Активно"
                    log_message(logs, f"Отчет будет записываться в лист '{report_sheet_title}'")
                else:
                    report_info["status"] = "Ошибка записи заголовка"
                    log_message(logs, "Не удалось записать заголовок в лист отчета. Отчетность будет отключена.", "error")
            else:
                 report_info["status"] = "Ошибка создания листа"
                 log_message(logs, "Не удалось создать лист для отчета. Отчетность будет отключена.", "error")
        else:
             report_info["status"] = "Сервис Google недоступен"
             log_message(logs, "Сервис Google Sheets недоступен, отчетность отключена.", "warning")

        total_processed = len(phone_numbers)
        log_message(logs, f"Начинаем отправку {total_processed} сообщений...")

        for i, number in enumerate(phone_numbers):
            log_message(logs, "-" * 20)
            log_message(logs, f"Сообщение {i + 1} из {total_processed} на номер {number}")

            success_send = send_message(API_URL, number, message_text, logs)

            if reporting_enabled and service and report_sheet_title:
                report_time = datetime.now().strftime("%H:%M:%S")
                status = "Отправлено" if success_send else "Не отправлено"
                report_row = [i + 1, number, "", status, report_time]
                write_report_to_sheet(service, SPREADSHEET_ID, report_sheet_title, [report_row], logs)

            if success_send:
                successful_sends += 1
            else:
                failed_sends += 1

            if i < total_processed - 1: # Пауза не нужна после последнего сообщения
                current_actual_delay = 0
                if random_delay_enabled:
                    current_actual_delay = random.uniform(5, 15)
                    log_message(logs, f"  Случайная пауза: {current_actual_delay:.2f} сек...")
                    time.sleep(current_actual_delay)
                elif delay > 0: # Если случайная не включена, но фиксированная > 0
                    current_actual_delay = delay
                    log_message(logs, f"  Фиксированная пауза {current_actual_delay} сек...")
                    time.sleep(current_actual_delay)
                else:
                    log_message(logs, "  Пауза не используется (0 сек).")
        
        log_message(logs, "=" * 30)
        log_message(logs, "Рассылка завершена.")
        log_message(logs, f"Итого: Успешно отправлено: {successful_sends}, Не удалось отправить: {failed_sends}")
        if reporting_enabled:
             log_message(logs, f"Отчет сохранен в Google Таблице на листе: '{report_sheet_title}'")
        log_message(logs, "=" * 30)

    return render_template('results.html',
                           logs=logs,
                           successful_sends=successful_sends,
                           failed_sends=failed_sends,
                           total_processed=total_processed,
                           message_text=message_text,
                           delay_info=delay_info_for_template,
                           report_info=report_info)


# --- Запуск приложения ---
if __name__ == "__main__":
    print("Проверка основных настроек...")
    # Проверяем только критичные для запуска Flask
    if not API_URL or API_URL == "TOKEN":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан API_URL в .env! Рассылка работать не будет."
        )
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан или не найден файл SERVICE_ACCOUNT_FILE: '{SERVICE_ACCOUNT_FILE}' в .env! Чтение номеров и отчетность работать не будут."
        )
    if not SPREADSHEET_ID or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан SPREADSHEET_ID в .env! Чтение номеров и отчетность работать не будут."
        )
    else:
        print("Основные настройки (.env) выглядят корректно.")

    print(
        "Запуск Flask приложения... Откройте http://127.0.0.1:5000 (или http://<ваш_ip>:5000) в браузере."
    )
    # debug=False для продакшена, host='0.0.0.0' для доступа из сети
    app.run(host="0.0.0.0", port=5000, debug=True)
=======
import requests
import time
import os
import re
import random
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask, render_template, request, jsonify


# --- Загрузка Настроек ---
load_dotenv()
API_URL = os.getenv("TOKEN")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
RANGE_NAME = os.getenv("RANGE_NAME")

# Настройки по умолчанию для веб-интерфейса
DEFAULT_MESSAGE_TEXT = ""
DEFAULT_DELAY_BETWEEN_MESSAGES = 5

# Области доступа для Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- Flask Приложение ---
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# --- Функции ---


def log_message(logs_list, message, level="info"):
    """Добавляет сообщение в список логов для вывода в веб-интерфейс."""
    print(message)  # Оставляем вывод в консоль сервера для отладки
    logs_list.append({"message": message, "level": level})


def format_phone_number(raw_number, logs_list):
    """Форматирует номер телефона и логирует процесс."""
    if not isinstance(raw_number, str):
        log_message(
            logs_list,
            f"  Предупреждение: Получено не строковое значение: {raw_number}. Пропускаем.",
            "warning",
        )
        return None

    digits = re.sub(r"\D", "", raw_number)

    if len(digits) == 11:
        if digits.startswith("8"):
            formatted = "7" + digits[1:]
            log_message(
                logs_list,
                f"    Форматирование: '{raw_number}' -> '{formatted}' (Замена 8 на 7)",
            )
            return formatted
        elif digits.startswith("7"):
            log_message(
                logs_list,
                f"    Форматирование: '{raw_number}' -> '{digits}' (Уже верный формат)",
            )
            return digits
        else:
            log_message(
                logs_list,
                f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 11 цифр, но начинается не с 7 или 8. Пропускаем.",
                "warning",
            )
            return None
    elif len(digits) == 10:
        formatted = "7" + digits
        log_message(
            logs_list,
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 10 цифр. Добавляем '7' в начало -> '{formatted}'",
            "warning",
        )
        return formatted
    else:
        log_message(
            logs_list,
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет неверную длину ({len(digits)}). Пропускаем.",
            "warning",
        )
        return None


def get_phone_numbers_from_sheet(service, spreadsheet_id, range_name, logs_list):
    """Читает номера из Google Sheets с использованием переданного объекта service."""
    try:
        log_message(
            logs_list,
            f"Чтение данных из таблицы ID: {spreadsheet_id}, Диапазон: {range_name}",
        )
        sheet = service.spreadsheets()
        result = (
            sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        )
        values = result.get("values", [])

        formatted_numbers = []
        if not values:
            log_message(
                logs_list,
                "Номера телефонов не найдены в указанном диапазоне.",
                "warning",
            )
            return []
        else:
            log_message(
                logs_list,
                f"Найдено строк в таблице: {len(values)}. Начинаем обработку и форматирование:",
            )
            try:
                start_row_match = re.search(r"(\d+):", range_name)
                start_row = int(start_row_match.group(1)) if start_row_match else 1
            except:
                start_row = 1

            for i, row in enumerate(values):
                current_row_num = start_row + i
                if row and row[0] and str(row[0]).strip():
                    raw_number = str(row[0]).strip()
                    log_message(
                        logs_list, f"  Строка {current_row_num}: Читаем '{raw_number}'"
                    )
                    formatted = format_phone_number(raw_number, logs_list)
                    if formatted:
                        if formatted not in formatted_numbers:
                            formatted_numbers.append(formatted)
                            log_message(
                                logs_list,
                                f"    -> Добавлен валидный номер: {formatted}",
                                "success",
                            )
                        else:
                            log_message(
                                logs_list,
                                f"    -> Дубликат номера {formatted}, пропускаем.",
                                "warning",
                            )
                else:
                    log_message(
                        logs_list,
                        f"  Строка {current_row_num}: Пустая или некорректная строка, пропускаем.",
                        "info",
                    )

            log_message(logs_list, "-" * 20)
            log_message(
                logs_list,
                f"Итоговый список уникальных валидных номеров для отправки ({len(formatted_numbers)} шт.).",
            )
            log_message(logs_list, "-" * 20)
            return formatted_numbers

    except HttpError as err:
        log_message(
            logs_list, f"Произошла ошибка Google API при чтении номеров: {err}", "error"
        )
        return None
    except Exception as e:
        log_message(
            logs_list,
            f"Произошла непредвиденная ошибка при чтении номеров: {e}",
            "error",
        )
        return None


def send_message(api_url, phone_number, message, logs_list):
    """Отправляет сообщение через API и логирует результат."""
    chat_id = f"{phone_number}@c.us"
    payload = {
        "chatId": chat_id,
        "message": message,
    }
    headers = {"Content-Type": "application/json"}

    try:
        log_message(logs_list, f"Отправка сообщения на {chat_id}...")
        # Увеличиваем таймаут, т.к. API может отвечать не мгновенно
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()  # Вызовет исключение для кодов 4xx/5xx

        response_text = "Не удалось декодировать ответ API"
        try:
            # Пытаемся декодировать ответ, как в оригинальном коде
            response_text = response.text.encode("latin1").decode("utf8")
        except UnicodeDecodeError:
            try:
                response_text = response.text.encode("utf-8").decode("utf-8")
            except Exception:
                response_text = (
                    response.text
                )  # Если ничего не помогло, показываем как есть

        log_message(
            logs_list,
            f"  Успешно отправлено на {chat_id}. Ответ API: {response_text}",
            "success",
        )
        return True

    except requests.exceptions.Timeout:
        log_message(
            logs_list,
            f"  Ошибка: Превышено время ожидания ответа от API при отправке на {chat_id}.",
            "error",
        )
        return False
    except requests.exceptions.RequestException as e:
        error_msg = f"  Ошибка отправки на {chat_id}: {e}"
        response_text = ""
        if e.response is not None:
            try:
                response_text = e.response.text.encode("latin1").decode("utf8")
            except UnicodeDecodeError:
                try:
                    response_text = e.response.text.encode("utf-8").decode("utf-8")
                except Exception:
                    response_text = e.response.text
            error_msg += f" | Ответ сервера ({e.response.status_code}): {response_text}"
        log_message(logs_list, error_msg, "error")
        return False
    except Exception as e:
        log_message(
            logs_list,
            f"  Непредвиденная ошибка при отправке на {chat_id}: {e}",
            "error",
        )
        return False


def create_google_service(logs_list):
    """Создает и возвращает объект service для Google API."""
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        log_message(
            logs_list,
            f"Ошибка: Файл сервисного аккаунта не найден или не указан: {SERVICE_ACCOUNT_FILE}",
            "error",
        )
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        log_message(
            logs_list,
            "Успешная аутентификация в Google Sheets API (для чтения/записи).",
        )
        return service
    except Exception as e:
        log_message(
            logs_list, f"Ошибка аутентификации в Google Sheets API: {e}", "error"
        )
        return None


def create_new_report_sheet(service, spreadsheet_id, sheet_title, logs_list):
    """Создает новый лист в Google Таблице для отчета."""  # Обновили docstring
    try:
        log_message(
            logs_list, f"Попытка создать новый лист с именем: '{sheet_title}'"
        )  # Обновили лог
        requests_body = {
            "requests": [{"addSheet": {"properties": {"title": sheet_title}}}]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=requests_body
        ).execute()

        log_message(
            logs_list,
            f"Успешно создан лист отчета: '{sheet_title}'",
            "success",
        )
        return True
    except HttpError as err:
        # Проверяем, возможно лист уже существует
        if "already exists" in str(err):
            log_message(
                logs_list,
                f"Предупреждение: Лист '{sheet_title}' уже существует. Запись будет вестись в него.",
                "warning",
            )
            return True  # Считаем успехом, если лист уже есть
        else:
            log_message(
                logs_list,
                f"Ошибка Google API при создании листа '{sheet_title}': {err}. Убедитесь, что у сервисного аккаунта есть права редактора.",
                "error",
            )
            return False
    except Exception as e:
        log_message(
            logs_list,
            f"Непредвиденная ошибка при создании листа '{sheet_title}': {e}",
            "error",
        )
        return False


def write_report_to_sheet(service, spreadsheet_id, sheet_title, data_rows, logs_list):
    """Записывает строки данных в указанный лист."""
    try:
        range_to_write = f"'{sheet_title}'!A1"  # Начинаем с A1
        body = {"values": data_rows}
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_to_write,
                valueInputOption="USER_ENTERED",  # Обрабатывать данные как введенные пользователем
                insertDataOption="INSERT_ROWS",  # Вставлять строки, а не перезаписывать
                body=body,
            )
            .execute()
        )
        log_message(
            logs_list,
            f"Записано строк в отчет '{sheet_title}': {len(data_rows)} (Результат API: {result.get('updates').get('updatedCells')} ячеек)",
        )
        return True
    except HttpError as err:
        log_message(
            logs_list,
            f"Ошибка Google API при записи данных в лист '{sheet_title}': {err}",
            "error",
        )
        return False
    except Exception as e:
        log_message(
            logs_list,
            f"Непредвиденная ошибка при записи данных в лист '{sheet_title}': {e}",
            "error",
        )
        return False


# --- Маршруты Flask ---
@app.route("/check_access", methods=["GET"])
def check_google_sheet_access():
    """Проверяет доступ к Google Sheet (только чтение для этой проверки)."""
    logs_check = []
    service_read_only = None

    # Создаем сервис с правами ТОЛЬКО НА ЧТЕНИЕ для проверки
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        return jsonify(
            {
                "status": "error",
                "message": f"Файл ключа {SERVICE_ACCOUNT_FILE} не найден",
            }
        )
    if not SPREADSHEET_ID or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        return jsonify(
            {"status": "error", "message": "Не настроен ID таблицы (SPREADSHEET_ID)"}
        )
    if not RANGE_NAME:
        return jsonify(
            {"status": "error", "message": "Не настроен диапазон (RANGE_NAME)"}
        )

    try:
        creds_read = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        service_read_only = build("sheets", "v4", credentials=creds_read)
        log_message(
            logs_check,
            "Check Access: Google Sheets API (read-only) authentication successful.",
        )

        sheet = service_read_only.spreadsheets()
        log_message(
            logs_check,
            f"Check Access: Reading from Sheet ID: {SPREADSHEET_ID}, Range: {RANGE_NAME}",
        )
        result = (
            sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        )
        values = result.get("values", [])
        num_rows = len(values)
        log_message(
            logs_check,
            f"Check Access: Successfully read data. Found {num_rows} rows in range.",
        )

        # Дополнительная проверка возможности записи (не выполняя запись)
        # Это менее надежно, но может дать подсказку пользователю
        try:
            creds_write = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service_write_check = build("sheets", "v4", credentials=creds_write)
            # Просто пытаемся получить метаданные таблицы, что требует прав записи
            service_write_check.spreadsheets().get(
                spreadsheetId=SPREADSHEET_ID, fields="properties"
            ).execute()
            write_access_message = "Права на запись (редактор) скорее всего есть."
            write_access_status = "success"
        except HttpError as write_err:
            if write_err.resp.status == 403:
                write_access_message = "Ошибка: Нет прав на запись (редактор). Отчеты создаваться не будут!"
                write_access_status = "error"
            else:
                write_access_message = (
                    f"Не удалось проверить права на запись: {write_err}"
                )
                write_access_status = "warning"
        except Exception as write_e:
            write_access_message = (
                f"Не удалось проверить права на запись (другая ошибка): {write_e}"
            )
            write_access_status = "warning"

        return jsonify(
            {
                "status": "success",
                "count": num_rows,
                "write_check": {
                    "message": write_access_message,
                    "status": write_access_status,
                },
            }
        )

    except HttpError as err:
        reason = "Проверьте права доступа к таблице или правильность ID/Диапазона."
        try:
            if err.resp.status == 403:
                reason = "Доступ к чтению запрещен (403). Убедитесь, что email сервисного аккаунта добавлен хотя бы в читатели таблицы."
            elif err.resp.status == 404:
                reason = (
                    "Таблица не найдена (404). Проверьте правильность SPREADSHEET_ID."
                )
            else:
                reason = f"Ошибка Google API ({err.resp.status}). {err._get_reason()}"
        except Exception:
            pass
        return jsonify({"status": "error", "message": reason})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Непредвиденная ошибка: {e}"})


@app.route("/")
def index():
    error = None
    if not API_URL or API_URL == "TOKEN":
        error = "Ошибка: Не указан API_URL в настройках (.env)!"
    return render_template(
        "index.html",
        default_delay=DEFAULT_DELAY_BETWEEN_MESSAGES,
        error=error,
    )


@app.route('/send', methods=['POST'])
def send_messages_route():
    logs = []
    log_message(logs, "Запрос на запуск рассылки получен.")
    service = None
    report_sheet_title = None
    reporting_enabled = False
    delay_info_for_template = {"type": "Фиксированная", "value": 0} # Для передачи в шаблон

    if not API_URL or API_URL == "TOKEN":
        log_message(logs, "Критическая ошибка: Не указан API_URL в .env!", "error")
        return render_template('results.html', logs=logs, successful_sends=0, failed_sends=0, total_processed=0, message_text="N/A", delay_info=delay_info_for_template, report_info=None)

    message_text = request.form.get('message', DEFAULT_MESSAGE_TEXT)
    
    random_delay_enabled = request.form.get('random_delay_enabled') == 'yes'
    delay = 0

    if random_delay_enabled:
        log_message(logs, "Выбран режим случайной задержки (5-15 сек).")
        delay_info_for_template["type"] = "Случайная (5-15 сек)"
        # Фиксированное значение delay не используется, но оставим 0 для информации
    else:
        try:
            delay = int(request.form.get('delay', DEFAULT_DELAY_BETWEEN_MESSAGES))
            if delay < 0: 
                delay = 0
            log_message(logs, f"Выбран режим фиксированной задержки: {delay} сек.")
            delay_info_for_template["value"] = delay
        except ValueError:
            delay = DEFAULT_DELAY_BETWEEN_MESSAGES
            log_message(logs, f"Предупреждение: Некорректное значение фиксированной задержки, используется значение по умолчанию: {delay} сек.", "warning")
            delay_info_for_template["value"] = delay

    log_message(logs, f"Текст сообщения для отправки: \"{message_text}\"")

    service = create_google_service(logs)
    if not service:
        log_message(logs, "Не удалось аутентифицироваться в Google API. Рассылка будет выполнена без чтения номеров из таблицы и без отчета.", "error")
        phone_numbers = None
    else:
        phone_numbers = get_phone_numbers_from_sheet(service, SPREADSHEET_ID, RANGE_NAME, logs)

    successful_sends = 0
    failed_sends = 0
    total_processed = 0
    report_info = {"sheet_title": None, "status": "Отключено"}

    if phone_numbers is None:
        log_message(logs, "Не удалось получить номера телефонов из таблицы или произошла ошибка API. Рассылка отменена.", "error")
    elif not phone_numbers:
        log_message(logs, "Список валидных номеров для отправки пуст. Рассылка не будет запущена.", "warning")
    else:
        if service:
            report_sheet_title = datetime.now().strftime("%d.%m.%y %H-%M-%S") # Изменил разделитель времени для имени файла
            report_info["sheet_title"] = report_sheet_title
            if create_new_report_sheet(service, SPREADSHEET_ID, report_sheet_title, logs):
                header_row = [["№", "Number", "Name", "Status", "Time"]]
                if write_report_to_sheet(service, SPREADSHEET_ID, report_sheet_title, header_row, logs):
                    reporting_enabled = True
                    report_info["status"] = "Активно"
                    log_message(logs, f"Отчет будет записываться в лист '{report_sheet_title}'")
                else:
                    report_info["status"] = "Ошибка записи заголовка"
                    log_message(logs, "Не удалось записать заголовок в лист отчета. Отчетность будет отключена.", "error")
            else:
                 report_info["status"] = "Ошибка создания листа"
                 log_message(logs, "Не удалось создать лист для отчета. Отчетность будет отключена.", "error")
        else:
             report_info["status"] = "Сервис Google недоступен"
             log_message(logs, "Сервис Google Sheets недоступен, отчетность отключена.", "warning")

        total_processed = len(phone_numbers)
        log_message(logs, f"Начинаем отправку {total_processed} сообщений...")

        for i, number in enumerate(phone_numbers):
            log_message(logs, "-" * 20)
            log_message(logs, f"Сообщение {i + 1} из {total_processed} на номер {number}")

            success_send = send_message(API_URL, number, message_text, logs)

            if reporting_enabled and service and report_sheet_title:
                report_time = datetime.now().strftime("%H:%M:%S")
                status = "Отправлено" if success_send else "Не отправлено"
                report_row = [i + 1, number, "", status, report_time]
                write_report_to_sheet(service, SPREADSHEET_ID, report_sheet_title, [report_row], logs)

            if success_send:
                successful_sends += 1
            else:
                failed_sends += 1

            if i < total_processed - 1: # Пауза не нужна после последнего сообщения
                current_actual_delay = 0
                if random_delay_enabled:
                    current_actual_delay = random.uniform(5, 15)
                    log_message(logs, f"  Случайная пауза: {current_actual_delay:.2f} сек...")
                    time.sleep(current_actual_delay)
                elif delay > 0: # Если случайная не включена, но фиксированная > 0
                    current_actual_delay = delay
                    log_message(logs, f"  Фиксированная пауза {current_actual_delay} сек...")
                    time.sleep(current_actual_delay)
                else:
                    log_message(logs, "  Пауза не используется (0 сек).")
        
        log_message(logs, "=" * 30)
        log_message(logs, "Рассылка завершена.")
        log_message(logs, f"Итого: Успешно отправлено: {successful_sends}, Не удалось отправить: {failed_sends}")
        if reporting_enabled:
             log_message(logs, f"Отчет сохранен в Google Таблице на листе: '{report_sheet_title}'")
        log_message(logs, "=" * 30)

    return render_template('results.html',
                           logs=logs,
                           successful_sends=successful_sends,
                           failed_sends=failed_sends,
                           total_processed=total_processed,
                           message_text=message_text,
                           delay_info=delay_info_for_template,
                           report_info=report_info)


# --- Запуск приложения ---
if __name__ == "__main__":
    print("Проверка основных настроек...")
    # Проверяем только критичные для запуска Flask
    if not API_URL or API_URL == "TOKEN":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан API_URL в .env! Рассылка работать не будет."
        )
    if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан или не найден файл SERVICE_ACCOUNT_FILE: '{SERVICE_ACCOUNT_FILE}' в .env! Чтение номеров и отчетность работать не будут."
        )
    if not SPREADSHEET_ID or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        print(
            "!!! КРИТИЧЕСКАЯ ОШИБКА: Не указан SPREADSHEET_ID в .env! Чтение номеров и отчетность работать не будут."
        )
    else:
        print("Основные настройки (.env) выглядят корректно.")

    print(
        "Запуск Flask приложения... Откройте http://127.0.0.1:5000 (или http://<ваш_ip>:5000) в браузере."
    )
    # debug=False для продакшена, host='0.0.0.0' для доступа из сети
    app.run(host="0.0.0.0", port=5000, debug=True)
>>>>>>> 01234d5055bc335512643cef3f81a12f2feeead3
>>>>>>> 49696dd1f3864486bc6b808b99b7c666a0e19435
