import requests
import time
import os
import re
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- НАСТРОЙКИ ---
load_dotenv()
API_URL = os.getenv('TOKEN')
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
RANGE_NAME = os.getenv('RANGE_NAME')

# Текст сообщения для отправки
MESSAGE_TEXT = "Привет! Это тестовая массовая рассылка."

# Задержка между отправками сообщений (в секундах), чтобы избежать блокировки API
DELAY_BETWEEN_MESSAGES = 0

# Области доступа для Google Sheets API (только чтение)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# --- КОНЕЦ НАСТРОЕК ---


def format_phone_number(raw_number):
    if not isinstance(raw_number, str):
        print(
            f"  Предупреждение: Получено не строковое значение: {raw_number}. Пропускаем.")
        return None

    # Удаляем все не цифровые символы
    digits = re.sub(r'\D', '', raw_number)

    # Проверяем длину
    if len(digits) == 11:
        if digits.startswith('8'):
            # Заменяем 8 на 7
            return '7' + digits[1:]
        elif digits.startswith('7'):
            # Уже правильный формат
            return digits
        else:
            # Неверный формат для 11 цифр
            print(
                f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 11 цифр, но начинается не с 7 или 8. Пропускаем.")
            return None
    elif len(digits) == 10:
        # Если 10 цифр, скорее всего, отсутствует код страны, добавляем '7'
        print(
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет 10 цифр. Добавляем '7' в начало.")
        return '7' + digits
    else:
        # Неверная длина
        print(
            f"  Предупреждение: Номер '{raw_number}' -> '{digits}' имеет неверную длину ({len(digits)}). Пропускаем.")
        return None


def get_phone_numbers_from_sheet(spreadsheet_id, range_name):
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"Ошибка: Файл сервисного аккаунта не найден по пути: {SERVICE_ACCOUNT_FILE}")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)

        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id,
                                    range=range_name).execute()
        values = result.get('values', [])

        formatted_numbers = []
        if not values:
            print('Номера телефонов не найдены в указанном диапазоне.')
            return []
        else:
            print(
                f"Найдено строк в таблице: {len(values)}. Начинаем обработку и форматирование:")
            # Определяем начальную строку из диапазона (для логов)
            try:
                start_row = int(re.search(r'(\d+):', range_name).group(1))
            except:
                start_row = 1  # По умолчанию, если не удалось распарсить

            for i, row in enumerate(values):
                # Убедимся, что строка не пустая и содержит хотя бы один элемент
                if row and row[0] and str(row[0]).strip():
                    raw_number = str(row[0]).strip()
                    current_row_num = start_row + i
                    print(f"  Строка {current_row_num}: Читаем '{raw_number}'")
                    formatted = format_phone_number(raw_number)
                    if formatted:
                        formatted_numbers.append(formatted)
                        print(f"    -> OK: {formatted}")
                    # else: функция format_phone_number уже вывела предупреждение
                else:
                    pass

            print("-" * 20)
            print(
                f"Итоговый список номеров для отправки ({len(formatted_numbers)} шт.):")
            print(formatted_numbers)
            print("-" * 20)
            return formatted_numbers

    except HttpError as err:
        print(f"Произошла ошибка Google API: {err}")
        return None
    except Exception as e:
        print(
            f"Произошла непредвиденная ошибка при чтении или форматировании номеров: {e}")
        return None


def send_message(api_url, phone_number, message):
    chat_id = f"{phone_number}@c.us"
    payload = {
        "chatId": chat_id,
        "message": message,
    }
    headers = {
        'Content-Type': 'application/json'
    }

    try:
        print(f"Отправка сообщения на {chat_id}...")
        response = requests.post(
            api_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        print(f"  Успешно отправлено на {chat_id}. Ответ API:")
        try:
            print(f"  {response.text.encode('latin1').decode('utf8')}")
        except UnicodeDecodeError:
            try:
                print(f"  {response.text.encode('utf-8').decode('utf-8')}")
            except Exception:
                print(f"  Не удалось декодировать ответ: {response.text}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"  Ошибка отправки на {chat_id}: {e}")
        if e.response is not None:
            try:
                print(
                    f"  Ответ сервера: {e.response.text.encode('latin1').decode('utf8')}")
            except UnicodeDecodeError:
                try:
                    print(
                        f"  Ответ сервера: {e.response.text.encode('utf-8').decode('utf-8')}")
                except Exception:
                    print(
                        f"  Не удалось декодировать ответ сервера: {e.response.text}")
        return False
    except Exception as e:
        print(f"  Непредвиденная ошибка при отправке на {chat_id}: {e}")
        return False


def main():
    print("Начало процесса...")

    # 1. Получаем и форматируем номера из Google Sheets
    phone_numbers = get_phone_numbers_from_sheet(SPREADSHEET_ID, RANGE_NAME)

    if phone_numbers is None:
        print("Не удалось получить номера телефонов. Проверьте настройки и ошибки выше.")
        return

    if not phone_numbers:
        print("Список номеров для отправки пуст (возможно, все номера были невалидны или диапазон пуст). Завершение работы.")
        return

    # 2. Отправляем сообщения по списку
    successful_sends = 0
    failed_sends = 0
    total_numbers_to_send = len(phone_numbers)

    for i, number in enumerate(phone_numbers):
        print("-" * 20)
        print(f"Сообщение {i + 1} из {total_numbers_to_send}")
        if send_message(API_URL, number, MESSAGE_TEXT):
            successful_sends += 1
        else:
            failed_sends += 1

        if i < total_numbers_to_send - 1:
            print(f"  Пауза {DELAY_BETWEEN_MESSAGES} сек...")
            time.sleep(DELAY_BETWEEN_MESSAGES)

    print("=" * 30)
    print("Рассылка завершена.")
    print(
        f"Всего номеров в таблице обработано (валидных): {total_numbers_to_send}")
    print(f"Успешно отправлено: {successful_sends}")
    print(f"Не удалось отправить: {failed_sends}")
    print("=" * 30)


if __name__ == '__main__':
    if API_URL == "TOKEN" or API_URL == "":
        print("Ошибка: Не указан API_URL в настройках!")
    elif SERVICE_ACCOUNT_FILE == 'path/to/your/service_account.json' or not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(
            f"Ошибка: Не указан или не найден файл SERVICE_ACCOUNT_FILE: {SERVICE_ACCOUNT_FILE}")
    elif SPREADSHEET_ID == 'YOUR_SPREADSHEET_ID' or SPREADSHEET_ID == "":
        print("Ошибка: Не указан SPREADSHEET_ID в настройках!")
    else:
        main()
