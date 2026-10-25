import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
import logging

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_sheet = None

def init_sheet(sheet_id: str):
    global _sheet
    try:
        creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
        gc = gspread.authorize(creds)
        _sheet = gc.open_by_key(sheet_id).sheet1
        # создаём заголовки, если таблица пустая
        if not _sheet.get_all_values():
            _sheet.append_row(["Дата", "User ID", "Username", "Вопрос", "Ответ", "Статус"])
        logging.info("Google Sheets подключён.")
    except Exception as e:
        logging.error(f"Не удалось подключить Google Sheets: {e}")
        _sheet = None


def log_dialog(user, question, answer, status="bot"):
    """status: bot / not_found / operator / operator_reply / user_to_operator"""
    if _sheet is None:
        return
    try:
        _sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(user.id),
            f"@{user.username}" if user.username else (user.full_name or "—"),
            question,
            answer,
            status
        ])
    except Exception as e:
        logging.error(f"Ошибка записи в Google Sheets: {e}")