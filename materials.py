"""Распознавание запросов на материалы и формирование ответа (видео-ссылки / файлы)."""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from dialog_context import combine_with_context, expand_aliases, history_pairs, is_vague_followup
from brand import apply_brand_terms

RESOURCES = Path(__file__).parent / "resources" / "resources.json"
FILES_DIR = Path(__file__).parent / "resources" / "files"

_MATERIAL_CACHE: list[dict] | None = None

_HINTS: list[tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]] = [
    ((("forex4", "форекс4", "forex4you", "форексе", "форекс", "forex"), ("регист", "зарегист", "регать", "регаться", "пополн", "депозит", "открыт")), ("forex4you",)),
    ((("forex4", "форекс4", "forex4you", "форексе", "форекс", "forex"), ("пополн", "депозит", "счет", "счёт")), ("forex4you",)),
    ((("roboforex", "робофорекс", "робо форекс", "робо", "roboforex"), ("регист", "зарегист", "регать")), ("roboforex", "регист")),
    ((("roboforex", "робофорекс", "робо", "roboforex"), ("пополн", "депозит", "счет", "счёт")), ("roboforex", "пополн")),
    ((("govpsfx", "govps"), ("регист", "зарегист", "аренд", "зарегать")), ("govps",)),
    ((("сервер", "vps", "впс"), ("регист", "зарегист", "аренд", "зарегать")), ("регист", "govps")),
    ((("vps", "впс"), ("зайти", "войти", "заход", "подключ")), ("vps", "зайти")),
    ((("monitrading", "монитрейдинг"), ("регист", "зарегист")), ("регист", "monitrading")),
    ((("monitrading", "монитрейдинг", "fxmonitor", "fx monitor", "фхмонитор", "мониторинг"), ("обзор",)), ("обзор", "monitrading")),
    # НЕ матчить голый monitrading → «Краткий обзор» (ломает «что нужно для работы»)
    ((("monitrading", "fxmonitor", "мониторинг"), ("поделиться", "поделится", "подел")), ("поделиться", "мониторинг")),
    ((("сушк", "сушку", "сушки"),), ("сушк",)),
    ((("king", "кинг"), ("презент", "мониторинг")), ("king",)),
    ((("trinity", "тринити", "технолог"), ("презент", "мониторинг")), ("trinity", "технолог")),
    ((("emar", "емар"), ("официальн", "презент")), ("официальн", "презентац")),
    ((("roboforex", "робофорекс"), ("партнер", "пдф", "pdf")), ("roboforex", "партнер")),
    ((("forex4", "форекс4", "forex4you", "форекс"), ("партнер", "пдф", "pdf")), ("forex4", "партнер")),
    ((("forex4", "форекс4", "forex4you", "форекс"), ("маркет", "маркетнг", "маркетинг", "план")), ("маркет", "forex")),
    ((("маркетинг", "маркетнг", "маркет"), ("план",)), ("маркетинг", "emar")),
    ((("emar", "емар"), ("маркетинг", "маркетнг", "маркет", "план")), ("маркетинг", "emar")),
    ((("обои",),), ("обои",)),
    ((("звук",), ("уведомлен", "fxmonitor", "мониторинг")), ("звук",)),
    ((("условн", "обозначен"), ("monitrading", "fxmonitor", "мониторинг", "валютн")), ("обозначен", "monitrading")),
    ((("forex4", "форекс"), ("ссылк", "реферал", "реф код", "партнер")), ("ссылку", "forex")),
    ((("эмодзи", "emoji"), ("статус", "telegram", "телеграм")), ("эмодзи",)),
    ((("cardex", "кардекс", "обменник"),), ("cardex",)),
    ((("trinity", "king", "myfxbook"), ("ссылк", "мониторинг")), ("мониторинги", "компании")),
]


# Подписи из каталога → материал (когда пользователь копирует пункт из списка)
_CATALOG_ALIASES: dict[str, str] = {
    "регистрация forex4you": "Forex4You: регистрация, открытие счета и пополнение",
    "регистрация roboforex": "Регистрация на брокере ROBOFOREX",
    "пополнение счета": "Forex4You: регистрация, открытие счета и пополнение",
    "пополнение счёта": "Forex4You: регистрация, открытие счета и пополнение",
    "пополнение forex4you": "Forex4You: регистрация, открытие счета и пополнение",
    "открытие счета forex4you": "Forex4You: регистрация, открытие счета и пополнение",
    "пополнение roboforex": "Пополнение брокера ROBOFOREX",
    "регистрация и аренда сервера govpsfx": "Регистрация и аренда сервера GOVPSFX",
    "как зарегать сервер": "Регистрация и аренда сервера GOVPSFX",
    "как зарегистрировать сервер": "Регистрация и аренда сервера GOVPSFX",
    "как зайти на vps сервер": "Как зайти на VPS сервер",
    "регистрация monitrading": "MoniTrading: Регистрация и обзор",
    "регистрация fxmonitor": "MoniTrading: Регистрация и обзор",
    "регистрация мониторинга": "MoniTrading: Регистрация и обзор",
    "monitrading регистрация": "MoniTrading: Регистрация и обзор",
    "monitrading обзор": "MoniTrading: Регистрация и обзор",
    "краткий обзор monitrading": "Краткий обзор MoniTrading",
    "обзор monitrading": "Краткий обзор MoniTrading",
    # НЕ добавлять голый «monitrading» / «fxmonitor» — иначе «что это» уходит в видео
}

_RAG_TOPIC_WORDS = (
    "риск", "заработ", "доход", "прибыл", "просадк", "долив", "критическ",
    "брокер", "робот", "советник", "что такое", "что это", "почему", "зачем",
    "преимуществ", "особенност",
)


def _is_definition_question(text: str) -> bool:
    """«что это / что такое / что за» — ответ из базы, не видео-инструкция."""
    t = _norm(text)
    t = t.replace("ьэто", "это").replace("ето ", "это ")
    if re.search(r"\bчто\s+(это|такое|за)\b", t):
        return True
    if re.search(r"\bче\s+(это|такое|за)\b", t):
        return True
    if re.search(r"\bэто\s+что\b", t) or " это что" in f" {t}":
        return True
    if t.endswith(" что это") or t.endswith(" что такое"):
        return True
    return False


def _has_kak_question(t: str) -> bool:
    if re.search(r"\bкакие\b", t):
        return False
    return bool(re.search(r"(?:^|\s)как\s", t) or t.startswith("как "))


def _looks_like_rag_followup(text: str) -> bool:
    t = _norm(text)
    if _is_definition_question(text):
        return True
    if any(w in t for w in _RAG_TOPIC_WORDS):
        return True
    if re.search(r"\bчто\s+такое\b", t) or re.search(r"\bчто\s+это\b", t):
        return True
    # «как пополнить депозит» без брокера — ответ из базы знаний, не видео/PDF
    if any(w in t for w in ("пополн", "депозит", "вывод", "вывести")):
        has_broker = any(
            k in t for k in ("forex", "форекс", "forex4", "roboforex", "робофорекс", "робо")
        )
        wants_media = any(
            k in t for k in ("видео", "инструкц", "pdf", "пдф", "скинь", "покажи", "пришли")
        )
        if not has_broker and not wants_media:
            return True
    return False


def _match_catalog_alias(text: str, materials: list[dict]) -> dict | None:
    t = _norm(text)
    # Определения не матчим на видео
    if _is_definition_question(text):
        return None

    title_by_norm = {_norm(m.get("title", "")): m for m in materials}

    if "обзор" in t and any(k in t for k in ("monitrading", "fxmonitor", "фхмонитор", "монитрейдинг")):
        for norm_title, item in title_by_norm.items():
            if "обзор" in norm_title and "monitrading" in norm_title:
                return item

    if t in _CATALOG_ALIASES:
        want = _norm(_CATALOG_ALIASES[t])
        for norm_title, item in title_by_norm.items():
            if want in norm_title or norm_title in want:
                return item

    best: tuple[int, dict] | None = None
    for alias, title in sorted(_CATALOG_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in t:
            want = _norm(title)
            for norm_title, item in title_by_norm.items():
                if want in norm_title:
                    cand = (len(alias), item)
                    if best is None or cand[0] > best[0]:
                        best = cand
    if best:
        return best[1]

    return None


def _norm(s: str) -> str:
    return expand_aliases(s)


def _load_catalog() -> dict:
    if not RESOURCES.is_file():
        return {}
    return json.loads(RESOURCES.read_text(encoding="utf-8"))


def load_materials() -> list[dict]:
    global _MATERIAL_CACHE
    if _MATERIAL_CACHE is not None:
        return _MATERIAL_CACHE
    if not RESOURCES.is_file():
        _MATERIAL_CACHE = []
        return _MATERIAL_CACHE
    data = json.loads(RESOURCES.read_text(encoding="utf-8"))
    out: list[dict] = []
    for cat in data.get("categories", []):
        cat_id = cat.get("id", "")
        for item in cat.get("items", []):
            t = item.get("type")
            if t == "video":
                out.append(item)
            elif t == "file":
                out.append(item)
            elif t in ("text", "info") and cat_id == "info":
                out.append(item)
    _MATERIAL_CACHE = out
    return out


def looks_like_material_request(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    if _looks_like_rag_followup(text) and "видео" not in t and "инструкц" not in t:
        return False
    if "шаблон" in t and not re.search(r"(?:^|\s)не\s+шаблон", t):
        return False
    if re.search(r"(?:^|\s)не\s+шаблон", t) or re.search(r"(?:^|\s)не\s+нужен\s+шаблон", t):
        return True

    if "шаблон" in t:
        return False

    strong = (
        "покажи", "скинь", "скиньте", "пришли", "пришлите", "отправь",
        "не понимаю", "не понял", "не поняла", "не знаю как", "объясни как",
        "есть видео", "есть инструкц", "дай видео", "дай ссылку", "нужно видео",
        "нужна инструкц", "нужен видео", "нужна видео", "мне нужна", "мне нужно",
        "нужна регистрац", "нужно регистрац", "хочу видео", "нужен обзор",
    )
    if any(m in t for m in strong):
        return True

    if _has_kak_question(t) and any(
        k in t
        for k in (
            "регист", "зарегист", "регать", "зайти", "войти",
            "vps", "форекс", "forex", "roboforex", "робо", "мониторинг",
            "сушк", "govps", "сервер", "зарегать",
        )
    ):
        return True

    if _has_kak_question(t) and any(k in t for k in ("пополн", "депозит", "вывод", "вывести")):
        has_broker = any(
            k in t for k in ("forex", "форекс", "forex4", "roboforex", "робофорекс", "робо")
        )
        wants_media = any(
            k in t for k in ("видео", "инструкц", "pdf", "пдф", "скинь", "покажи", "пришли")
        )
        if has_broker or wants_media:
            return True

    if any(m in t for m in ("видео", "инструкц", " pdf", "пдф")) and len(t) < 140:
        return True

    if any(k in t for k in ("регистрац", "брокер")) and any(
        k in t for k in ("форекс", "forex", "roboforex", "робо", "forex4")
    ):
        return True

    if any(k in t for k in ("cardex", "кардекс")) or "обменник" in t:
        return True

    if "мониторинг" in t and any(
        k in t for k in ("trinity", "king", "myfxbook", "fxmonitor", "ссылк", "компани")
    ):
        return True

    if "эмодзи" in t or ("статус" in t and "telegram" in t):
        return True

    if "реферал" in t or ("ссылк" in t and "forex" in t):
        return True

    if any(k in t for k in ("маркетинг", "маркетнг")) and "план" in t:
        return True

    if "партнер" in t and any(k in t for k in ("программ", "есть", "pdf", "пдф", "документ", "файл")):
        return True

    # «нужно/нужен» слишком широко («что нужно для работы») — только явный запрос медиа
    if any(k in t for k in ("monitrading", "fx monitor", "fxmonitor", "фхмонитор")) and any(
        k in t for k in ("обзор", "видео", "скинь", "пришли", "инструкц")
    ):
        return True

    if "пополн" in t and ("счет" in t or "счёт" in t):
        return True

    if t in _CATALOG_ALIASES or any(alias in t for alias in _CATALOG_ALIASES):
        return True

    if any(k in t for k in ("пополн", "депозит", "счет", "счёт")) and any(
        k in t for k in ("forex", "форекс", "roboforex", "робофорекс", "робо", "брокер")
    ):
        return True

    if any(k in t for k in ("регист", "зарегист")) and any(
        k in t for k in ("forex", "форекс", "roboforex", "робофорекс", "брокер")
    ):
        return True

    return False


def looks_like_catalog_list_request(text: str) -> bool:
    t = _norm(text)
    if not t or "шаблон" in t:
        return False
    list_markers = (
        "какие инструкц", "какие видео", "какие материал", "список инструкц",
        "что есть", "что у вас", "что у нас", "какие у нас", "перечисли",
        "какие есть", "есть инструкц", "есть видео", "есть материал",
    )
    if any(m in t for m in list_markers):
        return True
    if ("инструкц" in t or "материал" in t or "видео" in t) and any(
        k in t for k in ("какие", "какая", "список", "перечисл", "есть ли")
    ):
        return True
    return False


def format_catalog_list() -> str:
    data = _load_catalog()
    lines = ["📚 Доступные инструкции и материалы:\n"]

    for cat_id, header in (
        ("instructions", "📋 Видео-инструкции"),
        ("documents", "📄 PDF и документы"),
        ("info", "ℹ️ Полезная информация"),
    ):
        cat = next((c for c in data.get("categories", []) if c.get("id") == cat_id), None)
        if not cat or not cat.get("items"):
            continue
        lines.append(header)
        for item in cat["items"]:
            title = item.get("title", "")
            if item.get("type") == "video" or item.get("video_links"):
                lines.append(f"• {title} (видео)")
            elif item.get("media") == "pdf":
                lines.append(f"• {title} (PDF)")
            else:
                lines.append(f"• {title}")
        lines.append("")

    lines.append("Напишите, что нужно — например: «пополнение счёта forex» или «нужно видео».")
    lines.append("Или откройте 📦 Материалы в меню бота.")
    return "\n".join(lines)


def _broker_bias(query: str) -> str | None:
    t = _norm(query)
    if any(k in t for k in ("roboforex", "робофорекс", "робо")):
        return "roboforex"
    if any(k in t for k in ("forex4you", "forex4", "форекс4", "forex", "форекс")):
        return "forex"
    return None


def _pick_best(scored: list[tuple[float, dict]], query: str) -> dict | None:
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 0.52:
        return None

    bias = _broker_bias(query)
    if bias and len(scored) > 1 and scored[1][0] >= best_score - 0.12:
        for score, item in scored:
            if bias in _norm(item.get("title", "")) and score >= best_score - 0.15:
                return item

    if len(scored) > 1 and scored[1][0] >= best_score - 0.1 and best_score < 0.82:
        return None
    return best


def _hint_score(msg: str, title: str) -> float:
    msg = _norm(msg)
    title_n = _norm(title)
    for groups, title_need in _HINTS:
        ok = True
        for group in groups:
            if group and not any(w in msg for w in group):
                ok = False
                break
        if not ok:
            continue
        if title_need and not all(w in title_n for w in title_need):
            continue
        return 0.95
    return 0.0


def _looks_like_partner_programs_request(text: str) -> bool:
    t = _norm(text)
    if "партнер" not in t:
        return False
    if any(k in t for k in ("программ", "есть", "какие", "скинь", "пришли", "pdf", "пдф", "документ", "файл")):
        return True
    return bool(re.search(r"партнерск\w*\s+программ", t))


def _partner_program_items(materials: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in materials:
        if item.get("media") != "pdf":
            continue
        title = _norm(item.get("title", ""))
        if "партнер" not in title and "маркет" not in title:
            continue
        if "roboforex" in title or "forex" in title:
            key = item.get("file") or item.get("title", "")
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def match_material(text: str, history=None) -> dict | None:
    materials = load_materials()
    if not materials:
        return None

    raw_n = _norm(text)
    query = combine_with_context(text, history)
    query_n = _norm(query)
    # Guard до alias: просадка/долив/сушка — не материалы
    if any(w in raw_n for w in ("просадк", "долив", "подушк", "сушк")) or any(
        w in query_n for w in ("просадк", "долив", "подушк", "сушк")
    ):
        return None
    # «MoniTrading что это» — определение из базы, не видео регистрации
    if _is_definition_question(text):
        return None

    if _is_definition_question(query):
        return None

    alias_hit = _match_catalog_alias(query, materials)
    if alias_hit:
        return alias_hit

    if not looks_like_material_request(query):
        return None

    t = _norm(query)
    scored: list[tuple[float, dict]] = []
    for item in materials:
        title = _norm(item.get("title", ""))
        score = max(
            _hint_score(t, title),
            SequenceMatcher(None, t, title).ratio(),
        )
        for word in title.split():
            if len(word) > 4 and word in t:
                score = max(score, 0.72)
        # Не путать «как пополнить» с материалами без «пополн» в названии
        if any(w in t for w in ("пополн", "депозит", "вывод", "вывести")) and "пополн" not in title:
            score *= 0.2
        if any(w in t for w in ("пополн", "депозит")) and "пополн" in title:
            score = max(score, 0.88)
        scored.append((score, item))

    return _pick_best(scored, query)


def _recent_assistant_tag(history, prefix: str) -> bool:
    for role, msg in reversed(history_pairs(history)[-4:]):
        if role != "assistant":
            continue
        return msg.lower().startswith(prefix.lower())
    return False


def match_material_bundle(text: str, history=None) -> list[dict]:
    """Несколько PDF за один запрос (например, все партнёрские программы)."""
    materials = load_materials()
    if not materials:
        return []

    # Не дублировать PDF, если партнёрские программы только что отправлены
    if history and is_vague_followup(text) and _recent_assistant_tag(history, "[материалы:"):
        return []

    if _looks_like_partner_programs_request(text):
        query = text
    elif is_vague_followup(text) and history:
        combined = combine_with_context(text, history)
        if combined == text or not _looks_like_partner_programs_request(combined):
            return []
        query = combined
    else:
        return []

    bundle = _partner_program_items(materials)
    if len(bundle) >= 2:
        return bundle

    single = match_material(query, history=history)
    return [single] if single else []


def format_video_reply(item: dict) -> str:
    lines = [f"🎬 {item['title']}"]
    if item.get("text"):
        lines.append("")
        lines.append(item["text"])
    links = item.get("video_links") or []
    if links:
        lines.append("")
        for link in links:
            lines.append(f"▶ {link.get('label', 'Смотреть')}: {link['url']}")
    elif item.get("note"):
        lines.append("")
        lines.append(item["note"])
    return "\n".join(lines)


def format_text_reply(item: dict) -> str:
    body = item.get("text") or item.get("title", "")
    prefix = "ℹ️" if item.get("type") == "info" else "ℹ️"
    text = f"{prefix} {item.get('title', 'Информация')}\n\n{body}"
    url = (item.get("url") or "").strip()
    if url and url not in text:
        text += f"\n\nСсылка: {url}"
    return text


def format_material_reply(item: dict) -> str:
    if item.get("type") == "video":
        text = format_video_reply(item)
    elif item.get("type") in ("text", "info"):
        text = format_text_reply(item)
    elif item.get("type") == "link":
        title = item.get("title") or "Ссылка"
        url = (item.get("url") or "").strip()
        text = f"🔗 {title}\n\n{url}" if url else f"🔗 {title}"
    else:
        text = item.get("text") or item.get("title", "")
    return apply_brand_terms(text)


def material_file_path(item: dict) -> Path | None:
    fname = item.get("file")
    if not fname:
        return None
    path = FILES_DIR / fname
    return path if path.is_file() else None


def material_clarify_message() -> str:
    return (
        "Уточните, какая инструкция нужна:\n"
        "• регистрация Forex4you / RoboForex\n"
        "• пополнение счёта\n"
        "• VPS / GOVPSFX (регистрация сервера и вход)\n"
        "• MoniTrading (мониторинг советника)\n"
        "• маркетинг-план / партнёрские программы (PDF)\n"
        "• сушка советников\n"
        "• презентации / PDF\n\n"
        "Или откройте 📦 Материалы в меню бота."
    )
