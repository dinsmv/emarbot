from __future__ import annotations

import os
import json
import logging
import time
from typing import Dict, List

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from dialog_context import (
    combine_with_context,
    normalize_user_question,
    resolve_advisor_followup,
    extract_advisor_entity,
)

import chroma_sqlite_fix  # noqa: F401

import chromadb
from ai_utils import (
    get_embedding,
    generate_rag_answer,
    reformulate_for_search,
    humanize,
    define_term_fallback,
)

from aggression import needs_operator
from priority_qa import match_priority_answer
from answer_mode import decide_answer_mode, render_text_answer
from doliv_calculator import try_doliv_plan, DOLIV_CALC_PROMPT
from sheets import init_sheet, log_dialog
from templates import match_template, looks_like_template_request, TEMPLATE_CLARIFY_MSG
from materials import (
    match_material,
    match_material_bundle,
    looks_like_material_request,
    looks_like_catalog_list_request,
    format_catalog_list,
    format_material_reply,
    material_clarify_message,
    material_file_path,
)
from intent_router import (
    CAPABILITIES_REPLY,
    GREETING_REPLY,
    INTENT_CATALOG,
    INTENT_DEFINE,
    INTENT_FOLLOWUP,
    INTENT_GREETING,
    INTENT_HOWTO,
    INTENT_OPERATOR,
    INTENT_POLICY,
    INTENT_TEMPLATE,
    INTENT_TRUST,
    allows_materials,
    classify_intent,
)


# --- Конфиг ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPERATOR_GROUP_ID = int(os.getenv("OPERATOR_GROUP_ID", "0"))
DISABLE_OPERATOR_ESCALATION = os.getenv("DISABLE_OPERATOR_ESCALATION", "").lower() in (
    "1", "true", "yes",
)
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
MINIAPP_URL = os.getenv("MINIAPP_URL", "").strip()

DB_PATH = "knowledge_db"
POROG = 0.5
RAG_TOP_K = 5

DIALOG_TIMEOUT = 600          # через сколько секунд бездействия закрывать диалог (10 мин)
WARN_BEFORE = 120             # за сколько секунд до закрытия предупредить (2 мин)
CHECK_INTERVAL = 60           # как часто проверять таймауты (сек)
STATE_FILE = "dialogs_state.json"  # файл сохранения состояния
TG_LIMIT = 4000               # безопасный предел длины сообщения

CHAT_HISTORY_MAX = 6          # последние N реплик (3 пары вопрос-ответ)
CHAT_HISTORY_TTL = 1800       # забыть контекст через 30 мин бездействия

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- База знаний ---
chroma_client = chromadb.PersistentClient(path=DB_PATH)
collection = chroma_client.get_collection("faq")


def search_context(question):
    """Ищет 3–5 релевантных фрагментов в базе знаний."""
    try:
        emb = get_embedding(question)
    except Exception as e:
        logging.error("search_context embedding failed: %s", e)
        return None
    # Берём с запасом, чтобы отфильтровать по названию советника
    try:
        results = collection.query(
            query_embeddings=[emb],
            n_results=max(RAG_TOP_K * 3, 12),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logging.error("search_context chroma failed: %s", e)
        return None
    if not results["documents"] or not results["documents"][0]:
        return None

    best_distance = results["distances"][0][0]
    logging.info(f"Поиск: best_distance={best_distance:.3f}, порог={POROG}")
    if best_distance > POROG:
        return None
    entity = extract_advisor_entity(question)
    entity_tokens: list[str] = []
    if entity:
        # «EMAR Classic Aggressive» → ищем Aggressive (+ Classic если есть)
        low = entity.lower()
        for tok in ("aggressive", "medium", "conservative", "classic", "king", "trinity"):
            if tok in low:
                entity_tokens.append(tok)

    fragments = []
    for i in range(len(results["documents"][0])):
        distance = results["distances"][0][i]
        if distance > POROG:
            continue
        meta = results["metadatas"][0][i] or {}
        qmeta = meta.get("question", "")
        ans = results["documents"][0][i]
        blob = f"{qmeta} {ans}".lower()
        boost = 0.0
        if entity_tokens:
            # предпочитаем фрагменты с нужным профилем/линейкой
            hits = sum(1 for t in entity_tokens if t in blob)
            if hits:
                boost = -0.08 * hits
            elif any(t in blob for t in ("aggressive", "medium", "conservative")):
                # другой профиль — штрафуем
                boost = 0.12
        fragments.append({
            "question": qmeta,
            "answer": ans,
            "distance": distance + boost,
        })

    # Дедупликация: в базе бывают одинаковые фрагменты — не отдаём их дважды
    seen_keys = set()
    unique = []
    for f in sorted(fragments, key=lambda x: x["distance"]):
        key = "".join((f["answer"] or "").lower().split())[:200]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(f)
    fragments = unique

    fragments = fragments[:RAG_TOP_K]
    return fragments or None


# =====================================================================
#  ХРАНИЛИЩЕ СОСТОЯНИЙ
# =====================================================================
active_dialogs = {}
map_msg = {}
chat_history = {}


# ---------- Память диалога (уточняющие вопросы) ----------
def _looks_like_followup(text: str) -> bool:
    t = text.lower().strip()
    if len(t) < 60:
        return True
    markers = (
        "а ", "и ", "но ", "ещё", "еще ", "уточн", "подробнее", "обратно",
        "это ", "такой", "такая", "такое", "почему", "зачем", "можно ли",
        "а если", "а как", "а где", "а когда", "а что", "не понял", "не поняла",
        "не понятно", "непонятно", "то есть", "имеется в виду", "вы имели",
    )
    return any(t.startswith(m) or m in t for m in markers)


def get_chat_history(user_id: int) -> List[Dict]:
    now = time.time()
    msgs = chat_history.get(user_id, [])
    msgs = [m for m in msgs if now - m.get("ts", now) < CHAT_HISTORY_TTL]
    chat_history[user_id] = msgs
    return msgs


def append_chat(user_id: int, role: str, text: str):
    if not text or not text.strip():
        return
    msgs = get_chat_history(user_id)
    msgs.append({"role": role, "text": text.strip(), "ts": time.time()})
    chat_history[user_id] = msgs[-CHAT_HISTORY_MAX:]
    save_state()


def clear_chat_history(user_id: int):
    chat_history.pop(user_id, None)
    save_state()


def build_search_query(question: str, history: List[Dict]) -> str:
    """Для уточнений расширяем запрос контекстом или переформулируем через LLM."""
    # Follow-up про советника («у него параметры») — жёстко подставляем продукт
    resolved = resolve_advisor_followup(question, history) if history else None
    if resolved:
        return resolved
    if not history:
        return question
    contextual = combine_with_context(question, history)
    if contextual != question:
        # Для коротких уточнений — LLM-переформулировка; иначе склейка достаточна
        if _looks_like_followup(question) or len(question) < 50:
            return reformulate_for_search(contextual, history)
        return contextual
    if _looks_like_followup(question):
        return reformulate_for_search(question, history)
    return question


# ---------- Сохранение / загрузка состояния ----------
def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "active_dialogs": {str(k): v for k, v in active_dialogs.items()},
                "map_msg": {str(k): v for k, v in map_msg.items()},
                "chat_history": {str(k): v for k, v in chat_history.items()},
            }, f, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"save_state error: {e}")


def load_state():
    global active_dialogs, map_msg, chat_history
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
            active_dialogs = {int(k): v for k, v in data.get("active_dialogs", {}).items()}
            map_msg = {int(k): v for k, v in data.get("map_msg", {}).items()}
            chat_history = {int(k): v for k, v in data.get("chat_history", {}).items()}
        logging.info(
            f"Загружено: диалогов={len(active_dialogs)}, "
            f"историй чата={len(chat_history)}"
        )
    except FileNotFoundError:
        logging.info("Файл состояния не найден — старт с чистого листа.")
    except Exception as e:
        logging.warning(f"load_state error: {e}")


def is_user_with_operator(user_id):
    return user_id in active_dialogs


def touch_activity(user_id):
    if user_id in active_dialogs:
        active_dialogs[user_id]["last_activity"] = time.time()
        active_dialogs[user_id]["warned"] = False   # активность сбрасывает предупреждение
        save_state()


# ---------- Безопасная отправка длинных сообщений ----------
async def safe_send(context, chat_id, text, **kwargs):
    if not text:
        return None
    # Ответы без parse_mode — убираем markdown, чтобы не светились **звёздочки**
    if "parse_mode" not in kwargs:
        from ai_utils import _sanitize_answer
        text = _sanitize_answer(text)
    if len(text) <= TG_LIMIT:
        return await context.bot.send_message(chat_id, text, **kwargs)
    last = None
    for i in range(0, len(text), TG_LIMIT):
        last = await context.bot.send_message(chat_id, text[i:i + TG_LIMIT])
    return last


async def deliver_material(context, chat_id, item, reply_markup=None):
    """Отправка материала: видео-ссылки текстом, PDF/фото/аudio/видео — файлом."""
    path = material_file_path(item)
    caption = format_material_reply(item)
    media = item.get("media", "")
    max_upload = 49 * 1024 * 1024
    miniapp_hint = (
        f"\n\nОткройте 📦 Материалы в меню бота"
        + (f" или {MINIAPP_URL}" if MINIAPP_URL else "")
        + "."
    )

    if item.get("file") and not path:
        caption += (
            "\n\n⚠️ Файл сейчас недоступен на сервере."
            + miniapp_hint
        )
        return await safe_send(context, chat_id, caption, reply_markup=reply_markup)

    if path and media == "photo":
        with path.open("rb") as f:
            return await context.bot.send_photo(
                chat_id, photo=f, caption=caption[:1024], reply_markup=reply_markup,
            )
    if path and media == "pdf":
        with path.open("rb") as f:
            return await context.bot.send_document(
                chat_id, document=f, caption=caption[:1024], reply_markup=reply_markup,
            )
    if path and media == "audio":
        with path.open("rb") as f:
            return await context.bot.send_audio(
                chat_id, audio=f, caption=caption[:1024], reply_markup=reply_markup,
            )
    if path and media == "video":
        size = path.stat().st_size
        if size > max_upload:
            return await safe_send(
                context,
                chat_id,
                f"🎬 {item['title']}\n\n"
                "Видео слишком большое для отправки в чат Telegram (лимит ~50 МБ)."
                + miniapp_hint,
                reply_markup=reply_markup,
            )
        with path.open("rb") as f:
            return await context.bot.send_video(
                chat_id, video=f, caption=caption[:1024], reply_markup=reply_markup,
            )

    if item.get("type") == "file" and path:
        size = path.stat().st_size
        if size > max_upload:
            return await safe_send(
                context,
                chat_id,
                f"🎬 {item['title']}\n\n"
                "Файл слишком большой для отправки в чат Telegram (лимит ~50 МБ)."
                + miniapp_hint,
                reply_markup=reply_markup,
            )
        with path.open("rb") as f:
            return await context.bot.send_document(
                chat_id, document=f, caption=caption[:1024], reply_markup=reply_markup,
            )

    return await safe_send(context, chat_id, caption, reply_markup=reply_markup)


# ---------- Завершение диалога ----------
async def end_dialog(context, user_id, reason="closed", notify_user=True, notify_group=True):
    info = active_dialogs.pop(user_id, None)
    if info is None:
        return False

    pinned_id = info.get("pinned_msg_id")
    if pinned_id:
        try:
            await context.bot.unpin_chat_message(chat_id=user_id, message_id=pinned_id)
        except Exception as e:
            logging.warning(f"Не смог открепить у {user_id}: {e}")
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=pinned_id)
        except Exception as e:
            logging.warning(f"Не смог удалить закреп у {user_id}: {e}")

    # чистим map_msg от записей этого пользователя
    for mid in [m for m, u in map_msg.items() if u == user_id]:
        map_msg.pop(mid, None)

    clear_chat_history(user_id)
    save_state()

    uname = f"@{info['username']}" if info.get("username") else info.get("name", str(user_id))

    if notify_user:
        try:
            await context.bot.send_message(
                user_id,
                "Рад был помочь! Если появятся вопросы — пишите, всегда на связи 🙂"
            )
        except Exception as e:
            logging.warning(f"Не смог уведомить пользователя {user_id}: {e}")

    if notify_group and OPERATOR_GROUP_ID:
        reason_text = {
            "user": "пользователь нажал «Вопрос решён»",
            "operator": "оператор завершил диалог",
            "timeout": "автозавершение по таймауту (нет активности)",
            "command": "закрыто командой /close",
        }.get(reason, "завершено")
        try:
            await context.bot.send_message(
                OPERATOR_GROUP_ID,
                f"🔚 Диалог с {uname} (id {user_id}) завершён.\nПричина: {reason_text}."
            )
        except Exception as e:
            logging.warning(f"Не смог уведомить группу: {e}")

    log_dialog_safe(user_id, uname, "(диалог завершён)", reason, f"dialog_closed_{reason}")
    return True


def log_dialog_safe(user_id, uname, question, answer, status):
    try:
        class _U:
            def __init__(self, uid, name):
                self.id = uid
                self.username = name.lstrip("@") if name else None
                self.full_name = name
        log_dialog(_U(user_id, uname), question, answer, status=status)
    except Exception as e:
        logging.warning(f"log_dialog error: {e}")


# =====================================================================
#  КЛАВИАТУРЫ
# =====================================================================
def user_resolved_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Вопрос решён", callback_data="resolve_user")
    ]])


def operator_end_kb(user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔚 Завершить диалог", callback_data=f"endop:{user_id}")
    ]])


def main_menu_kb():
    rows = [
        [InlineKeyboardButton("📋 Основные темы", callback_data="show_topics")],
        [InlineKeyboardButton("🧮 Расчёт долива", callback_data="doliv_calc")],
        [InlineKeyboardButton("👤 Позвать оператора", callback_data="call_operator")],
    ]
    return InlineKeyboardMarkup(rows)


HELP_TEXT = (
    "📋 <b>Основные темы поддержки:</b>\n\n"
    "• Установка и подключение торговых советников\n"
    "• Настройка и работа (Trinity, King, Classic)\n"
    "• Режим сушки\n"
    "• MoniTrading и мониторинг счёта\n"
    "• Пополнение и вывод средств\n"
    "• Просадка и управление рисками\n"
    "• Технические проблемы с терминалом\n"
    "• Ссылки и полезные ресурсы компании\n\n"
    "Опишите ваш вопрос текстом — постараюсь помочь.\n"
    "📦 Материалы (видео/PDF) — кнопка «Материалы» в меню слева от поля ввода.\n"
    "🧮 Персональный план долива — кнопка «Расчёт долива».\n"
    "Для связи с живым специалистом нажмите «Позвать оператора»."
)

START_TEXT = (
    "Здравствуйте! 👋\n\n"
    "Я — бот техподдержки <b>EMAR Capital</b> по торговым советникам.\n\n"
    "Могу ответить на типовые вопросы: установка, настройка, сушка, "
    "мониторинг, пополнение и вывод, технические проблемы.\n\n"
    + (
        "📦 Инструкции, PDF и видео — кнопка «Материалы» в меню бота.\n\n"
        if MINIAPP_URL
        else ""
    )
    + "🧮 Могу посчитать план долива по вашим цифрам — кнопка «Расчёт долива».\n\n"
    + "⚠️ <i>Я не даю инвестиционных советов, не гарантирую доходность "
    "и не заменяю финансовую или юридическую консультацию.</i>\n\n"
    "Напишите ваш вопрос — или выберите действие ниже 👇"
)


# =====================================================================
#  КОМАНДЫ
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_chat_history(update.effective_user.id)
    await update.message.reply_text(
        START_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def materials_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not MINIAPP_URL:
        await update.message.reply_text(
            "Раздел материалов скоро будет доступен. Пока используйте канал «Промо Материалы»."
        )
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📦 Открыть материалы",
            web_app=WebAppInfo(url=MINIAPP_URL),
        )
    ]])
    await update.message.reply_text(
        "📦 <b>Материалы EMAR Capital</b>\n\n"
        "Инструкции, видео и документы — в канале «Промо Материалы».\n"
        "Шаблоны можно скопировать прямо в Mini App.",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def operator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_user_with_operator(update.effective_user.id):
        await update.message.reply_text(
            "Вы уже на связи со специалистом — напишите ваш вопрос, "
            "и оператор ответит в ближайшее время."
        )
        return
    text = " ".join(context.args) if context.args else "Пользователь вызвал оператора командой /operator"
    await escalate_to_operator(update, context, text, reason="user_request")


# Команда /active — список активных диалогов (только в группе операторов)
async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != OPERATOR_GROUP_ID:
        return
    if not active_dialogs:
        await update.message.reply_text("Активных диалогов нет.")
        return
    lines = ["📋 Активные диалоги:\n"]
    now = time.time()
    for uid, info in active_dialogs.items():
        uname = f"@{info['username']}" if info.get("username") else info.get("name", str(uid))
        status = "🟢 в работе" if info.get("operator_id") else "🟡 ждёт оператора"
        idle = int(now - info.get("last_activity", now))
        lines.append(f"• {uname} (id {uid}) — {status}, без активности {idle} сек")
    await update.message.reply_text("\n".join(lines))


# =====================================================================
#  ПЕРЕВОД НА ОПЕРАТОРА
# =====================================================================
async def escalate_to_operator(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reason: str = "manual",
):
    user = update.effective_user

    if DISABLE_OPERATOR_ESCALATION:
        test_notice = {
            "not_found": (
                "Я не нашёл точного ответа в базе знаний.\n"
                "🔧 Тестовый режим — в чат поддержки ничего не отправлено."
            ),
            "llm_uncertain": (
                "Пока не уверен в ответе на этот вопрос.\n"
                "🔧 Тестовый режим — в чат поддержки ничего не отправлено."
            ),
            "user_request": (
                "Запрос оператора принят.\n"
                "🔧 Тестовый режим — в чат поддержки ничего не отправлено."
            ),
            "manual": (
                "Вопрос требует внимания специалиста.\n"
                "🔧 Тестовый режим — в чат поддержки ничего не отправлено."
            ),
        }.get(reason, (
            "🔧 Тестовый режим — в чат поддержки ничего не отправлено."
        ))
        await safe_send(context, user.id, test_notice, reply_markup=main_menu_kb())
        log_dialog(user, text, f"(тест, без оператора: {reason})", status="test_skip")
        logging.info("TEST MODE: эскалация пропущена (%s): %s", reason, text[:120])
        return

    if user.id in active_dialogs:
        return

    clear_chat_history(user.id)
    active_dialogs[user.id] = {
        "operator_id": None,
        "username": user.username,
        "name": user.full_name,
        "last_activity": time.time(),
        "warned": False,
        "pinned_msg_id": None,
    }

    user_notice = {
        "not_found": (
            "Я не нашёл точного ответа в базе знаний — передаю ваш вопрос специалисту 🙏\n"
            "Скоро вернёмся с ответом.\n\n"
            "📌 Когда вопрос будет решён — нажмите кнопку ниже 👇"
        ),
        "user_request": (
            "Передаю ваш вопрос специалисту 🙏 Скоро вернёмся с ответом.\n\n"
            "📌 Когда вопрос будет решён — нажмите кнопку ниже 👇"
        ),
        "llm_uncertain": (
            "По этому вопросу лучше проконсультироваться со специалистом — "
            "уже передаю ваш запрос 🙏\n\n"
            "📌 Когда вопрос будет решён — нажмите кнопку ниже 👇"
        ),
    }.get(reason, (
        "Передаю ваш вопрос специалисту 🙏 Скоро вернёмся с ответом.\n\n"
        "📌 Когда вопрос будет решён — нажмите кнопку ниже 👇"
    ))

    sent = await context.bot.send_message(
        user.id,
        user_notice,
        reply_markup=user_resolved_kb(),
    )

    # закрепляем сообщение в чате пользователя (системное "закрепил" удалит хендлер)
    try:
        await context.bot.pin_chat_message(
            chat_id=user.id,
            message_id=sent.message_id,
            disable_notification=True
        )
        active_dialogs[user.id]["pinned_msg_id"] = sent.message_id
    except Exception as e:
        logging.warning(f"Не смог закрепить сообщение у {user.id}: {e}")

    save_state()

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Взять в работу", callback_data=f"take:{user.id}")
    ]])

    reason_labels = {
        "not_found": "ответ не найден в базе знаний",
        "user_request": "запрос оператора",
        "llm_uncertain": "ИИ не уверен в ответе",
        "manual": "эскалация",
    }
    reason_label = reason_labels.get(reason, reason)

    uname = f"@{user.username}" if user.username else user.full_name
    await context.bot.send_message(
        OPERATOR_GROUP_ID,
        f"⚠️ НУЖЕН ОПЕРАТОР ({reason_label})\n"
        f"Пользователь: {uname} (id: {user.id})\n"
        f"Сообщение:\n«{text}»\n\n"
        f"Нажмите кнопку, чтобы взять диалог. "
        f"Затем отвечайте через Reply на сообщения пользователя.",
        reply_markup=kb
    )
    log_dialog(user, text, f"→ переведено на оператора ({reason_label})", status="user_to_operator")


# Оператор нажал «Взять в работу»
async def take_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])

    if user_id not in active_dialogs:
        await query.edit_message_text(query.message.text + "\n\n❌ Диалог уже неактивен.")
        return

    if active_dialogs[user_id]["operator_id"] is not None:
        await query.answer("Этот диалог уже взят другим оператором.", show_alert=True)
        return

    operator = query.from_user
    active_dialogs[user_id]["operator_id"] = operator.id
    touch_activity(user_id)

    op_name = f"@{operator.username}" if operator.username else operator.full_name
    await query.edit_message_text(query.message.text + f"\n\n🟢 В работе у {op_name}")

    await context.bot.send_message(
        OPERATOR_GROUP_ID,
        f"🟢 Диалог с пользователем id {user_id} взят оператором {op_name}.\n"
        f"Кнопка ниже завершит диалог:",
        reply_markup=operator_end_kb(user_id)
    )


# Пользователь нажал «Вопрос решён»
async def resolve_by_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in active_dialogs:
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # завершаем диалог (внутри открепится закреп И отправится одно прощание)
    await end_dialog(context, user_id, reason="user")


# Оператор нажал «Завершить диалог»
async def end_by_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])

    if user_id not in active_dialogs:
        await query.edit_message_text(query.message.text + "\n\n❌ Диалог уже завершён.")
        return

    operator = query.from_user
    op_name = f"@{operator.username}" if operator.username else operator.full_name
    await query.edit_message_text(query.message.text + f"\n\n🔚 Завершено оператором {op_name}.")
    await end_dialog(context, user_id, reason="operator", notify_group=False)


async def show_topics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def doliv_calc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        DOLIV_CALC_PROMPT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def call_operator_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if is_user_with_operator(user.id):
        await query.message.reply_text(
            "Вы уже на связи со специалистом — напишите ваш вопрос, "
            "и оператор ответит в ближайшее время."
        )
        return
    await escalate_to_operator(
        update, context,
        "Пользователь нажал «Позвать оператора»",
        reason="user_request",
    )


# Команда /close <user_id>
async def close_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != OPERATOR_GROUP_ID:
        return
    if not context.args:
        await update.message.reply_text("Использование: /close <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный user_id.")
        return

    if user_id in active_dialogs:
        await end_dialog(context, user_id, reason="command", notify_group=False)
        await update.message.reply_text(f"✅ Диалог с {user_id} закрыт.")
    else:
        await update.message.reply_text("Активного диалога с этим пользователем нет.")


# =====================================================================
#  АВТО-ЗАКРЫТИЕ ПО ТАЙМАУТУ (+ предупреждение)
# =====================================================================
async def check_timeouts(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    to_close = []
    for user_id, info in list(active_dialogs.items()):
        last = info.get("last_activity", now)
        idle = now - last

        if idle > (DIALOG_TIMEOUT - WARN_BEFORE) and not info.get("warned"):
            info["warned"] = True
            save_state()
            try:
                await context.bot.send_message(
                    user_id,
                    "Вы ещё здесь? 🙂 Если вопросов больше нет — скоро закрою обращение. "
                    "Напишите что-нибудь, чтобы продолжить."
                )
            except Exception as e:
                logging.warning(f"Не смог отправить предупреждение {user_id}: {e}")

        if idle > DIALOG_TIMEOUT:
            to_close.append(user_id)

    for user_id in to_close:
        logging.info(f"⏱ Автозакрытие диалога с {user_id} (таймаут).")
        await end_dialog(context, user_id, reason="timeout")


# =====================================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================================================================
# Определяем "пустые"/служебные сообщения (от закрепления, входа и т.п.)
def is_service_message(msg):
    if msg is None:
        return True
    if (msg.text and msg.text.strip()) or (msg.caption and msg.caption.strip()):
        return False
    if any([
        msg.photo, msg.document, msg.video, msg.voice,
        msg.audio, msg.sticker, msg.animation, msg.video_note
    ]):
        return False
    return True


# Удаляем системное "бот закрепил сообщение"
async def delete_pin_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg and msg.pinned_message:
        try:
            await context.bot.delete_message(
                chat_id=msg.chat_id,
                message_id=msg.message_id
            )
        except Exception as e:
            logging.debug(f"Не удалил уведомление о закреплении: {e}")


# =====================================================================
#  СООБЩЕНИЯ ИЗ ГРУППЫ ОПЕРАТОРОВ (ответы пользователю через Reply)
# =====================================================================
async def operator_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    replied_id = msg.reply_to_message.message_id
    user_id = map_msg.get(replied_id)

    # fallback — если Reply на "не то" сообщение, но активный диалог один — отправляем ему
    if not user_id:
        active_with_op = [
            uid for uid, info in active_dialogs.items()
            if info.get("operator_id") is not None
        ]
        if len(active_with_op) == 1:
            user_id = active_with_op[0]
        else:
            logging.info("Reply на сообщение без привязки и неоднозначный диалог — игнор.")
            return

    if user_id not in active_dialogs:
        return

    try:
        await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id
        )
    except Exception as e:
        logging.warning(f"copy_message error: {e}")
        if msg.text:
            await safe_send(context, user_id, msg.text)

    touch_activity(user_id)
    log_dialog(msg.from_user, "(ответ оператора)", msg.text or "(вложение)", status="operator_reply")


# =====================================================================
#  СООБЩЕНИЯ ОТ ПОЛЬЗОВАТЕЛЕЙ (личка)
# =====================================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    вопрос = normalize_user_question((msg.text or "").strip())

    # Если пользователь уже в режиме оператора — пересылаем в группу
    if is_user_with_operator(user.id):
        # игнорируем служебные сообщения (закрепление, вход в чат и т.п.)
        if is_service_message(msg):
            return

        touch_activity(user.id)
        uname = f"@{user.username}" if user.username else user.full_name

        try:
            sent = await context.bot.copy_message(
                chat_id=OPERATOR_GROUP_ID,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id
            )
            info_msg = await context.bot.send_message(
                OPERATOR_GROUP_ID,
                f"💬 от {uname} (id {user.id}) — отвечайте Reply на сообщение выше",
                reply_markup=operator_end_kb(user.id)
            )
            map_msg[sent.message_id] = user.id
            map_msg[info_msg.message_id] = user.id
        except Exception as e:
            logging.warning(f"forward to operators error: {e}")

        save_state()
        log_dialog(user, вопрос or "(вложение)", "(ожидает ответа оператора)", status="operator")
        return

    # служебные сообщения молча игнорируем
    if is_service_message(msg):
        return

    # Дальше работаем только с текстом
    if not вопрос:
        await msg.reply_text("Напишите, пожалуйста, ваш вопрос текстом 🙂")
        return

    try:
        await _handle_user_question(update, context, user, вопрос)
    except Exception as e:
        logging.exception("handle_message crash: %s", e)
        try:
            await safe_send(
                context,
                user.id,
                "Сейчас не удалось обработать вопрос. Напишите ещё раз или нажмите «Позвать оператора».",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            pass


async def _handle_user_question(update, context, user, вопрос: str):
    history = get_chat_history(user.id)

    # 1) Намерение: правила → при сомнении Groq
    route = classify_intent(вопрос, history)
    logging.info(
        "Intent: %s (source=%s conf=%.2f reason=%s) q=%s",
        route.intent, route.source, route.confidence, route.reason, вопрос[:100],
    )

    if route.intent == INTENT_GREETING:
        clear_chat_history(user.id)
        reply = CAPABILITIES_REPLY if route.reason == "capabilities" else GREETING_REPLY
        reply = humanize(reply, strict=True)
        await safe_send(context, user.id, reply, reply_markup=main_menu_kb())
        append_chat(user.id, "user", вопрос)
        append_chat(user.id, "assistant", reply)
        log_dialog(user, вопрос, reply, status="bot:greeting")
        return

    if route.intent == INTENT_OPERATOR or needs_operator(вопрос):
        await escalate_to_operator(update, context, вопрос, reason="manual")
        return

    # 2) Шаблон заявки (не перехватывать howto «как установить…»)
    if route.intent == INTENT_TEMPLATE or (
        looks_like_template_request(вопрос) and route.intent != INTENT_HOWTO
    ):
        template = match_template(вопрос, history=history)
        if template:
            header = f"📝 {template['title']}\n\n"
            await safe_send(context, user.id, header + template["text"], reply_markup=main_menu_kb())
            append_chat(user.id, "user", вопрос)
            append_chat(user.id, "assistant", f"[шаблон: {template['title']}]")
            log_dialog(user, вопрос, f"(шаблон: {template['title']})", status="template")
            return
        await safe_send(context, user.id, TEMPLATE_CLARIFY_MSG, reply_markup=main_menu_kb())
        append_chat(user.id, "user", вопрос)
        append_chat(user.id, "assistant", TEMPLATE_CLARIFY_MSG)
        return

    # 3) Список инструкций
    if route.intent == INTENT_CATALOG or looks_like_catalog_list_request(вопрос):
        catalog_msg = format_catalog_list()
        await safe_send(context, user.id, catalog_msg, reply_markup=main_menu_kb())
        append_chat(user.id, "user", вопрос)
        append_chat(user.id, "assistant", catalog_msg)
        log_dialog(user, вопрос, "(список инструкций)", status="catalog")
        return

    # 3b) Калькулятор долива / персональный план по цифрам из MoniTrading
    doliv_plan = try_doliv_plan(вопрос)
    if doliv_plan:
        await safe_send(context, user.id, doliv_plan, reply_markup=main_menu_kb())
        append_chat(user.id, "user", вопрос)
        append_chat(user.id, "assistant", doliv_plan)
        log_dialog(user, вопрос, doliv_plan, status="bot:doliv_calc")
        return

    # 4) Официальные факты — ВСЕГДА до материалов/RAG
    # Диспетчер: policy (дословно) | adapt (перефраз под вопрос)
    priority = match_priority_answer(вопрос, history=history)
    if priority:
        mode = decide_answer_mode(
            вопрос, route.intent, history, has_priority=True
        )
        answer = render_text_answer(
            mode.mode, вопрос, priority, intent=route.intent
        )
        status = f"bot:{route.intent}:{mode.mode}"
        logging.info("Answer mode: %s", mode.label)
        await safe_send(context, user.id, answer, reply_markup=main_menu_kb())
        append_chat(user.id, "user", вопрос)
        append_chat(user.id, "assistant", answer)
        log_dialog(user, вопрос, answer, status=status)
        return

    # 5) Видео/PDF — ТОЛЬКО при намерении howto
    if allows_materials(route.intent):
        bundle = match_material_bundle(вопрос, history=history)
        if bundle:
            intro = "📄 Партнёрские программы брокеров:"
            await safe_send(context, user.id, intro, reply_markup=None)
            for i, mat in enumerate(bundle):
                kb = main_menu_kb() if i == len(bundle) - 1 else None
                await deliver_material(context, user.id, mat, reply_markup=kb)
            append_chat(user.id, "user", вопрос)
            titles = ", ".join(m["title"] for m in bundle)
            append_chat(user.id, "assistant", f"[материалы: {titles}]")
            log_dialog(user, вопрос, f"(материалы: {titles})", status="material")
            return

        material = match_material(вопрос, history=history)
        if material:
            await deliver_material(context, user.id, material, reply_markup=main_menu_kb())
            append_chat(user.id, "user", вопрос)
            append_chat(user.id, "assistant", f"[материал: {material['title']}]")
            log_dialog(user, вопрос, f"(материал: {material['title']})", status="material")
            return

        contextual_q = combine_with_context(вопрос, history)
        if looks_like_material_request(contextual_q):
            clarify = material_clarify_message()
            await safe_send(context, user.id, clarify, reply_markup=main_menu_kb())
            append_chat(user.id, "user", вопрос)
            append_chat(user.id, "assistant", clarify)
            return

    # 6) RAG — база знаний, затем диспетчер kb/adapt
    if route.intent == INTENT_DEFINE:
        search_q = вопрос
    else:
        search_q = build_search_query(вопрос, history)
        if search_q != вопрос:
            logging.info("Уточнение: «%s» → «%s»", вопрос[:80], search_q[:120])

    fragments = search_context(search_q)
    if not fragments and route.intent == INTENT_FOLLOWUP:
        alt_q = combine_with_context(вопрос, history)
        if alt_q != search_q:
            fragments = search_context(alt_q)

    if not fragments:
        if route.intent == INTENT_DEFINE:
            ответ = define_term_fallback(вопрос)
            await safe_send(context, user.id, ответ, reply_markup=main_menu_kb())
            append_chat(user.id, "user", вопрос)
            append_chat(user.id, "assistant", ответ)
            log_dialog(user, вопрос, ответ, status="bot:define:fallback")
            return
        await escalate_to_operator(update, context, вопрос, reason="not_found")
        return

    draft = generate_rag_answer(
        вопрос,
        fragments,
        history=None if route.intent == INTENT_DEFINE else history,
        intent=route.intent,
    )
    if not draft and route.intent == INTENT_DEFINE:
        draft = define_term_fallback(вопрос)
    if draft:
        mode = decide_answer_mode(
            вопрос, route.intent, history, has_priority=False
        )
        ответ = render_text_answer(
            mode.mode, вопрос, draft, intent=route.intent
        )
        logging.info("Answer mode: %s", mode.label)
        await safe_send(context, user.id, ответ, reply_markup=main_menu_kb())
        append_chat(user.id, "user", вопрос)
        append_chat(user.id, "assistant", ответ)
        log_dialog(user, вопрос, ответ, status=f"bot:{route.intent}:{mode.mode}")
    else:
        await escalate_to_operator(update, context, вопрос, reason="llm_uncertain")


# =====================================================================
#  MINI APP: кнопка меню + панель вложений (скрепка)
# =====================================================================
async def setup_miniapp(application: Application) -> None:
    """Кнопка «Материалы» слева от поля ввода + ссылка для панели вложений."""
    if not MINIAPP_URL:
        logging.info("MINIAPP_URL не задан — Mini App отключён")
        return
    try:
        me = await application.bot.get_me()
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📦 Материалы",
                web_app=WebAppInfo(url=MINIAPP_URL),
            )
        )
        logging.info("Menu Button Mini App: %s", MINIAPP_URL)
        if me.username:
            attach = f"https://t.me/{me.username}?startattach"
            logging.info(
                "Панель вложений (скрепка): BotFather → /setattach → %s | "
                "пользователь добавляет бота: %s",
                MINIAPP_URL,
                attach,
            )
    except Exception as e:
        logging.warning("Не удалось настроить Mini App menu button: %s", e)


# =====================================================================
#  ЗАПУСК
# =====================================================================
def main():
    if not TOKEN:
        print("ОШИБКА: Токен не найден! Проверьте .env")
        return
    if DISABLE_OPERATOR_ESCALATION:
        print("🔧 ТЕСТОВЫЙ РЕЖИМ: DISABLE_OPERATOR_ESCALATION=1 — в чат поддержки ничего не уходит.")
    elif not OPERATOR_GROUP_ID:
        print("ВНИМАНИЕ: OPERATOR_GROUP_ID не задан — перевод на оператора работать не будет.")

    init_sheet(GOOGLE_SHEET_ID)
    load_state()   # восстанавливаем диалоги после перезапуска

    app = Application.builder().token(TOKEN).post_init(setup_miniapp).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("materials", materials_command))
    app.add_handler(CommandHandler("operator", operator_command))
    app.add_handler(CommandHandler("close", close_dialog))
    app.add_handler(CommandHandler("active", active_command))
    app.add_handler(CallbackQueryHandler(show_topics_callback, pattern=r"^show_topics$"))
    app.add_handler(CallbackQueryHandler(doliv_calc_callback, pattern=r"^doliv_calc$"))
    app.add_handler(CallbackQueryHandler(call_operator_callback, pattern=r"^call_operator$"))
    app.add_handler(CallbackQueryHandler(take_dialog, pattern=r"^take:"))
    app.add_handler(CallbackQueryHandler(resolve_by_user, pattern=r"^resolve_user$"))
    app.add_handler(CallbackQueryHandler(end_by_operator, pattern=r"^endop:"))

    # сообщения из группы операторов (любой контент с Reply)
    app.add_handler(MessageHandler(
        filters.Chat(OPERATOR_GROUP_ID) & ~filters.COMMAND,
        operator_group_message
    ))

    # ловим и удаляем системное "бот закрепил сообщение" (только в личке) — ВАЖНО: до handle_message
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.StatusUpdate.PINNED_MESSAGE,
        delete_pin_notification
    ))

    # сообщения от пользователей в личке (любой контент)
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_message
    ))

    app.job_queue.run_repeating(check_timeouts, interval=CHECK_INTERVAL, first=CHECK_INTERVAL)

    print("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()