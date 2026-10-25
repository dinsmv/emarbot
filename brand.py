"""Брендинг и единые формулировки для бота и каталога."""
from __future__ import annotations

import re

MONITRADING = "MoniTrading"
MONITRADING_FULL = (
    "MoniTrading — сервис мониторинга за торговым советником"
)

HISTORICAL_YIELD = (
    "По историческим данным за прошлые годы торговые советники EMAR Capital "
    "в среднем приносили клиентам порядка 5–7% в месяц. "
    "На текущий год можно ориентироваться на схожие показатели, "
    "но конкретный результат зависит от рынка, настроек и соблюдения рекомендаций."
)

_UNCERTAIN_PATTERNS = (
    re.compile(r"\bвероятно\b", re.IGNORECASE),
    re.compile(r"\bвозможно\b", re.IGNORECASE),
    re.compile(r"\bскорее всего\b", re.IGNORECASE),
    re.compile(r"\bскорей всего\b", re.IGNORECASE),
    re.compile(r"\bимеется в виду\b", re.IGNORECASE),
    re.compile(r"\bпохоже\b", re.IGNORECASE),
)

_DISPLAY_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"FX\s*MONITOR", re.IGNORECASE), MONITRADING),
    (re.compile(r"FX\s*monitor", re.IGNORECASE), MONITRADING),
    (re.compile(r"FxMonitor", re.IGNORECASE), MONITRADING),
    (re.compile(r"FXmonitor", re.IGNORECASE), MONITRADING),
    (re.compile(r"фх\s*монитор", re.IGNORECASE), MONITRADING),
    (re.compile(r"FX\s*Monitor", re.IGNORECASE), MONITRADING),
    (re.compile(r"Fx\s*Monitor", re.IGNORECASE), MONITRADING),
    (re.compile(r"ключ\s+fx\s*monitor", re.IGNORECASE), f"ключ {MONITRADING}"),
    (re.compile(r"ключ\s+Fx\s*Monitor", re.IGNORECASE), f"ключ {MONITRADING}"),
    (re.compile(r"@emarcapitalsupport", re.IGNORECASE), "@Emarcapitalbot"),
    (re.compile(r"t\.me/emarcapitalsupport", re.IGNORECASE), "t.me/Emarcapitalbot"),
    (re.compile(r"https?://t\.me/cdx_pay\b", re.IGNORECASE), "https://t.me/m/c7IG774aN2My"),
    (re.compile(r"t\.me/cdx_pay\b", re.IGNORECASE), "t.me/m/c7IG774aN2My"),
    (re.compile(r"@cdx_pay\b", re.IGNORECASE), "https://t.me/m/c7IG774aN2My"),
)


def apply_brand_terms(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, repl in _DISPLAY_REPLACEMENTS:
        out = pattern.sub(repl, out)
    return out


def make_confident(text: str) -> str:
    """Убирает неуверенные формулировки из ответа бота."""
    if not text:
        return text
    out = text
    for pattern in _UNCERTAIN_PATTERNS:
        out = pattern.sub("", out)
    # Только пробелы/табы — не трогаем переносы строк (иначе список «сплющивается»)
    out = re.sub(r"[^\S\n]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[^\S\n]+,", ",", out)
    out = re.sub(r"\(\s*\)", "", out)
    return out.strip()
