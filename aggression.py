import re

# ── Прямые запросы оператора ───────────────────────────────
OPERATOR_REQUESTS = [
    "оператор", "оператора", "живой человек", "менеджер",
    "человек", "поддержк", "specialist", "human", "позовите",
]

# ── Маркеры агрессии / негатива ────────────────────────────
AGGRESSION_PATTERNS = [
    r"развод", r"мошенник", r"кидал", r"обман", r"кида[ню]",
    r"верните деньги", r"где мои деньги", r"скам", r"\bлох",
    r"идиот", r"туп(ой|ые|ица|ое)", r"бесполезн", r"отвратительн",
    r"\bужас", r"достал", r"в суд", r"полици", r"жулик", r"ворьё",
    r"наеб", r"кинул", r"разворов",
]

# ── Корни ненормативной лексики (ловят большинство форм) ───
PROFANITY_ROOTS = [
    "бля", "блят", "сук", "хуй", "хуе", "хуё", "хер", "пизд",
    "ебан", "ебат", "ёбан", "ебал", "наху", "похуй", "нахер",
    "пidor", "пидор", "пидар", "гандон", "гондон", "мудак", "мудил",
    "долбоёб", "долбоеб", "дебил", "урод", "ублюд", "тварь",
    "сволоч", "падл", "гнид", "чмо", "залуп", "манда",
    "ебуч", "выеб", "заеб", "уеб", "проеб",
]


def _normalize(text: str) -> str:
    """Приводим текст к виду, в котором сложно спрятать мат."""
    t = text.lower()
    replace = {
        "@": "а", "0": "о", "3": "е", "1": "и", "4": "ч",
        "y": "у", "x": "х", "e": "е", "a": "а", "o": "о",
        "*": "", ".": "", ",": "", "-": "", "_": "", " ": "",
    }
    for k, v in replace.items():
        t = t.replace(k, v)
    return t


def has_profanity(text: str) -> bool:
    """Проверка на мат с учётом простых способов обхода."""
    norm = _normalize(text)
    return any(root in norm for root in PROFANITY_ROOTS)


def is_legitimacy_doubt(text: str) -> bool:
    """Сомнение «мошенники / скам?» — не эскалация, а ответ о компании."""
    if not text or has_profanity(text):
        return False
    t = text.lower()
    if any(
        x in t
        for x in (
            "верните деньги", "где мои деньги", "в суд", "полици",
            "украли", "списали",
        )
    ):
        return False
    return bool(
        re.search(
            r"мошен|скам|развод|кидал|обман|жулик|ворь|"
            r"можно\s+доверять|это\s+развод|не\s+развод|кидалов",
            t,
        )
    )


def needs_operator(text: str) -> bool:
    """True — если нужно передать диалог оператору."""
    if not text:
        return False
    t = text.lower()

    # Сомнение в легитимности — отвечаем сами (priority), не эскалируем
    if is_legitimacy_doubt(text):
        return False

    if any(word in t for word in OPERATOR_REQUESTS):
        return True

    if has_profanity(text):
        return True

    if any(re.search(p, t) for p in AGGRESSION_PATTERNS):
        return True

    letters = [c for c in text if c.isalpha()]
    if len(letters) > 12:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.6:
            return True

    if text.count("!") >= 3 or "???" in text:
        return True

    return False
