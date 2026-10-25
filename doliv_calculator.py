"""Калькулятор долива / плана по просадке — по схеме EMAR Capital (Notion)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class AccountState:
    name: str
    balance: float
    drawdown_pct: float  # абсолютное значение, 40 = -40%


_ADVISOR_ALIASES: tuple[tuple[str, str], ...] = (
    (r"trinity\s*x|тринити\s*x", "Trinity X"),
    (r"trinity|тринити", "Trinity"),
    (r"classic|классик", "Classic"),
    (r"king|кинг", "King"),
)

_CALC_HINTS = (
    "посчитай", "рассчитай", "калькулятор", "сколько долив", "какой долив",
    "моя ситуация", "у меня на счет", "у меня на счёт", "на счетах",
)

DOLIV_CALC_PROMPT = (
    "🧮 <b>Расчёт долива</b> — по схеме академии EMAR Capital "
    "(критическая ситуация / MoniTrading).\n\n"
    "Пришлите цифры с ваших счетов, например:\n\n"
    "<code>Classic: депозит 1000$, просадка 0.25%\n"
    "King: депозит 1000$, просадка 0.1%\n"
    "Trinity: депозит 1000$, просадка 40%</code>\n\n"
    "Или для одного счёта:\n"
    "<code>на счёте 1000$ просадка 40%</code>\n\n"
    "Я посчитаю: нужна ли сушка/долив, сумму долива (100% депозита), "
    "ориентир просадки после пополнения и — если счетов несколько — "
    "план перевода 90% с самого спокойного на просевший (как в примере академии)."
)


def _norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = t.replace(",", ".")
    return re.sub(r"\s+", " ", t).strip()


def looks_like_calc_request(text: str) -> bool:
    """Есть цифры просадки/депозита — можно считать план."""
    t = _norm(text)
    has_pct = bool(re.search(r"\d+(?:\.\d+)?\s*%", t) or re.search(r"просадк\w*\s*-?\d+", t))
    has_money = bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:\$|usd|доллар|депозит|баланс)", t)
        or re.search(r"(?:депозит|баланс|счет|счёт)\w*\s*-?\d+", t)
    )
    has_advisor = any(re.search(p, t) for p, _ in _ADVISOR_ALIASES)
    if has_advisor and has_pct and has_money:
        return True
    if has_pct and has_money:
        return True
    if has_advisor and has_pct:
        return True
    return False


def _parse_accounts(text: str) -> list[AccountState]:
    t = _norm(text)
    found: list[AccountState] = []

    # «Classic: 1000$ просадка -0.25%» / «Тринити 1000 -40%»
    for pattern, name in _ADVISOR_ALIASES:
        for m in re.finditer(
            rf"(?:{pattern})\w*[^\d%]{{0,40}}?"
            rf"(?P<bal>\d+(?:\.\d+)?)\s*(?:\$|usd|доллар\w*)?"
            rf"[^\d%]{{0,40}}?"
            rf"(?:просадк\w*\s*)?(?P<dd>-?\d+(?:\.\d+)?)\s*%",
            t,
        ):
            bal = float(m.group("bal"))
            dd = abs(float(m.group("dd")))
            found.append(AccountState(name=name, balance=bal, drawdown_pct=dd))

        # порядок: просадка раньше денег — «Trinity просадка 40% депозит 1000»
        for m in re.finditer(
            rf"(?:{pattern})\w*[^\d%]{{0,40}}?"
            rf"(?:просадк\w*\s*)?(?P<dd>-?\d+(?:\.\d+)?)\s*%"
            rf"[^\d%]{{0,40}}?"
            rf"(?P<bal>\d+(?:\.\d+)?)\s*(?:\$|usd|доллар\w*|депозит\w*|баланс\w*)?",
            t,
        ):
            bal = float(m.group("bal"))
            dd = abs(float(m.group("dd")))
            if not any(a.name == name and a.balance == bal for a in found):
                found.append(AccountState(name=name, balance=bal, drawdown_pct=dd))

    # один счёт: «просадка 35% депозит 500$ classic»
    if len(found) <= 1:
        m = re.search(
            r"(?:просадк\w*\s*)?(?P<dd>-?\d+(?:\.\d+)?)\s*%"
            r".{0,50}?"
            r"(?:депозит|баланс|счет|счёт)\w*[^\d]{0,12}(?P<bal>\d+(?:\.\d+)?)",
            t,
        )
        if not m:
            m = re.search(
                r"(?:депозит|баланс|счет|счёт)\w*[^\d]{0,12}(?P<bal>\d+(?:\.\d+)?)"
                r".{0,50}?"
                r"(?:просадк\w*\s*)?(?P<dd>-?\d+(?:\.\d+)?)\s*%",
                t,
            )
        if m:
            name = "Счёт"
            for pattern, aname in _ADVISOR_ALIASES:
                if re.search(pattern, t):
                    name = aname
                    break
            acc = AccountState(
                name=name,
                balance=float(m.group("bal")),
                drawdown_pct=abs(float(m.group("dd"))),
            )
            if not found:
                found.append(acc)
            elif found[0].name == "Счёт" and name != "Счёт":
                found[0] = acc

    # дедуп по имени — берём последнее упоминание
    by_name: dict[str, AccountState] = {}
    for acc in found:
        by_name[acc.name] = acc
    return list(by_name.values())


def _fmt_money(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))} $"
    return f"{x:.2f} $"


def _fmt_dd(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}%"
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"
def _stage_for_dd(dd: float) -> str:
    if dd < 20:
        return "норма (0–20%) — рабочая зона, менять ничего не нужно"
    if dd < 30:
        return "первые действия (20–30%) — включите сушку и ждите отката"
    if dd < 50:
        return "зона долива (ориентир 30–40%) — после сушки, если растёт, нужен долив 100%"
    return "критический уровень (≥50%) — после долива при повторных 50% отключите Auto Trading и напишите в поддержку"


def _estimate_after_100_doliv(dd: float) -> float:
    """Как в примере Notion: при удвоении баланса процент просадки ≈ снижается вдвое."""
    return dd / 2.0


def build_doliv_plan(text: str) -> str | None:
    """Строит персональный план или подсказку формата."""
    accounts = _parse_accounts(text)
    if not accounts:
        t = _norm(text)
        if "долив" in t or "подушк" in t or any(h in t for h in _CALC_HINTS):
            return (
                "Могу посчитать план долива по вашей ситуации.\n\n"
                "Напишите в таком виде (как в MoniTrading):\n"
                "• Classic: депозит 1000$, просадка 0.25%\n"
                "• King: депозит 1000$, просадка 0.1%\n"
                "• Trinity: депозит 1000$, просадка 40%\n\n"
                "Или для одного счёта: «на счёте 1000$ просадка 40%, что делать?»"
            )
        return None

    lines: list[str] = []
    lines.append("Расчёт по вашей ситуации (схема EMAR Capital / критическая ситуация):\n")
    lines.append("Текущие показатели:")
    for a in sorted(accounts, key=lambda x: -x.drawdown_pct):
        lines.append(
            f"• {a.name}: депозит {_fmt_money(a.balance)}, просадка {_fmt_dd(a.drawdown_pct)} "
            f"— {_stage_for_dd(a.drawdown_pct)}"
        )

    critical = max(accounts, key=lambda a: a.drawdown_pct)
    calm = min(accounts, key=lambda a: a.drawdown_pct)

    # Критический повторный 50%+
    if critical.drawdown_pct >= 50:
        lines.append(
            f"\n⚠️ На {critical.name} просадка {_fmt_dd(critical.drawdown_pct)}. "
            "Если долив 100% уже делали и просадка снова около 50% — "
            "немедленно отключите Auto Trading и напишите @Emarcapitalbot. "
            "Автоторговлю не включайте до консультации."
        )
        if critical.drawdown_pct < 100:
            doliv = critical.balance
            lines.append(
                f"\nЕсли долив ещё не делали: пополните {critical.name} на {_fmt_money(doliv)} "
                f"(100% депозита). Ориентир после долива: просадка ≈ {_fmt_dd(_estimate_after_100_doliv(critical.drawdown_pct))}."
            )
        return "\n".join(lines)

    # Норма / сушка без долива
    if critical.drawdown_pct < 20:
        lines.append(
            "\nВсе счета в рабочей зоне (до 20%). Долив не нужен — продолжайте контроль в MoniTrading."
        )
        return "\n".join(lines)

    if critical.drawdown_pct < 30:
        lines.append(
            f"\nПлан:\n1. На {critical.name} включите режим сушки и дождитесь отката.\n"
            "2. Долив пока не требуется (ориентир долива — просадка 30–40% и рост после сушки).\n"
            "3. Следите за счётом в MoniTrading."
        )
        return "\n".join(lines)

    # 30–50%: долив
    doliv_amount = critical.balance
    new_dd = _estimate_after_100_doliv(critical.drawdown_pct)
    lines.append(
        f"\nОриентир долива для {critical.name}: пополнение на {_fmt_money(doliv_amount)} "
        f"(100% текущего депозита).\n"
        f"После пополнения просадка в моменте ≈ {_fmt_dd(new_dd)} "
        f"(как в примере академии: при удвоении баланса процент примерно снижается вдвое)."
    )

    # Портфельный план (2+ счёта) — как в Notion
    if len(accounts) >= 2 and calm.name != critical.name and calm.drawdown_pct < critical.drawdown_pct:
        transfer = round(calm.balance * 0.9, 2)
        leave = round(calm.balance - transfer, 2)
        others = [a for a in accounts if a.name not in (critical.name, calm.name)]

        lines.append(
            f"\nВариант без внешнего капитала (портфель роботов), как в академии:\n"
            f"Сейчас сильнее всего просел {critical.name} ({_fmt_dd(critical.drawdown_pct)}), "
            f"спокойнее всего {calm.name} ({_fmt_dd(calm.drawdown_pct)}).\n\n"
            f"Порядок действий:\n"
            f"1. Остановите торговлю на {calm.name} (наименьшая просадка).\n"
            f"2. В кабинете брокера переведите ~90% депозита с {calm.name} на {critical.name}: "
            f"{_fmt_money(transfer)} (оставьте ≈ {_fmt_money(leave)} / 10% на {calm.name}, "
            f"чтобы не ликвидировать счёт).\n"
        )
        if others:
            names = ", ".join(a.name for a in others)
            lines.append(
                f"3. Советник(и) {names} желательно перевести в режим сушки.\n"
            )
            step = 4
        else:
            step = 3
        lines.append(
            f"{step}. Когда просадка на {critical.name} снизится до 0% — остановите его, "
            f"пока «подушка» ещё на балансе (чтобы не открыл новые ордера с увеличенного депозита).\n"
            f"{step + 1}. Верните средства на {calm.name} и запустите всех советников в штатном режиме.\n\n"
            "Так вы используете средства внутри системы, не внося новый капитал снаружи."
        )
        lines.append(
            f"\nАльтернатива: внешний долив на {critical.name} — пополнить ещё "
            f"{_fmt_money(doliv_amount)} со своего кошелька."
        )
    else:
        lines.append(
            f"\nПлан для одного счёта ({critical.name}):\n"
            f"1. Убедитесь, что сушка включена; если просадка продолжает расти — делайте долив.\n"
            f"2. Пополните счёт на {_fmt_money(doliv_amount)} (ровно 100% депозита).\n"
            f"3. Контролируйте MoniTrading / терминал.\n"
            f"4. Если после долива просадка снова ≈ 50% — отключите Auto Trading и напишите "
            f"@Emarcapitalbot."
        )

    lines.append(
        "\nОриентиры академии для долива: просадка примерно −30%…−40%, "
        "уровень маржи примерно от 2500% до 1000%."
    )
    return "\n".join(lines)


def try_doliv_plan(text: str) -> str | None:
    """Точка входа для бота: план или подсказка формата, либо None."""
    t = _norm(text)
    accounts = _parse_accounts(text)
    if accounts:
        return build_doliv_plan(text)
    if looks_like_calc_request(text) or (
        "долив" in t and any(h in t for h in ("посчитай", "рассчитай", "калькулятор", "сколько"))
    ):
        return build_doliv_plan(text)  # вернёт подсказку формата
    return None
