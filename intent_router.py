"""Классификация намерения пользователя: сначала правила, при сомнении — Groq."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from aggression import is_legitimacy_doubt, needs_operator
from dialog_context import (
    expand_aliases,
    extract_advisor_entity,
    history_pairs,
    is_vague_followup,
    normalize_user_question,
)
from materials import looks_like_catalog_list_request, looks_like_material_request

# Каналы ответа
INTENT_OPERATOR = "operator"
INTENT_GREETING = "greeting"
INTENT_TEMPLATE = "template"
INTENT_CATALOG = "catalog"
INTENT_TRUST = "trust"
INTENT_POLICY = "policy"
INTENT_DEFINE = "define"
INTENT_HOWTO = "howto"
INTENT_SPECS = "specs"
INTENT_FOLLOWUP = "followup"
INTENT_RAG = "rag"

ALL_INTENTS = (
    INTENT_OPERATOR,
    INTENT_GREETING,
    INTENT_TEMPLATE,
    INTENT_CATALOG,
    INTENT_TRUST,
    INTENT_POLICY,
    INTENT_DEFINE,
    INTENT_HOWTO,
    INTENT_SPECS,
    INTENT_FOLLOWUP,
    INTENT_RAG,
)

GREETING_REPLY = (
    "Здравствуйте! Я бот поддержки EMAR Capital — помогаю по торговым советникам, "
    "MoniTrading, VPS, брокерам и инструкциям.\n\n"
    "Напишите вопрос своими словами или откройте 📦 Материалы в меню."
)

CAPABILITIES_REPLY = """Я бот техподдержки EMAR Capital. Вот основное, чем могу помочь:

🔧 Советники и настройка
Classic, King, Trinity — что это, как работают, как установить и подключить.
Регистрация у брокера, аренда VPS-сервера.

📊 Счёт и контроль
Просадка: когда сушка, когда долив — посчитаю персонально по вашим цифрам.
MoniTrading — как смотреть счёт с телефона.
Пополнение и вывод средств.

📦 Материалы
Видео, PDF-инструкции, шаблоны заявок в поддержку — пришлю прямо в чат.

💬 И конечно — вопросы про компанию, риски, доходность, тестовый период.

Пишите своими словами, разберёмся. Если нужен живой человек — жмите «Позвать оператора» 👇"""


@dataclass
class RouteDecision:
    intent: str
    source: str  # rules | llm
    confidence: float
    reason: str = ""


def _norm(text: str) -> str:
    t = expand_aliases(normalize_user_question(text or ""))
    return re.sub(r"\s+", " ", t.lower()).strip()


def _is_definition(text: str) -> bool:
    t = _norm(text).replace("ьэто", "это")
    if re.search(r"\bчто\s+(это|такое|за)\b", t):
        return True
    if re.search(r"\bче\s+(это|такое|за)\b", t):
        return True
    if re.search(r"\bэто\s+что\b", t):
        return True
    # «что нужно для работы с X» — требования/суть, не видео
    if re.search(r"\bчто\s+нужн[оа]\b", t) and not re.search(
        r"\bвидео|инструкц|скинь|пришли\b", t
    ):
        return True
    if re.search(r"\bзачем(\s+он)?(\s+нужен)?\b", t) and not re.search(
        r"\bкак\b", t
    ):
        return True
    if re.search(r"\bдля\s+чего\b|\bпреимуществ|\bособенност|\bназначен", t):
        return True
    return False

def _is_policy(text: str) -> bool:
    """Только своя просадка / что делать. «Что такое сушка/долив» — define, не policy."""
    from priority_qa import _is_drawdown_action_question

    return _is_drawdown_action_question(text)


def _is_trust(text: str) -> bool:
    if is_legitimacy_doubt(text):
        return True
    t = _norm(text)
    if re.search(r"кто\s+(такая|такое|такие|вы)|что\s+за\s+компани|о\s+компани", t):
        return True
    if ("emar" in t or "емар" in t) and any(w in t for w in ("кто", "что", "компани", "это")):
        return True
    return bool(re.search(r"расскажите\s+о\s+компани|чем\s+занимается", t))


def _is_template(text: str) -> bool:
    t = _norm(text)
    if "не шаблон" in t or "не нужен шаблон" in t:
        return False
    return "шаблон" in t or "заявк" in t and "техподдерж" in t


def _is_howto(text: str) -> bool:
    t = _norm(text)
    if _is_definition(text):
        return False
    # общее пополнение/вывод без брокера — не видео (ответ из priority/базы)
    deposit_like = any(w in t for w in ("пополн", "вывод", "вывести")) and any(
        w in t for w in ("депозит", "сч", "средств", "деньг", "баланс")
    )
    has_broker = any(
        k in t for k in ("forex", "форекс", "roboforex", "робофорекс", "робо")
    )
    wants_media = any(k in t for k in ("видео", "инструкц", "скинь", "пришли", "покажи"))
    if deposit_like and not has_broker and not wants_media:
        return False
    # явный запрос инструкции / видео / регистрации
    if any(
        w in t
        for w in (
            "видео", "инструкц", "скинь", "пришли", "покажи", "пдф", " pdf",
            "как зарегист", "как зарегать", "как зайти", "как войти",
            "как аренд", "как подключ", "как установ",
        )
    ):
        return True
    # «как его установить?» — нет непрерывной строки «как установ»
    if re.search(r"как\s+(?:его\s+|её\s+|ее\s+|мне\s+)?(?:установ|подключ|активир)", t):
        return True
    if re.search(r"(?:^|\s)как\s+", t) and any(
        k in t
        for k in (
            "регист", "зарегист", "регать", "vps", "сервер", "брокер",
            "forex", "roboforex", "мониторинг", "monitrading", "govps",
            "сушк", "обмен", "советник", "робот",
        )
    ):
        return True
    if has_broker and deposit_like:
        return True
    if looks_like_material_request(text) and not _is_definition(text):
        return True
    return False


def _is_specs(text: str) -> bool:
    t = _norm(text)
    if extract_advisor_entity(text):
        if any(
            w in t
            for w in (
                "параметр", "характеристик", "настройк", "депозит", "лот",
                "пары", "принцип", "как работает", "доход", "риск", "спецификац",
            )
        ):
            return True
        # голое имя советника / линейки — тоже specs/rag
        if len(t) < 48:
            return True
    if any(
        w in t
        for w in (
            "техническ", "параметр", "характеристик", "принцип работы",
            "как работает советник",
        )
    ):
        return True
    return False


def _is_followup(text: str, history) -> bool:
    if not history:
        return False
    if is_vague_followup(text):
        return True
    t = _norm(text)
    if len(t) < 40 and re.search(
        r"^(а |и |ну |ещё|еще|там|тут|про него|у него|какие|какие у)",
        t,
    ):
        return True
    return False


def _history_snippet(history, limit: int = 4) -> str:
    lines = []
    for role, msg in history_pairs(history)[-limit:]:
        label = "Клиент" if role == "user" else "Бот"
        lines.append(f"{label}: {msg[:180]}")
    return "\n".join(lines)


def _is_greeting(text: str) -> bool:
    t = _norm(text)
    if not t or len(t) > 80:
        return False
    # «привет», «привет, ты кто», «кто ты»
    if re.fullmatch(
        r"(привет|здравствуй(те)?|добрый\s+(день|вечер|утро)|хи+|хай|hello|hi)"
        r"([!?.\s,]*)"
        r"(как\s+дела|ты\s+кто|кто\s+ты|кто\s+вы|что\s+ты(?:\s+умеешь)?)?"
        r"[!?.\s,]*",
        t,
    ):
        return True
    if re.search(r"\b(привет|здравствуйте)\b", t) and re.search(
        r"\b(ты\s+кто|кто\s+ты|кто\s+вы)\b", t
    ):
        return True
    if re.fullmatch(r"(ты\s+кто|кто\s+ты|кто\s+вы)[?!]*", t):
        return True
    return False


def _is_capabilities(text: str) -> bool:
    t = _norm(text)
    t = re.sub(r"[?!.,;:]+$", "", t).strip()
    phrases = (
        "что ты можешь",
        "что ты умеешь",
        "что умеешь",
        "чем можешь помочь",
        "что можешь",
        "как ты можешь помочь",
        "твои функции",
        "что делаешь",
    )
    return t in phrases or any(t.startswith(p) for p in phrases)


def classify_by_rules(text: str, history=None) -> Optional[RouteDecision]:
    """Быстрые правила. None — нужна LLM."""
    raw = text or ""
    t = _norm(raw)

    if not t:
        return RouteDecision(INTENT_RAG, "rules", 0.5, "empty")

    if _is_greeting(raw):
        return RouteDecision(INTENT_GREETING, "rules", 0.95, "greeting")

    if _is_capabilities(raw):
        return RouteDecision(INTENT_GREETING, "rules", 0.95, "capabilities")

    if needs_operator(raw) and not is_legitimacy_doubt(raw):
        return RouteDecision(INTENT_OPERATOR, "rules", 0.95, "aggression/operator")

    if _is_trust(raw):
        return RouteDecision(INTENT_TRUST, "rules", 0.92, "trust/company")
    if _is_template(raw):
        return RouteDecision(INTENT_TEMPLATE, "rules", 0.9, "template")

    if looks_like_catalog_list_request(raw):
        return RouteDecision(INTENT_CATALOG, "rules", 0.9, "catalog list")

    # Определение раньше policy: «что такое сушка/долив» → define → RAG
    if _is_definition(raw):
        return RouteDecision(INTENT_DEFINE, "rules", 0.92, "definition")

    if _is_policy(raw):
        return RouteDecision(INTENT_POLICY, "rules", 0.93, "drawdown/doliv")

    if _is_howto(raw):
        return RouteDecision(INTENT_HOWTO, "rules", 0.88, "howto/material")

    if _is_specs(raw):
        return RouteDecision(INTENT_SPECS, "rules", 0.85, "advisor specs")

    if _is_followup(raw, history):
        return RouteDecision(INTENT_FOLLOWUP, "rules", 0.8, "dialog followup")

    # Типичные темы академии — сразу в базу, без лишнего LLM
    if any(
        w in t
        for w in (
            "заработ", "доход", "прибыл", "риск", "брокер", "тестов",
            "активац", "эквити", "маржа", "своп", "советник", "робот",
            "classic", "king", "trinity", "emar",
        )
    ):
        return RouteDecision(INTENT_RAG, "rules", 0.82, "kb topic")

    return None


def classify_by_llm(text: str, history=None) -> RouteDecision:
    """Один короткий вызов LLM — намерение одной меткой."""
    from ai_utils import _call_llm

    hist = _history_snippet(history) if history else "(нет)"
    system = (
        "Ты классификатор намерений для бота техподдержки EMAR Capital (Forex-советники).\n"
        "Выбери РОВНО ОДНУ метку из списка и ответь только ей (латиницей, нижний регистр):\n"
        "operator — зовут человека / мат / угрозы\n"
        "trust — мошенники, скам, кто такая компания\n"
        "template — нужен текстовый шаблон заявки\n"
        "catalog — список всех инструкций/видео\n"
        "policy — просадка, долив, сушка, что делать при риске\n"
        "define — что такое / что это / зачем нужен (определение понятия)\n"
        "howto — как сделать: регистрация, видео, инструкция, вход на VPS\n"
        "specs — параметры/характеристики/принцип работы советника\n"
        "followup — короткое уточнение к предыдущей теме диалога\n"
        "rag — обычный вопрос по базе знаний\n"
    )
    user = (
        f"История:\n{hist}\n\n"
        f"Сообщение клиента: {text}\n\n"
        "Метка:"
    )
    try:
        raw = _call_llm(system, user, max_out=600)
        if not raw:
            return RouteDecision(INTENT_RAG, "llm", 0.4, "llm_fallback_rag")
        token = re.split(r"[\s,.;:]+", raw.strip().lower())[0]
        if token in ALL_INTENTS:
            return RouteDecision(token, "llm", 0.75, f"llm:{token}")
        logging.warning("Intent LLM unknown label: %s", raw[:40])
    except Exception as e:
        logging.warning("Intent LLM error: %s", e)
    return RouteDecision(INTENT_RAG, "llm", 0.4, "llm_fallback_rag")


def classify_intent(text: str, history=None) -> RouteDecision:
    """Итоговое намерение: правила → при сомнении LLM → иначе rag без LLM."""
    by_rules = classify_by_rules(text, history)
    if by_rules and by_rules.confidence >= 0.8:
        return by_rules
    # Короткие реплики не гоняем в Groq (лимиты TPD) — сразу база/контекст
    t = _norm(text)
    if len(t) < 25:
        return by_rules or RouteDecision(INTENT_RAG, "rules", 0.55, "short_default_rag")
    try:
        llm = classify_by_llm(text, history)
    except Exception as e:
        logging.warning("classify_intent LLM skip: %s", e)
        return by_rules or RouteDecision(INTENT_RAG, "rules", 0.5, "llm_error_rag")
    if by_rules and by_rules.intent == llm.intent:
        return RouteDecision(
            llm.intent, "rules+llm", max(by_rules.confidence, llm.confidence), by_rules.reason
        )
    if by_rules and llm.confidence < 0.6:
        return by_rules
    # llm_fallback_rag при 429 — не тратим дальше
    if llm.reason == "llm_fallback_rag":
        return by_rules or llm
    return llm

def allows_materials(intent: str) -> bool:
    """Видео/PDF только для howto (и каталога — отдельный канал)."""
    return intent == INTENT_HOWTO


def prefers_priority(intent: str) -> bool:
    return intent in (INTENT_TRUST, INTENT_POLICY, INTENT_DEFINE)


def prefers_rag(intent: str) -> bool:
    return intent in (
        INTENT_DEFINE,
        INTENT_SPECS,
        INTENT_FOLLOWUP,
        INTENT_RAG,
        INTENT_POLICY,
        INTENT_TRUST,
    )
