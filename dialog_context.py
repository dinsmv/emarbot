"""Умное склеивание текущего сообщения с контекстом диалога."""
from __future__ import annotations

import re
import unicodedata

# Транслит и синонимы: форекс ↔ forex, робофорекс ↔ roboforex
_ALIAS_EXPANSIONS: tuple[tuple[str, str], ...] = (
    ("форекс4you", "forex4you"),
    ("форекс4", "forex4"),
    ("форекс", "forex"),
    ("робофорекс", "roboforex"),
    ("робо форекс", "roboforex"),
    ("фхмонитор", "fxmonitor"),
    ("монитрейдинг", "monitrading"),
    ("впс", "vps"),
    ("емар", "emar"),
)

# Темы для определения смены предмета разговора
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "partner": ("партнер", "партнёр", "реферал", "affiliate"),
    "fxmonitor": ("fxmonitor", "fx monitor", "фхмонитор", "monitrading", "монитрейдинг"),
    "forex4you": ("forex4you", "форекс4you", "forex4", "форекс4", "forex", "форекс"),
    "roboforex": ("roboforex", "робофорекс", "робо форекс", "робо"),
    "marketing": ("маркетинг", "маркетнг", "маркет план"),
    "template": ("шаблон", "заявк"),
    "registration": ("регист", "зарегист", "регать"),
    "deposit": ("пополн", "депозит"),
    "vps": ("vps", "впс", "govps"),
    "monitoring": ("мониторинг", "myfxbook", "trinity", "king"),
    "cardex": ("cardex", "кардекс", "обменник"),
    "presentation": ("презент", "king", "trinity"),
    "drying": ("сушк", "сушку"),
    "drawdown": ("просадк", "долив", "подушк", "drawdown"),
    "advisor": (
        "советник", "aggressive", "агрессив", "medium", "медиум", "conservative",
        "консерватив", "classic", "классик", "king", "кинг", "trinity", "тринити",
        "параметр", "техническ",
    ),
}

# Линейка / профиль риска — для follow-up «у него / какие параметры»
_LINE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\btrinity\b|\bтринити\b", "Trinity"),
    (r"\bking\b|\bкинг\b", "King"),
    (r"\bclassic\b|\bклассик\b", "Classic"),
)
_PROFILE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\btrinity\s*x\b|\bтринити\s*x\b", "X"),
    (r"\baggressive\b|\bагрессив\w*", "Aggressive"),
    (r"\bconservative\b|\bконсерватив\w*", "Conservative"),
    (r"\bmedium\b|\bмедиум\b|\bсредний\b", "Medium"),
)

_PRONOUN_FOLLOWUP = re.compile(
    r"(?:"
    r"\bу\s+нег[оа]\b|\bнег[оа]\b|\bнего\b|\bеё\b|\bее\b|\bего\b|"
    r"\bэтого\b|\bэтой\b|\bэтот\b|\bэта\b|\bэти\b|"
    r"\bтакого\b|\bтакой\b|\bтакая\b|\bтакое\b|"
    r"\bпараметр|\bхарактеристик|\bнастройк|\bдепозит|\bлот|"
    r"\bпары\b|\bвалютн|\bсколько\s+стоит|\bдоход|\bриск"
    r")",
    re.I,
)

# Разговорный сленг / опечатки / чат-формы → нормальная форма
# Сначала длинные фразы, потом короткие слова (порядок важен).
_SLANG_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # «что такое / что делать»
    (r"(?<!\w)(?:че|шо|што|чо)\s+такое(?!\w)", "что такое"),
    (r"(?<!\w)(?:че|шо|што|чо)\s+за(?!\w)", "что за"),
    (r"(?<!\w)(?:че|шо)\s+делать(?!\w)", "что делать"),
    (r"(?<!\w)(?:че|шо)\s+делат[ьи]?(?!\w)", "что делать"),
    (r"(?<!\w)как\s+сделать\s+долив(?!\w)", "как сделать долив"),
    (r"(?<!\w)как\s+долить(?!\w)", "как сделать долив"),
    (r"(?<!\w)че\s+за\s+долив(?!\w)", "что такое долив"),
    (r"(?<!\w)че\s+такое\s+долив(?!\w)", "что такое долив"),
    (r"(?<!\w)видосик(?!\w)", "видео"),
    (r"(?<!\w)видос(?!\w)", "видео"),
    (r"(?<!\w)ролик(?!\w)", "видео"),
    # просадка / долив / сушка (фразы)
    (r"(?<!\w)просел[оаи]?\s+сильно(?!\w)", "большая просадка"),
    (r"(?<!\w)уш[её]л\s+в\s+минус(?!\w)", "просадка"),
    (r"(?<!\w)в\s+минусе(?!\w)", "просадка"),
    (r"(?<!\w)минусанул[оаи]?(?!\w)", "просадка"),
    (r"(?<!\w)залить\s+подушку(?!\w)", "сделать долив"),
    (r"(?<!\w)кинуть\s+подушку(?!\w)", "сделать долив"),
    (r"(?<!\w)подушка\s+безопасности(?!\w)", "долив"),
    (r"(?<!\w)на\s+сушку(?!\w)", "в режим сушки"),
    (r"(?<!\w)засушить(?!\w)", "включить сушку"),
    (r"(?<!\w)пополнить\s+деп(?!\w)", "пополнить депозит"),
    (r"(?<!\w)закинуть\s+(?:на\s+)?(?:сч[её]т|деп(?:озит)?)(?!\w)", "пополнить счёт"),
    (r"(?<!\w)залить\s+(?:на\s+)?(?:сч[её]т|деп(?:озит)?)(?!\w)", "пополнить счёт"),
    (r"(?<!\w)вывести\s+бабки(?!\w)", "вывести деньги"),
    (r"(?<!\w)снять\s+бабки(?!\w)", "вывести деньги"),
    (r"(?<!\w)не\s+робит(?!\w)", "не работает"),
    (r"(?<!\w)не\s+пашет(?!\w)", "не работает"),
    (r"(?<!\w)не\s+крутит(?!\w)", "не работает"),
    (r"(?<!\w)зайти\s+на\s+впс(?!\w)", "войти на vps"),
    (r"(?<!\w)fx\s*monitor(?!\w)", "monitrading"),
    (r"(?<!\w)патаму\s*что(?!\w)", "потому что"),
    (r"(?<!\w)птму\s*что(?!\w)", "потому что"),
    # вопросы / частицы
    (r"(?<!\w)чето(?!\w)", "что-то"),
    (r"ьэто", "это"),
    (r"(?<!\w)ето(?!\w)", "это"),
    (r"(?<!\w)ниче(?!\w)", "ничего"),
    (r"(?<!\w)нече(?!\w)", "нечего"),
    (r"(?<!\w)че(?!\w)", "что"),
    (r"(?<!\w)шо(?!\w)", "что"),
    (r"(?<!\w)што(?!\w)", "что"),
    (r"(?<!\w)чо(?!\w)", "что"),
    (r"(?<!\w)скока(?!\w)", "сколько"),
    (r"(?<!\w)скок(?!\w)", "сколько"),
    (r"(?<!\w)када(?!\w)", "когда"),
    (r"(?<!\w)куды(?!\w)", "куда"),
    (r"(?<!\w)откель(?!\w)", "откуда"),
    (r"(?<!\w)почем(?!\w)", "почему"),
    (r"(?<!\w)поч(?!\w)", "почему"),
    (r"(?<!\w)зачем(?!\w)", "зачем"),
    (r"(?<!\w)нада(?!\w)", "надо"),
    (r"(?<!\w)мож(?!\w)", "можно"),
    # время / усилители
    (r"(?<!\w)щас(?!\w)", "сейчас"),
    (r"(?<!\w)ща(?!\w)", "сейчас"),
    (r"(?<!\w)сеча(?!\w)", "сейчас"),
    (r"(?<!\w)сейча(?!\w)", "сейчас"),
    (r"(?<!\w)прям(?!\w)", "прямо"),
    (r"(?<!\w)оч(?!\w)", "очень"),
    (r"(?<!\w)ваще(?!\w)", "вообще"),
    (r"(?<!\w)вобще(?!\w)", "вообще"),
    (r"(?<!\w)вообщем(?!\w)", "в общем"),
    (r"(?<!\w)крч(?!\w)", "короче"),
    (r"(?<!\w)короч(?!\w)", "короче"),
    (r"(?<!\w)типо(?!\w)", "типа"),
    (r"(?<!\w)тока(?!\w)", "только"),
    (r"(?<!\w)токо(?!\w)", "только"),
    (r"(?<!\w)ток(?!\w)", "только"),
    (r"(?<!\w)мб(?!\w)", "может быть"),
    (r"(?<!\w)хз(?!\w)", "не знаю"),
    (r"(?<!\w)нзч(?!\w)", "не за что"),
    (r"(?<!\w)имхо(?!\w)", "по моему мнению"),
    (r"(?<!\w)тк(?!\w)", "потому что"),
    # вежливость
    (r"(?<!\w)пжлста(?!\w)", "пожалуйста"),
    (r"(?<!\w)пжлст[а]?(?!\w)", "пожалуйста"),
    (r"(?<!\w)пжалст[а]?(?!\w)", "пожалуйста"),
    (r"(?<!\w)плиз(?!\w)", "пожалуйста"),
    (r"(?<!\w)плз(?!\w)", "пожалуйста"),
    (r"(?<!\w)пж(?!\w)", "пожалуйста"),
    (r"(?<!\w)пасиба(?!\w)", "спасибо"),
    (r"(?<!\w)пасиб(?!\w)", "спасибо"),
    (r"(?<!\w)спс(?!\w)", "спасибо"),
    (r"(?<!\w)сяб(?!\w)", "спасибо"),
    # приветствия
    (r"(?<!\w)прив(?!\w)", "привет"),
    (r"(?<!\w)здрасте(?!\w)", "здравствуйте"),
    (r"(?<!\w)здарова(?!\w)", "здравствуйте"),
    (r"(?<!\w)здаров(?!\w)", "здравствуйте"),
    (r"(?<!\w)хай(?!\w)", "привет"),
    (r"(?<!\w)хеллоу(?!\w)", "привет"),
    (r"(?<!\w)хелло(?!\w)", "привет"),
    # действия в чате
    (r"(?<!\w)скиньте(?!\w)", "пришлите"),
    (r"(?<!\w)скинь(?!\w)", "пришлите"),
    (r"(?<!\w)киньте(?!\w)", "пришлите"),
    (r"(?<!\w)кинь(?!\w)", "пришлите"),
    (r"(?<!\w)закиньте(?!\w)", "пришлите"),
    (r"(?<!\w)закинь(?!\w)", "пришлите"),
    (r"(?<!\w)гляньте(?!\w)", "посмотрите"),
    (r"(?<!\w)глянь(?!\w)", "посмотрите"),
    (r"(?<!\w)поясните(?!\w)", "объясните"),
    (r"(?<!\w)поясни(?!\w)", "объясните"),
    (r"(?<!\w)разжуйте(?!\w)", "объясните подробнее"),
    (r"(?<!\w)разжуй(?!\w)", "объясните подробнее"),
    (r"(?<!\w)подскажи(?!\w)", "подскажите"),
    (r"(?<!\w)скажи(?!\w)", "скажите"),
    # «не работает»
    (r"(?<!\w)отвалил(?:ось|ся)?(?!\w)", "не работает"),
    (r"(?<!\w)завис(?:ло|ла)?(?!\w)", "зависло"),
    (r"(?<!\w)глючит(?!\w)", "не работает"),
    (r"(?<!\w)багает(?!\w)", "не работает"),
    (r"(?<!\w)забагалось(?!\w)", "не работает"),
    (r"(?<!\w)тупит(?!\w)", "не работает"),
    (r"(?<!\w)робит(?!\w)", "работает"),
    (r"(?<!\w)пашет(?!\w)", "работает"),
    # деньги / депозит
    (r"(?<!\w)бабосики(?!\w)", "деньги"),
    (r"(?<!\w)бабосы(?!\w)", "деньги"),
    (r"(?<!\w)бабло(?!\w)", "деньги"),
    (r"(?<!\w)бабки(?!\w)", "деньги"),
    (r"(?<!\w)капуста(?!\w)", "деньги"),
    (r"(?<!\w)лаве(?!\w)", "деньги"),
    (r"(?<!\w)депик(?!\w)", "депозит"),
    (r"(?<!\w)депа(?!\w)", "депозит"),
    (r"(?<!\w)деп(?!\w)", "депозит"),
    (r"(?<!\w)пополняшка(?!\w)", "пополнение"),
    # просадка / долив / сушка (слова)
    (r"(?<!\w)просел[оаи]?(?!\w)", "просадка"),
    (r"(?<!\w)процент[оа]в?(?!\w)", "процентов"),
    (r"(?<!\w)проц(?!\w)", "процентов"),
    (r"(?<!\w)долить(?!\w)", "долив"),
    (r"(?<!\w)подушк[ауеи]?(?!\w)", "долив"),
    (r"долив\s+долив", "долив"),
    (r"(?<!\w)сушить(?!\w)", "сушка"),
    # регистрация / брокеры / VPS / мониторинг
    (r"(?<!\w)зарегац+а(?!\w)", "зарегистрироваться"),
    (r"(?<!\w)зарегаться(?!\w)", "зарегистрироваться"),
    (r"(?<!\w)зарегать(?!\w)", "зарегистрировать"),
    (r"(?<!\w)регаться(?!\w)", "зарегистрироваться"),
    (r"(?<!\w)регать(?!\w)", "зарегистрировать"),
    (r"(?<!\w)рега(?!\w)", "регистрация"),
    (r"(?<!\w)сервачок(?!\w)", "сервер"),
    (r"(?<!\w)сервак(?!\w)", "сервер"),
    (r"(?<!\w)впска(?!\w)", "vps"),
    (r"(?<!\w)впску(?!\w)", "vps"),
    (r"(?<!\w)впс(?!\w)", "vps"),
    (r"(?<!\w)говпс(?!\w)", "govpsfx"),
    (r"(?<!\w)govps(?!\w)", "govpsfx"),
    (r"(?<!\w)фхмонитор(?!\w)", "monitrading"),
    (r"(?<!\w)fxmonitor(?!\w)", "monitrading"),
    (r"(?<!\w)монитрейдинг(?!\w)", "monitrading"),
    (r"(?<!\w)форекс4(?!\w)", "forex4you"),
    (r"(?<!\w)ф4у(?!\w)", "forex4you"),
    (r"(?<!\w)форех(?!\w)", "forex"),
    (r"(?<!\w)форик(?!\w)", "forex"),
    (r"(?<!\w)роба(?!\w)", "roboforex"),
    (r"(?<!\w)брок(?!\w)", "брокер"),
    (r"(?<!\w)кинг(?!\w)", "king"),
    (r"(?<!\w)тринити(?!\w)", "trinity"),
    (r"(?<!\w)классик(?!\w)", "classic"),
    (r"(?<!\w)автоторг(?:овля)?(?!\w)", "автоторговля"),
    (r"(?<!\w)автотрейд(?:инг)?(?!\w)", "автоторговля"),
    (r"(?<!\w)маржин\s*колл(?!\w)", "маржин колл"),
    (r"(?<!\w)маржинколл(?!\w)", "маржин колл"),
    (r"(?<!\w)стоп\s*лосс(?!\w)", "stop loss"),
    (r"(?<!\w)стоплосс(?!\w)", "stop loss"),
    # эмоции (мягкая нормализация)
    (r"(?<!\w)ппц(?!\w)", "плохо"),
    (r"(?<!\w)пипец(?!\w)", "плохо"),
    (r"(?<!\w)капец(?!\w)", "плохо"),
    (r"(?<!\w)жесть(?!\w)", "плохо"),
    (r"(?<!\w)фигня(?!\w)", "проблема"),
    (r"(?<!\w)хрень(?!\w)", "проблема"),
    (r"(?<!\w)норм(?!\w)", "нормально"),
    (r"(?<!\w)окей(?!\w)", "хорошо"),
)


def normalize_user_question(text: str) -> str:
    """Нормализует сленг («че»→«что»), чтобы матчинг и ИИ понимали вопрос."""
    t = (text or "").strip()
    if not t:
        return t
    low = t.lower().replace("ё", "е")
    low = re.sub(r"([а-яa-z])\1{2,}", r"\1\1", low)
    for pattern, repl in _SLANG_REPLACEMENTS:
        pat = pattern.replace("ё", "е")
        try:
            low = re.sub(pat, repl, low, flags=re.IGNORECASE)
        except re.error:
            continue
    low = re.sub(r"\s+", " ", low).strip()
    # убрать дубли после замен: «долив долив», «видео видео»
    low = re.sub(r"\b(\w+)(?:\s+\1)+\b", r"\1", low)
    if t[:1].isupper() and low:
        return low[0].upper() + low[1:]
    return low

# Уточнения без своей темы — можно склеивать с предыдущим вопросом
_AUXILIARY_TOPICS = frozenset({"video", "file", "clarify"})

_AUXILIARY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "video": ("видео", "обзор", "ролик", "youtube", "rutube"),
    "file": ("pdf", "пдф", "файл", "документ", "скинь", "скиньте", "пришли", "пришлите"),
    "clarify": ("не шаблон", "не текст", "именно", "уточн", "подробнее"),
}

_VAGUE_FOLLOWUPS = (
    "мне нужно видео", "нужно видео", "мне нужен видео", "нужен видео",
    "дай видео", "дайте видео", "именно видео", "не шаблон", "не нужен шаблон",
    "а видео", "не текст", "скинь", "скиньте", "пришли", "пришлите",
    "отправь", "отправьте",
)

_CLARIFY_MARKERS = (
    "уточните", "какой шаблон", "какая инструкция", "раздел «шаблоны»",
    "какой материал", "что именно", "какая инструкция нужна",
)

_DELIVERED_MARKERS = ("[шаблон:", "[материал:", "[материалы:")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return expand_aliases(s)


def expand_aliases(text: str) -> str:
    """Сленг + пары форекс/forex, чтобы матчинг понимал оба написания."""
    t = normalize_user_question(text or "")
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    extras: list[str] = []
    for left, right in _ALIAS_EXPANSIONS:
        if left in t:
            extras.append(right)
        elif right in t:
            extras.append(left)
    if extras:
        t = f"{t} {' '.join(extras)}"
    return t


def history_pairs(history) -> list[tuple[str, str]]:
    if not history:
        return []
    out: list[tuple[str, str]] = []
    for entry in history:
        if isinstance(entry, dict):
            out.append((entry.get("role", ""), entry.get("text", "")))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            out.append((entry[0], entry[1]))
    return out


def extract_topics(text: str) -> set[str]:
    t = _norm(text)
    topics: set[str] = set()
    for name, keywords in _TOPIC_KEYWORDS.items():
        if any(k in t for k in keywords):
            topics.add(name)
    for name, keywords in _AUXILIARY_KEYWORDS.items():
        if any(k in t for k in keywords):
            topics.add(name)
    return topics


def substantive_topics(text: str) -> set[str]:
    return extract_topics(text) - _AUXILIARY_TOPICS


def topics_conflict(current: str, previous: str) -> bool:
    """True, если новое сообщение явно про другую тему."""
    cur = substantive_topics(current)
    prev = substantive_topics(previous)
    if not cur or not prev:
        return False
    if cur & prev:
        return False
    return True


def is_vague_followup(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    if is_pronoun_followup(text):
        return True
    if len(t) > 55:
        return False
    if any(v in t for v in _VAGUE_FOLLOWUPS):
        return True
    if len(t) < 22 and not substantive_topics(text):
        return True
    return False


def bot_awaiting_clarification(history) -> bool:
    for role, msg in reversed(history_pairs(history)[-6:]):
        if role != "assistant":
            continue
        low = msg.lower()
        if any(m in low for m in _CLARIFY_MARKERS):
            return True
        if low.startswith("[шаблон:") or low.startswith("[материал"):
            return False
    return False


def _last_user_messages(history, limit: int = 4) -> list[str]:
    msgs: list[str] = []
    for role, text in reversed(history_pairs(history)):
        if role != "user":
            continue
        t = text.strip()
        if t:
            msgs.append(t)
        if len(msgs) >= limit:
            break
    return msgs


def _find_topic_anchor(pairs: list[tuple[str, str]], current_text: str) -> str | None:
    """Ищет в истории вопрос с темой, близкой к текущему уточнению."""
    current_substantive = substantive_topics(current_text)
    best: str | None = None
    best_score = 0

    for role, msg in reversed(pairs):
        if role != "user":
            continue
        anchor = msg.strip()
        if not anchor or _norm(anchor) == _norm(current_text):
            continue
        if is_vague_followup(anchor) and not substantive_topics(anchor):
            continue
        anchor_topics = substantive_topics(anchor)
        if not anchor_topics:
            continue
        score = len(current_substantive & anchor_topics)
        if current_substantive and not score:
            score = 1 if any(k in _norm(anchor) for k in _norm(current_text).split()) else 0
        if score > best_score:
            best_score = score
            best = anchor

    if best:
        return best
    return None


def find_context_anchor(history, current_text: str) -> str | None:
    """Находит пользовательское сообщение, к которому относится уточнение."""
    if not history:
        return None

    pairs = history_pairs(history)[-10:]
    user_msgs = [msg for role, msg in pairs if role == "user" and msg.strip()]

    if not user_msgs:
        return None

    # Ответ на уточнение «какая инструкция нужна» — ищем тему в истории
    if bot_awaiting_clarification(history) and not is_vague_followup(current_text):
        anchor = _find_topic_anchor(pairs, current_text)
        if anchor:
            return anchor

    current_substantive = substantive_topics(current_text)

    # Явная новая тема — не цепляемся к старому вопросу
    if current_substantive and not is_vague_followup(current_text):
        if topics_conflict(current_text, user_msgs[-1]):
            return None
        return current_text

    # Уточнение после ответа бота: берём последний вопрос пользователя
    if is_vague_followup(current_text) or bot_awaiting_clarification(history):
        for role, msg in reversed(pairs):
            if role != "user":
                continue
            anchor = msg.strip()
            if not anchor:
                continue
            if topics_conflict(current_text, anchor) and substantive_topics(current_text):
                continue
            return anchor

    # Короткое «а как…», «не понял» — к предыдущему сообщению, если тема не сменилась
    if len(_norm(current_text)) < 60:
        prev = user_msgs[-1]
        if not topics_conflict(current_text, prev):
            return prev

    return None


def extract_advisor_entity(text: str) -> str | None:
    """Достаёт продукт вида «EMAR Classic Aggressive» из текста."""
    if not text:
        return None
    t = text.lower().replace("ё", "е")
    line = None
    profile = None
    for pat, name in _LINE_PATTERNS:
        if re.search(pat, t, re.I):
            line = name
            break
    for pat, name in _PROFILE_PATTERNS:
        if re.search(pat, t, re.I):
            profile = name
            break
    if line and profile:
        return f"EMAR {line} {profile}"
    if profile and not line:
        # «Aggressive» без линейки — оставляем профиль, линейку доберём из истории
        return profile
    if line and not profile:
        return f"EMAR {line}"
    return None


def last_advisor_entity(history) -> str | None:
    """Последний упомянутый советник в переписке (сначала у пользователя, потом у бота)."""
    pairs = history_pairs(history)
    # Сначала ищем у пользователя (явный выбор темы)
    for role, msg in reversed(pairs):
        if role != "user":
            continue
        ent = extract_advisor_entity(msg)
        if ent:
            return ent
    # Затем у бота (если клиент сказал только «Aggressive»)
    for role, msg in reversed(pairs):
        if role != "assistant":
            continue
        ent = extract_advisor_entity(msg)
        if ent:
            return ent
    return None


def merge_advisor_entity(partial: str | None, from_history: str | None) -> str | None:
    """Склеивает «Aggressive» + «EMAR Classic …» из истории → полный продукт."""
    if not partial and not from_history:
        return None
    if partial and ("Classic" in partial or "King" in partial or "Trinity" in partial):
        if any(p in partial for p in ("Aggressive", "Medium", "Conservative", " X")):
            return partial if partial.startswith("EMAR") else f"EMAR {partial}"
    hist = from_history or ""
    part = partial or ""
    # профиль из текущего, линейка из истории
    profile = None
    line = None
    for p in ("Aggressive", "Medium", "Conservative", "X"):
        if p in part or p in hist:
            if p in part:
                profile = p
                break
            if not profile:
                profile = p
    for ln in ("Classic", "King", "Trinity"):
        if ln in part:
            line = ln
            break
        if ln in hist and not line:
            line = ln
    if line and profile:
        return f"EMAR {line} {profile}"
    if part.startswith("EMAR"):
        return part
    if hist.startswith("EMAR") and profile and profile in hist:
        # заменяем профиль в hist
        for p in ("Aggressive", "Medium", "Conservative"):
            hist = hist.replace(p, profile)
        return hist
    if profile:
        return f"EMAR {profile}" if not line else f"EMAR {line} {profile}"
    return hist or (f"EMAR {part}" if part else None)


def is_pronoun_followup(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if extract_advisor_entity(t):
        # в вопросе уже назван продукт — не follow-up по местоимению
        if _PRONOUN_FOLLOWUP.search(t) and len(t) < 80:
            return True
        return False
    return bool(_PRONOUN_FOLLOWUP.search(t))


def resolve_advisor_followup(text: str, history) -> str | None:
    """
    Если вопрос — уточнение («какие у него параметры»), возвращает явный запрос
    с названием советника из истории. Иначе None.
    """
    if not history or not text.strip():
        return None
    if not (is_pronoun_followup(text) or is_vague_followup(text) or _looks_like_param_followup(text)):
        return None

    current_ent = extract_advisor_entity(text)
    hist_ent = last_advisor_entity(history)
    entity = merge_advisor_entity(current_ent, hist_ent)
    if not entity:
        return None

    # убрать местоимения, оставить суть вопроса
    cleaned = text.strip()
    cleaned = re.sub(r"\bу\s+нег[оа]\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\bнег[оа]\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\bего\b|\bеё\b|\bее\b|\bэтого\b|\bэтой\b|\bэтот\b|\bэта\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?!.")
    if not cleaned:
        return f"технические параметры советника {entity}"
    if re.search(r"параметр|характеристик|техн", cleaned, re.I):
        return f"технические параметры советника {entity}"
    return f"{cleaned} советник {entity}"


def _looks_like_param_followup(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(r"параметр|характеристик|настройк|техн|депозит|лот|пар[аы]|доход|риск", t)
        and len(t) < 90
        and not extract_advisor_entity(t)
    )


def combine_with_context(text: str, history) -> str:
    """
    Склеивает текущий вопрос с контекстом, если это уточнение.
    Не склеивает, если пользователь явно сменил тему.
    """
    if not history or not text.strip():
        return text

    # Приоритет: follow-up про советника («у него параметры» → Aggressive)
    resolved = resolve_advisor_followup(text, history)
    if resolved:
        return resolved

    anchor = find_context_anchor(history, text)
    if not anchor:
        return text

    if _norm(anchor) == _norm(text):
        return text

    combined = f"{anchor} {text}".strip()
    # Смена темы в склеенном запросе — оставляем только текущий вопрос
    if substantive_topics(text) and topics_conflict(text, anchor):
        return text

    # Если в якоре есть советник, а в вопросе местоимение — усиливаем
    ent = extract_advisor_entity(anchor) or last_advisor_entity(history)
    if ent and is_pronoun_followup(text):
        return f"{ent}: {text}"

    return combined


def is_explicit_request(text: str, predicate) -> bool:
    """Проверка явного запроса по текущему сообщению (без склеивания)."""
    return predicate(text)
