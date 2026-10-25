"""Распознавание запросов на шаблоны и отправка текста в чат."""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from dialog_context import expand_aliases

RESOURCES = Path(__file__).parent / "resources" / "resources.json"

_TEMPLATE_CACHE: list[dict] | None = None

TEMPLATE_CLARIFY_MSG = (
    "Уточните, какой шаблон нужен:\n"
    "• установка / тест\n"
    "• обновление советника\n"
    "• перенос между брокерами\n"
    "• перенос на новый сервер\n\n"
    "Или откройте 📦 Материалы → раздел «Шаблоны»."
)

# Ключевые слова в запросе → фрагменты в названии шаблона
_HINTS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("установ",), ("установк",)),
    (("тест",), ("тест",)),
    (("заявк",), ("заявк",)),
    (("обнов",), ("обновлен",)),
    (("перенос", "брокер"), ("перенос", "брокер")),
    (("перенос", "сервер"), ("перенос", "сервер")),
    (("новый сервер",), ("новый сервер",)),
]

_CLARIFY_MARKERS = (
    "уточните, какой шаблон",
    "какой шаблон нужен",
    "раздел «шаблоны»",
)


def _norm(s: str) -> str:
    return expand_aliases(s)


def load_templates() -> list[dict]:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE
    if not RESOURCES.is_file():
        _TEMPLATE_CACHE = []
        return _TEMPLATE_CACHE
    data = json.loads(RESOURCES.read_text(encoding="utf-8"))
    out = []
    for cat in data.get("categories", []):
        if cat.get("id") != "other":
            continue
        for item in cat.get("items", []):
            if item.get("type") == "text" and item.get("text"):
                out.append(item)
    _TEMPLATE_CACHE = out
    return out


def _history_pairs(history) -> list[tuple[str, str]]:
    if not history:
        return []
    out: list[tuple[str, str]] = []
    for entry in history:
        if isinstance(entry, dict):
            out.append((entry.get("role", ""), entry.get("text", "")))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            out.append((entry[0], entry[1]))
    return out


def awaiting_template_choice(history) -> bool:
    """Бот только что спросил, какой шаблон нужен."""
    for role, text in reversed(_history_pairs(history)[-6:]):
        if role != "assistant":
            continue
        low = text.lower()
        if any(m in low for m in _CLARIFY_MARKERS):
            return True
        if low.startswith("[шаблон:"):
            return False
    return False


def _match_by_hints(text: str, templates: list[dict]) -> dict | None:
    t = _norm(text)
    for item in templates:
        title = _norm(item.get("title", ""))
        for req_words, title_words in _HINTS:
            if all(w in t for w in req_words) and all(w in title for w in title_words):
                return item
    return None


def _is_template_topic_phrase(text: str, templates: list[dict]) -> bool:
    t = _norm(text)
    if len(t) > 64:
        return False
    return _match_by_hints(text, templates) is not None


def _is_general_howto_question(text: str) -> bool:
    """«Что нужно / как установить…» — вопрос по процессу, не запрос шаблона."""
    t = _norm(text)
    if re.search(r"\b(?:что|как)\s+(?:нужно|надо|необходимо)\b", t):
        return True
    if "чтобы начать" in t or "как начать" in t or "с чего начать" in t:
        return True
    # «как установить / как его установить / как подключить советника»
    if re.search(
        r"как\s+(?:его\s+|её\s+|ее\s+|мне\s+)?(?:установ|подключ|активир)",
        t,
    ):
        return True
    # «установить торгового советника» без слова «шаблон»
    if re.search(r"(?:установ|подключ|активир)", t) and any(
        w in t for w in ("советник", "робот", "лиценз")
    ):
        return True
    return False


def looks_like_template_request(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    if _is_general_howto_question(text):
        return False
    if re.search(r"(?:^|\s)не\s+шаблон", t):
        return False
    if re.search(r"(?:^|\s)не\s+нужен\s+шаблон", t):
        return False
    if "шаблон" in t:
        return True

    templates = load_templates()
    # Короткая фраза «установка» / «тест» — только как ответ на уточнение
    # «какой шаблон?», не как самостоятельный вопрос «как установить».
    # Здесь без history: считаем topic-phrase только если это одно слово/тема
    # без вопросительного howto (howto уже отсечён выше).
    if _is_template_topic_phrase(text, templates):
        # «установить советника» уже отсечено; остаётся «установка», «обновление»…
        # Не считать howto-вопросы с «как/что» шаблоном.
        if re.search(r"(?:^|\s)(?:как|что|зачем|почему)\b", t):
            return False
        return True

    material_topics = (
        "регистр", "форекс", "forex", "roboforex", "робо", "пополн",
        "vps", "govps", "мониторинг", "monitrading", "fxmonitor", "сушк", "презент",
        "видео", "инструкц", "брокер",
    )
    template_topics = ("установ", "обнов", "перенос", "тест", "заявк")
    action_verbs = ("скинь", "скиньте", "пришли", "пришлите", "дай", "дайте", "отправь", "отправьте")

    if any(k in t for k in material_topics) and not any(w in t for w in template_topics):
        return False

    if "шаблон" in t and any(w in t for w in action_verbs + ("нужен", "нужна", "нужно")):
        return True

    return any(v in t for v in action_verbs) and any(
        k in t for k in template_topics + ("шаблон", "заявк")
    )


def match_template(text: str, history=None) -> dict | None:
    """Возвращает шаблон из каталога или None."""
    templates = load_templates()
    if not templates:
        return None

    t = _norm(text)

    # Ответ на «какой шаблон нужен?» — «обновление советника» и т.п.
    if history and awaiting_template_choice(history):
        hinted = _match_by_hints(text, templates)
        if hinted:
            return hinted

    if not looks_like_template_request(text):
        return None

    if "шаблон" in t and not any(
        w in t for w in ("установ", "обнов", "перенос", "тест", "заявк", "брокер", "сервер", "советник")
    ):
        if not _is_template_topic_phrase(text, templates):
            return None

    hinted = _match_by_hints(text, templates)
    if hinted:
        return hinted

    scored: list[tuple[float, dict]] = []
    for item in templates:
        title = _norm(item.get("title", ""))
        score = SequenceMatcher(None, t, title).ratio()

        if "шаблон" in t:
            for word in title.split():
                if len(word) > 4 and word in t:
                    score = max(score, 0.75)

        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 0.42:
        return None
    if len(scored) > 1 and scored[1][0] >= best_score - 0.08:
        if best_score < 0.7:
            return None
    return best
