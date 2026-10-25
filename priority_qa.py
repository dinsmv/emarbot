"""Приоритетные ответы — официальная политика компании поверх RAG."""
from __future__ import annotations

import re

from dialog_context import combine_with_context, history_pairs, normalize_user_question

_DRAWDOWN_WORDS = ("просадк", "долив", "подушк", "сушк", "drawdown")
_DOLIV_WORDS = ("долив", "подушк", "долить", "залить")

OFFICIAL_DRAWDOWN_POLICY = """Что делать при просадке — схема EMAR Capital:

Сначала оцените уровень просадки в MoniTrading / терминале. Дальше действуйте по этапам:

1. Норма (0–20%) — рабочая зона советника. Беспокоиться не нужно, ничего не меняйте.

2. Первые действия (20–30%) — включите режим сушки (пары не набирают новые ордера) и дождитесь отката цены. Альтернатива: высушить до 0% и сменить точку входа.

3. Долив (если после сушки просадка продолжает расти) — это пополнение счёта «подушкой безопасности».
   Долив — пополнение торгового счёта на 100% от текущего депозита на этом счёте (не 50% и не «вернуть часть»).
   Пример: на счёте 1000 $ → вносите ещё 1000 $. После этого просадка в моменте снижается примерно до 30–33%, и советнику легче выровнять позиции.

4. Критический уровень — если после долива просадка снова достигла 50%: немедленно отключите Auto Trading и напишите в техподдержку @Emarcapitalbot. Автоторговлю не включайте до консультации.

При просадке 30% и выше не рекомендуется «ничего не делать». Контролируйте счёт в MoniTrading и терминале."""

HOW_TO_DOLIV = """Долив (подушка безопасности) — это пополнение торгового счёта на сумму, равную 100% текущего депозита на этом счёте.

Его делают, когда после включения сушки просадка продолжает расти: подушка даёт советнику запас маржи и снижает процент просадки.

Как сделать долив:

1. Убедитесь, что сушка уже включена, а просадка всё ещё растёт — тогда нужен долив.
2. Пополните счёт на 100% от текущего депозита (не 50%, не «вернуть до исходного» частично — именно 100%).
   Пример: на счёте 1000 $ при просадке → пополнение ещё на 1000 $.
3. После пополнения следите за MoniTrading и терминалом, дождитесь отката.
4. Выводить долив можно только после полного выхода в 0% просадки: сначала отключите Auto Trading, затем выведите подушку, потом снова запустите советник с исходным депозитом."""

COMPANY_ABOUT = """EMAR Capital — это команда разработчиков, трейдеров и специалистов по автоматизированной торговле.

Мы создаём и сопровождаем торговых советников для рынка Forex, которые помогают автоматизировать торговлю и снизить влияние эмоций на решения.

Мы не принимаем деньги клиентов в управление и не имеем доступа к вашим средствам. Каждый клиент самостоятельно владеет своим брокерским счётом: пополнение и вывод доступны только вам. Перед покупкой можно бесплатно протестировать советника 14 дней."""

COMPANY_NOT_SCAM = """EMAR Capital — команда разработчиков и трейдеров: мы создаём и сопровождаем торговых советников для Forex.

Мы не принимаем деньги клиентов в управление и не имеем доступа к вашим средствам. Торговля идёт на вашем личном брокерском счёте: пополнение и вывод — только у вас.

Перед покупкой можно бесплатно протестировать советника 14 дней, проверить работу на своём депозите и при желании отключить систему и вывести средства."""

MONITRADING_ABOUT = """MoniTrading — это удобный сервис для мониторинга и анализа торговых показателей от EMAR Capital.

С ним можно:
• наблюдать за показателями работы и статусом автоторговли;
• видеть баланс и процент средств в работе (просадку);
• смотреть количество открытых сделок и их объём;
• следить за доходностью с момента запуска, за текущий и предыдущий месяцы.

Преимущества: открывается с телефона, планшета или компьютера; все счета на одном экране; обновление каждые 10 секунд; не нужно каждый раз заходить на удалённый стол. Если вовремя заметить отклонения — можно принять меры и избежать критических последствий.

Для подключения нужна регистрация мониторинга (есть видео-инструкция)."""

MONITRADING_REQUIREMENTS = """Чтобы работать с MoniTrading, нужно:

1. Зарегистрироваться в сервисе мониторинга MoniTrading (есть видео-инструкция «Регистрация мониторинга»).
2. Получить ключ мониторинга в личном кабинете.
3. Передать ключ в техподдержку EMAR Capital для привязки к торговому счёту / советнику.
4. При необходимости настроить уведомления в Telegram в разделе мониторинга.

После подключения вы сможете с телефона или компьютера следить за балансом, просадкой, сделками и доходностью — обновление примерно каждые 10 секунд. Отдельный удалённый стол для этого не обязателен."""

VPS_ABOUT = """В контексте EMAR Capital «сервер» — это VPS (Virtual Private Server, виртуальный частный сервер): удалённый компьютер, на котором установлено ПО для работы торгового советника.

Он называется виртуальным, потому что вы получаете выделенную часть ресурсов физического сервера у провайдера. К нему можно подключиться из любой точки мира через интернет — как к своему рабочему столу.

Зачем он нужен: советник должен работать круглосуточно. На домашнем компьютере пришлось бы держать ПК включённым 24/7 с стабильным интернетом и удалённым доступом. Аренда VPS надёжнее и обычно выгоднее: сервер работает без перебоев электричества и домашней сети, ордера исполняются стабильнее, а вы можете управлять сервером с телефона или компьютера.

В EMAR Capital для аренды используют сервис GOVPSFX. Регистрацию и вход удобно смотреть по видео в «Материалах» («Регистрация и аренда сервера GOVPSFX», «Как зайти на VPS сервер»)."""

ADVISOR_RISKS = """Риски есть — как в любой работе на Forex. Кратко по делу:

1. Рыночный риск — рынок волатилен, бывают просадки. Рабочая зона обычно 0–20%. Дальше по схеме компании: сушка при 20–30%, долив (подушка 100% депозита), а если после долива снова около 50% — отключить Auto Trading и написать в техподдержку.

2. Риск профиля — Conservative / Medium / Aggressive / Trinity X дают разный потенциал и разную нагрузку по просадке. Чем выше ожидаемая доходность, тем выше риск — профиль выбирают под себя.

3. Технические риски — сбои терминала, интернета или сервера. Их снижают VPS (работа 24/7) и контроль в MoniTrading.

Средства всегда на вашем брокерском счёте, компания к ним доступа не имеет. Результат зависит от рынка и дисциплины; перед стартом можно пройти тестовый период 14 дней."""

EARNINGS_ABOUT = """Советники EMAR Capital как раз рассчитаны на заработок на Forex — на вашем личном брокерском счёте.

По историческим данным прошлых лет у клиентов в среднем выходило порядка 5–7% в месяц. На текущий год можно ориентироваться на похожие цифры, но итог зависит от рынка и профиля (Conservative / Medium / Aggressive / Trinity X): выше потенциал — выше риск.

Чтобы результат был стабильнее:
• держитесь настроек и правил по каждому советнику;
• соблюдайте риск-менеджмент (сушка и долив по схеме при просадке);
• периодически смотрите MoniTrading и терминал.

Гарантировать процент нельзя — это рынок. Но при дисциплине и контроле система работает именно на результат. Перед покупкой доступен тест 14 дней."""

DEPOSIT_TOPUP = """Пополнение торгового счёта выполняется через личный кабинет брокера. Для Forex4You и RoboForex доступно пополнение криптовалютой (USDT).

Для Forex4You: YouTube https://www.youtube.com/watch?v=2Sfv0Bt0Klk , VK Video https://vkvideo.ru/video-233074365_456239101 , RuTube https://rutube.ru/video/8576f0654d97cc6049d37f9e72dda406/ (в «Материалах» — «Forex4You: регистрация, открытие счета и пополнение»). Для RoboForex — «Пополнение брокера ROBOFOREX». Напишите, у какого брокера у вас счёт — подскажу точнее или пришлю нужное видео."""

WITHDRAW_FUNDS = """Вывод средств выполняется через личный кабинет брокера на ваш криптокошелёк. По регламенту обработка до 5 дней, на практике часто 1–2 часа.

Минимальная сумма вывода зависит от правил брокера (от 10$ и выше). Свободные средства для вывода отображаются в показателе Equity. Перед полным выводом средств обычно переводят советник в режим сушки."""

HOW_TO_INSTALL = """Установку и активацию торгового советника делает техподдержка EMAR Capital — самостоятельно настраивать терминал не нужно.

Как это проходит:
1. Подготовьте VPS (аренда на GOVPSFX — видео в «Материалах»), брокерский счёт и ключ MoniTrading.
2. Напишите в техподдержку @Emarcapitalbot (или через бота → «Написать в техподдержку»).
3. В заявке укажите: IP, логин и пароль VPS; номер и пароль торгового счёта; сервер брокера; ключ MoniTrading; название советника.
4. Специалист установит и настроит советника (обычно в течение суток).

Если нужен готовый текст заявки — напишите «шаблон на установку»."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _is_drawdown_action_question(text: str) -> bool:
    """Своя просадка / что делать — не определения и не «допустимая просадка» при подборе."""
    t = _norm(text)
    if not any(w in t for w in ("просадк", "drawdown")):
        return False
    # «что такое просадка/сушка» — define → RAG, не policy
    if re.search(r"(что|че|чё|шо|што)\s+(такое|это|за)\b", t) or re.search(r"\bэто\s+что\b", t):
        return False
    # лимит при подборе советника
    if re.search(r"допустим|приемлем|приемлемая", t):
        return False
    if re.search(r"(подбер|подойд|какой\s+советник|какая\s+верси|профил)", t) and not re.search(
        r"что\s+делать|у\s+меня|у\s+нас", t
    ):
        return False
    if re.search(r"у\s+меня|у\s+нас|моя\s+просадк|наш[ае]\s+просадк", t):
        return True
    if re.search(r"что\s+делать|как\s+быть|как\s+действов|что\s+предпринять", t):
        return True
    if re.search(r"раст[её]т|вырос|критич", t):
        return True
    if re.search(r"при\s+просадк|если\s+просадк", t):
        return True
    if _extract_pct(t) is not None:
        return True
    return False


def _is_drawdown_topic(text: str) -> bool:
    """Совместимость: только actionable-просадка (не любое упоминание сушки/долива)."""
    return _is_drawdown_action_question(text)


_WORD_PCT = {
    "десять": 10, "пятнадцать": 15, "двадцать": 20, "двацат": 20,
    "тридцать": 30, "трицат": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
}


def _extract_pct(text: str) -> int | None:
    t = _norm(text)
    m = re.search(
        r"(?:больше|свыше|от|около|почти|уже)?\s*(\d{1,2})\s*(?:%|процент\w*)",
        t,
    )
    if m:
        return int(m.group(1))
    m = re.search(r"просадк\w*\s*(?:уже\s*)?(?:почти\s*|больше\s*|свыше\s*)?(\d{1,2})", t)
    if m:
        return int(m.group(1))
    for word, val in _WORD_PCT.items():
        if word in t and ("процент" in t or "просадк" in t):
            return val
    return None


def _is_definition_or_howto_doliv(text: str) -> bool:
    """Только «как сделать долив». «Что такое долив/сушка» → RAG (define), не priority."""
    t = _norm(text)
    if not any(w in t for w in _DOLIV_WORDS):
        return False
    if re.search(r"(что|че|чё|шо|што)\s+(такое|это|за)\b", t) or re.search(r"\bэто\s+что\b", t):
        return False
    if re.search(r"\bкак\b", t) and any(w in t for w in _DOLIV_WORDS):
        return True
    if any(p in t for p in ("как сделать", "как делать", "как правильно", "как это")):
        return True
    return False


def _is_about_monitrading(text: str) -> bool:
    t = _norm(text)
    t = t.replace("ьэто", "это")
    if not any(w in t for w in ("monitrading", "монитрейдинг", "fxmonitor", "фхмонитор")):
        return False
    # «что это / преимущества» — определение; «как зарегистрировать» — не сюда
    if re.search(r"регист|зарегист|как\s+подключ|как\s+настро|видео|инструкц", t):
        return False
    return bool(
        re.search(
            r"что\s+(это|такое|за)|че\s+(это|такое)|это\s+что|преимуществ|зачем|для\s+чего|особенност|"
            r"что\s+нужн|для\s+работы",
            t,
        )
        or t.strip() in ("monitrading", "монитрейдинг", "fxmonitor")
    )


def _is_monitrading_requirements(text: str) -> bool:
    t = _norm(text)
    if not any(w in t for w in ("monitrading", "монитрейдинг", "fxmonitor", "фхмонитор")):
        return False
    return bool(re.search(r"что\s+нужн|для\s+работы|как\s+начать|что\s+надо", t))


def _is_about_vps(text: str) -> bool:
    t = _norm(text)
    t = t.replace("ьэто", "это")
    # «сервер» в контексте EMAR = VPS; регистрацию/видео не перехватываем
    if not any(w in t for w in ("vps", "впс", "виртуальн", "сервер", "govps")):
        return False
    if re.search(
        r"регист|зарегист|зарегать|аренд|заказать|как\s+зайти|как\s+войти|как\s+подключ|"
        r"видео|инструкц|удаленн\w*\s+стол",
        t,
    ):
        return False
    return bool(
        re.search(
            r"что\s+(это|такое|за)|че\s+(это|такое)|это\s+что|"
            r"зачем(\s+он)?(\s+нужен)?|для\s+чего|назначен|преимуществ|особенност",
            t,
        )
        or t.strip() in ("vps", "впс", "сервер", "vps сервер", "vps сервера")
    )


def _is_term_definition(text: str) -> bool:
    """«Что такое X» — определение термина (не про компанию)."""
    t = _norm(text)
    return bool(
        re.search(r"(что|че|чё|шо|што)\s+(такое|это|за)\b", t)
        or re.search(r"\bэто\s+что\b", t)
    )


def _is_about_company(text: str) -> bool:
    t = _norm(text)
    if re.search(r"кто\s+(такая|такое|такие|вы)|что\s+за\s+компани|о\s+компани", t):
        return True
    if ("emar" in t or "емар" in t) and any(
        w in t for w in ("кто", "что", "компани", "это")
    ):
        return True
    return bool(
        re.search(r"расскажите\s+о\s+компани|чем\s+занимается\s+компани", t)
    )


def _is_trust_question(text: str) -> bool:
    t = _norm(text)
    return bool(
        re.search(
            r"мошен|скам|развод|кидал|обман|жулик|ворь|"
            r"можно\s+доверять|это\s+развод|не\s+развод|кидалов|"
            r"они\s+нормальн|вы\s+нормальн",
            t,
        )
    )


def _is_risk_question(text: str) -> bool:
    t = _norm(text)
    if any(w in t for w in ("просадк", "долив", "сушк")):
        return False
    if "риск" in t:
        return True
    return bool(
        re.search(
            r"чем\s+я\s+рискую|насколько\s+это\s+рискованно|какие\s+риски",
            t,
        )
    )


def _is_earnings_question(text: str) -> bool:
    t = _norm(text)
    return bool(
        re.search(
            r"сколько\s+.{0,40}?заработ|"
            r"сколько\s+можно\s+заработ|"
            r"можно\s+ли\s+заработ|"
            r"реально\s+ли\s+заработ|"
            r"какая\s+доходн|"
            r"какую\s+доходн|"
            r"какой\s+доход|"
            r"средн\w*\s+доход|"
            r"заработ\w*\s+тут|"
            r"тут\s+заработ",
            t,
        )
    )


def _is_deposit_topup_question(text: str) -> bool:
    """Общее «как пополнить» без названия брокера — текст, не видео."""
    t = _norm(text)
    if any(w in t for w in ("долив", "подушк", "просадк")):
        return False
    if any(k in t for k in ("forex4", "forex 4", "roboforex", "робофорекс")):
        return False
    if re.search(r"видео|инструкц|скинь|пришли", t):
        return False
    return bool(re.search(r"пополн", t) and re.search(r"депозит|сч[её]т|баланс", t))


def _is_withdraw_question(text: str) -> bool:
    t = _norm(text)
    if any(w in t for w in ("долив", "подушк", "просадк")):
        return False
    if any(k in t for k in ("forex4", "forex 4", "roboforex", "робофорекс")):
        return False
    return bool(
        re.search(r"вывод|вывести", t)
        and re.search(r"депозит|средств|деньг|сч[её]т|баланс|прибыл", t)
    )


def _is_install_howto(text: str) -> bool:
    """Как установить / активировать советника — процесс, не шаблон заявки."""
    t = _norm(text)
    if "шаблон" in t:
        return False
    if re.search(r"заявк", t) and "техподдерж" in t:
        return False
    if re.search(r"как\s+(?:его\s+|её\s+|ее\s+|мне\s+)?(?:установ|подключ|активир)", t):
        return True
    if re.search(r"(?:установ|подключ|активир)", t) and any(
        w in t for w in ("советник", "робот", "лиценз")
    ):
        return True
    return False


def _last_assistant_text(history) -> str | None:
    for role, msg in reversed(history_pairs(history)):
        if str(role).lower() in ("assistant", "bot") and (msg or "").strip():
            return str(msg)
    return None


def _pct_from_normal_zone_answer(assistant_text: str) -> int | None:
    """Если последний ответ бота — короткий «норма 0–20%», вернуть названный %."""
    t = _norm(assistant_text or "")
    if "рабочая зона" not in t and "беспокоиться не нужно" not in t:
        return None
    m = re.search(r"при просадке\s+(\d{1,2})\s*%", t)
    if m:
        pct = int(m.group(1))
        return pct if pct <= 20 else None
    pct = _extract_pct(t)
    if pct is not None and pct <= 20:
        return pct
    return None


def _is_nothing_to_do_followup(text: str) -> bool:
    t = _norm(text)
    return bool(
        re.search(
            r"ничего\s+не\s+делать|ничего\s+не\s+меня|можно\s+не\s+делать|"
            r"не\s+надо\s+ничего|не\s+нужно\s+ничего|просто\s+ждать|"
            r"то\s+есть\s+ничего|значит\s+ничего|это\s+норма|вс[её]\s+ок|"
            r"верно\s*\?|правильно\s*\?",
            t,
        )
    )


def _is_short_what_to_do_followup(text: str) -> bool:
    """Только короткое «(а) что делать?» — не «партнера что делать»."""
    t = _norm(text)
    return bool(
        re.fullmatch(
            r"(а\s+)?(что|как)\s+(мне\s+)?(делать|быть)\??",
            t,
        )
    )


def _drawdown_followup_after_normal(raw: str, history) -> str | None:
    """После короткого ответа 0–20% — подтверждать норму, не слать схему/подушку.

    Не срабатывает, если пользователь сменил тему (партнёр, шаблон, советник…).
    """
    last = _last_assistant_text(history)
    if not last:
        return None
    prev_pct = _pct_from_normal_zone_answer(last)
    if prev_pct is None:
        return None
    # Новая substantive-тема ≠ просадка → не цеплять старый ответ
    from dialog_context import substantive_topics

    topics = substantive_topics(raw)
    if topics - {"drawdown", "drying"}:
        return None
    if not (
        _is_nothing_to_do_followup(raw) or _is_short_what_to_do_followup(raw)
    ):
        return None
    return (
        f"Да, при просадке {prev_pct}% ничего делать не нужно — это норма "
        f"(рабочая зона 0–20%). Просто наблюдайте за счётом в MoniTrading."
    )


def should_keep_priority_verbatim(text: str, history=None) -> bool:
    """Просадка/долив/заработок/риски — дословно, без adapt (иначе LLM искажает).

    Установка советника — не сюда: для неё режим adapt (факты те же, тон живее).
    """
    raw = normalize_user_question(text)
    if _drawdown_followup_after_normal(raw, history):
        return True
    return (
        _is_earnings_question(raw)
        or _is_risk_question(raw)
        or _is_drawdown_action_question(raw)
        or _is_definition_or_howto_doliv(raw)
    )


def match_priority_answer(text: str, history=None) -> str | None:
    """Официальные ответы. Тема берётся из ТЕКУЩЕГО сообщения (raw),
    чтобы история («сколько заработать») не перебивала «какие риски?»."""
    raw = normalize_user_question(text)
    query = combine_with_context(raw, history) if history else raw

    # Follow-up после короткого «норма 0–20%» — не противоречить предыдущему ответу
    confirm = _drawdown_followup_after_normal(raw, history)
    if confirm:
        return confirm

    # Сначала узкие темы по текущей реплике
    if _is_risk_question(raw):
        return ADVISOR_RISKS
    if _is_earnings_question(raw):
        return EARNINGS_ABOUT
    if _is_trust_question(raw):
        return COMPANY_NOT_SCAM
    if _is_monitrading_requirements(raw):
        return MONITRADING_REQUIREMENTS
    if _is_about_monitrading(raw):
        return MONITRADING_ABOUT
    if _is_about_vps(raw):
        return VPS_ABOUT
    if _is_about_company(raw):
        return COMPANY_ABOUT
    if _is_deposit_topup_question(raw):
        return DEPOSIT_TOPUP
    if _is_withdraw_question(raw):
        return WITHDRAW_FUNDS
    if _is_install_howto(raw):
        return HOW_TO_INSTALL
    # Follow-up «как его установить?» после определения советника
    if raw != query and _is_install_howto(query):
        return HOW_TO_INSTALL

    # Долив-howto (не «что такое долив»)
    if _is_definition_or_howto_doliv(raw):
        return HOW_TO_DOLIV
    # Просадка — только своя / что делать (не сушка как термин, не «допустимая 20%»)
    if _is_drawdown_action_question(raw) or (
        raw != query and _is_drawdown_action_question(query) and _extract_pct(raw) is not None
    ):
        pct = _extract_pct(raw)
        if pct is None:
            pct = _extract_pct(query) if raw != query else None
        ans = _match_drawdown_answer(raw, query, pct)
        if ans:
            return ans

    # «Что такое лонг/стопы/…» — только RAG. Не подмешивать COMPANY_ABOUT из history («кто вы»).
    if _is_term_definition(raw) and not (
        _is_about_company(raw)
        or _is_trust_question(raw)
        or _is_about_monitrading(raw)
        or _is_about_vps(raw)
    ):
        return None

    # Короткие follow-up («а сколько?») — только если raw сам не тема
    if raw != query and not _is_term_definition(raw):
        if _is_risk_question(query):
            return ADVISOR_RISKS
        if _is_earnings_question(query):
            return EARNINGS_ABOUT
        if _is_about_company(query):
            return COMPANY_ABOUT
        if _is_about_monitrading(query):
            return MONITRADING_ABOUT
        if _is_deposit_topup_question(query):
            return DEPOSIT_TOPUP
        if _is_withdraw_question(query):
            return WITHDRAW_FUNDS

    return None


def _match_drawdown_answer(raw: str, query: str, pct: int | None) -> str | None:
    if _is_definition_or_howto_doliv(raw):
        return HOW_TO_DOLIV
    # 0–20% — коротко: норма + одна строка про схему (без полной копии)
    if pct is not None and pct <= 20:
        return (
            f"При просадке {pct}% — это рабочая зона (0–20%). "
            "Беспокоиться не нужно, ничего не меняйте; наблюдайте за счётом в MoniTrading.\n\n"
            "Схема на случай роста: сушка при 20–30%, далее долив (подушка 100% депозита)."
        )
    # >20% или без процента — полная официальная схема дословно, без дублей сверху
    if pct is not None or "просадк" in _norm(raw):
        return OFFICIAL_DRAWDOWN_POLICY
    return None
