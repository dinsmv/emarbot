from __future__ import annotations

import os
import re
import logging
import time
from typing import List, Optional

import requests
from dotenv import load_dotenv
from anthropic import Anthropic
from groq import Groq

from brand import apply_brand_terms, make_confident, HISTORICAL_YIELD, MONITRADING_FULL

DRAWDOWN_POLICY = """
При вопросах о просадке, доливе, сушке — используй ТОЛЬКО официальную схему EMAR Capital:
• 0–20% — норма, ничего не делать
• 20–30% — сушка, ждать отката (или высушить до 0% и сменить вход)
• после сушки просадка растёт — долив 100% от депозита на счёте (не 50%, не частичное «вернуть 300$»)
• после долива снова 50% — отключить Auto Trading, техподдержка
Никогда не советуй «ничего не делать» при просадке 30% и выше.
"""

load_dotenv()

JINA_API_KEY = os.getenv("JINA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
ANTHROPIC_WORKSPACE_ID = (os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip() or None
COMPANY_NAME = os.getenv("COMPANY_NAME", "EMAR Capital")

JINA_MODEL = "jina-embeddings-v3"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")

ESCALATE_MARKER = "__ESCALATE__"

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
_anthropic_headers = (
    {"anthropic-workspace-id": ANTHROPIC_WORKSPACE_ID}
    if ANTHROPIC_WORKSPACE_ID
    else None
)
anthropic_client = (
    Anthropic(api_key=ANTHROPIC_API_KEY, default_headers=_anthropic_headers)
    if ANTHROPIC_API_KEY
    else None
)

_LANGUAGE_RULE = (
    "Пиши только на русском языке кириллицей. "
    "Никогда не вставляй китайские, японские, корейские символы или иероглифы."
)

_FORMAT_RULE = (
    "ФОРМАТИРОВАНИЕ: пошаговые инструкции оформляй нумерованным списком, каждый "
    "пункт с новой строки. Перечисления — маркированным списком с новой строки. "
    "Между смысловыми блоками — пустая строка. Абзацы не длиннее 3 предложений. "
    "Никогда не пиши сплошную простыню текста. "
    "Без Markdown и HTML: не используй **, __, *, #, ```, <b>, <i> — только обычный текст."
)

SYSTEM_PROMPT = f"""Ты — бот техподдержки компании {COMPANY_NAME} (торговые советники на Forex).
Отвечай вежливо, понятно, на «вы». Пиши уверенно и по делу.
{_LANGUAGE_RULE}
{_FORMAT_RULE}
Используй информацию из предоставленного контекста (фрагменты базы знаний).
Если вопрос общий («что это», «что такое»), собери связный ответ из связанных фактов во фрагментах.
Учитывай предыдущую переписку — местоимения («его», «это», «там», «тут», «риски», «у него», «параметры») относятся к теме диалога.
Если в вопросе назван конкретный советник (Classic / King / Trinity + Conservative / Medium / Aggressive / Trinity X) —
отвечай ТОЛЬКО про него. Не подменяй на другую линейку или профиль.
Если спрашивают «технические параметры» / «характеристики» / «депозит, лот, пары» —
перечисли ВСЕ параметры из фрагментов списком (депозит, доходность, платформа, брокеры, счёт, плечо, инструменты, таймфрейм, лот, режим). Не сокращай до 2–3 пунктов.
Если спрашивают «принцип работы» / «как работает» — раскрой суть: чем отличается, кто принимает решение о входе, что делает робот, ключевые модули (индикаторы, пирамидинг и т.д.). Не ограничивайся одним общим предложением.
Сервис мониторинга называется MoniTrading ({MONITRADING_FULL}). Не используй старое название FXmonitor.
Если спрашивают о доходности, заработке, «сколько могу заработать» — упомяни исторический ориентир:
{HISTORICAL_YIELD}
{DRAWDOWN_POLICY}
Не используй слова «вероятно», «возможно», «скорее всего», «скорей всего», «имеется в виду».
Ответь ровно одной строкой {ESCALATE_MARKER} только если фрагменты совсем не по теме вопроса.
Не давай индивидуальных инвестиционных советов и не обещай гарантированную прибыль.
Не упоминай, что ты ИИ или языковая модель."""

SYNTHESIS_PROMPT = f"""Ты — бот техподдержки компании {COMPANY_NAME}.
{_LANGUAGE_RULE}
{_FORMAT_RULE}
Поиск нашёл похожие фрагменты базы знаний, но нет дословного ответа на вопрос клиента.
Собери из фрагментов максимально полезный связный ответ, как это делает живой специалист поддержки.
Учитывай переписку: уточнения («а как его получить?», «а где?», «какие риски?») относятся к предыдущей теме.
Сервис мониторинга — MoniTrading. Не используй FXmonitor.
Пиши уверенно, без «вероятно», «возможно», «скорее всего».
Не выдумывай факты, которых нет во фрагментах и переписке.
Если фрагменты хоть как-то по теме — обязательно ответь.
{ESCALATE_MARKER} — только если тема вопроса и фрагменты полностью разные."""

DEFINE_PROMPT = f"""Ты — бот техподдержки компании {COMPANY_NAME}.
{_LANGUAGE_RULE}
{_FORMAT_RULE}
Клиент спросил определение термина («что такое / что это»).
Отвечай ТОЛЬКО определением этого термина по фрагментам базы.
Начни с «X — это…», затем кратко зачем нужно / как связано с торговлей.
Каждый термин — свой ответ.
ИГНОРИРУЙ предыдущую переписку и чужие темы (просадка, партнёры, цены роботов),
если вопрос — про термин.
Не подменяй ответ текстом «о компании EMAR Capital» и не пиши стоимость советников,
если клиент не спрашивал про цену.
Сервис мониторинга — MoniTrading. Не используй FXmonitor.
Пиши уверенно, без «вероятно/возможно».
Если во фрагментах НЕТ определения нужного термина — ответь ровно: {ESCALATE_MARKER}
Не выдумывай факты вне фрагментов."""


_DEFINE_SUPPORT_LINE = "Подробнее подскажет поддержка @Emarcapitalbot."


def define_term_fallback(question: str) -> str:
    """Если термина нет в базе — короткое общее определение, НЕ текст о компании."""
    t = re.sub(r"\s+", " ", (question or "").lower()).strip()
    m = re.search(
        r"(?:что|че|чё|шо|што)\s+(?:такое|это|за)\s+(.+?)[\?\!\.]*\s*$",
        t,
    )
    term = (m.group(1).strip() if m else "").strip(" «»\"'") or "этот термин"
    term_display = term[:80]
    return (
        f"{term_display.capitalize()} — общий термин из трейдинга/работы с советниками; "
        f"точной карточки в базе знаний сейчас нет. {_DEFINE_SUPPORT_LINE}"
    )


def _define_answer_off_topic(question: str, answer: str) -> bool:
    """Ответ про цены/компанию вместо определения термина."""
    q = (question or "").lower()
    a = (answer or "").lower()
    if not a:
        return True
    if _looks_like_company_blurb(a):
        return True
    # спрашивают термин — а в ответе прайс роботов
    if re.search(r"что\s+(такое|это)|ликвидн|лонг|шорт|стоп|спред|волатил|марж", q):
        if re.search(
            r"стоимост|цена\s+робот|100\s*000|100k|\b2\s*000\b.*mini|mini.*\b2\s*000\b|"
            r"полная\s+версия|мини.?версия",
            a,
        ):
            return True
    return False


# CJK + японский + корейский — случайная вставка токенов из мультиязычной модели
_FOREIGN_SCRIPT = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf"
    r"\u3040-\u30ff\u31f0-\u31ff"
    r"\uac00-\ud7af"
    r"\u3000-\u303f\uf900-\ufaff]"
)
# После вырезания иероглифа из «более详ной» остаётся «болееной»
_BROKEN_WORD_FIXES = (
    (re.compile(r"\bболееной\b", re.IGNORECASE), "более подробной"),
)


def _sanitize_answer(text: str) -> str:
    """Убирает иероглифы, markdown-разметку и чинит обрывы слов."""
    if not text or ESCALATE_MARKER in text:
        return text
    if _FOREIGN_SCRIPT.search(text):
        logging.warning("Ответ содержал нелатинские символы — удалены")
    cleaned = _FOREIGN_SCRIPT.sub("", text)
    for pattern, replacement in _BROKEN_WORD_FIXES:
        cleaned = pattern.sub(replacement, cleaned)
    # Telegram шлёт ответы без parse_mode → **жирный** виден как звёздочки
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = make_confident(apply_brand_terms(cleaned))
    return cleaned.strip()


def get_embedding(text: str) -> list[float]:
    """Эмбеддинг для живого чата: мало попыток, без длинного sleep (не блокируем бота)."""
    return get_embeddings_batch([text], max_attempts=2, max_wait=3)[0]


def get_embeddings_batch(
    texts: List[str],
    max_attempts: int = 10,
    max_wait: int = 60,
) -> List[list[float]]:
    """Пакет эмбеддингов через Jina с повтором при 429.
    Для сборки БД — много попыток; для чата вызывайте с max_attempts=2.
    """
    if not texts:
        return []

    for attempt in range(max_attempts):
        try:
            resp = requests.post(
                "https://api.jina.ai/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {JINA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": JINA_MODEL,
                    "task": "text-matching",
                    "input": texts,
                },
                timeout=30,
            )
            if resp.status_code == 429:
                wait = min(
                    int(resp.headers.get("Retry-After", 5 * (attempt + 1))),
                    max_wait,
                )
                logging.warning(f"Jina 429 — пауза {wait} сек (попытка {attempt + 1})")
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in data]
        except requests.RequestException as e:
            if attempt + 1 >= max_attempts:
                raise
            wait = min(5 * (attempt + 1), max_wait)
            logging.warning(f"Jina error: {e} — retry через {wait}с")
            time.sleep(wait)
    raise RuntimeError("Jina API: превышен лимит запросов после повторов")

def _format_context(fragments: list[dict]) -> str:
    blocks = []
    for i, frag in enumerate(fragments, 1):
        q = frag.get("question", "").strip()
        a = frag.get("answer", "").strip()
        blocks.append(f"Фрагмент {i}:\nВопрос: {q}\nОтвет: {a}")
    return "\n\n".join(blocks)


_HISTORY_LIMIT = 6


def _format_history(history: list[dict]) -> str:
    lines = []
    for msg in history[-_HISTORY_LIMIT:]:
        role = "Клиент" if msg["role"] == "user" else "Поддержка"
        lines.append(f"{role}: {msg['text']}")
    return "\n".join(lines)


def reformulate_for_search(question: str, history: list[dict]) -> str:
    if not history:
        return question

    hist_text = _format_history(history)
    prompt = (
        "Клиент переписывается с техподдержкой торговых советников EMAR Capital.\n"
        "Преобразуй ПОСЛЕДНЕЕ сообщение клиента в один полный самостоятельный вопрос "
        "для поиска по базе знаний.\n"
        "Учитывай контекст переписки. Не добавляй фактов, которых нет в переписке.\n"
        "Если клиент писал «Aggressive» / Classic / King / Trinity / Medium / Conservative — "
        "обязательно сохрани это имя продукта в вопросе. Не подменяй на другой советник.\n"
        "Местоимения «у него», «его», «этого» относятся к последнему названному советнику.\n"
        "Ответь ТОЛЬКО текстом вопроса, одной строкой, без пояснений.\n\n"
        f"Переписка:\n{hist_text}\n\n"
        f"Последнее сообщение клиента: {question}\n\n"
        "Полный вопрос:"
    )

    try:
        result = _call_llm(
            "Ты преобразуешь реплику клиента в полный поисковый вопрос. Ответь одной строкой.",
            prompt,
            max_out=600,
        )
        if result:
            return result.strip().strip('"')
        prev_user = next((m["text"] for m in reversed(history) if m["role"] == "user"), "")
        if prev_user:
            return f"{prev_user} {question}"
        return question
    except Exception as e:
        logging.warning(f"Reformulate error: {e}")
        prev_user = next((m["text"] for m in reversed(history) if m["role"] == "user"), "")
        if prev_user:
            return f"{prev_user} {question}"
        return question


def _build_user_prompt(
    user_question: str,
    fragments: list[dict],
    history: Optional[List[dict]] = None,
) -> str:
    history_block = ""
    if history:
        history_block = (
            "Предыдущая переписка с клиентом:\n"
            + _format_history(history)
            + "\n\n"
        )
    return (
        f"{history_block}"
        f"Текущий вопрос пользователя: {user_question}\n\n"
        f"Контекст из базы знаний:\n{_format_context(fragments)}\n\n"
        f"Сформулируй ответ на текущий вопрос пользователя:"
    )


def _is_escalate(answer: Optional[str]) -> bool:
    return not answer or ESCALATE_MARKER in answer


def _looks_like_company_blurb(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(r"emar capital\s*[—\-–].*команда|не принимаем деньги клиентов в управление", t)
    )


def _call_llm(system_prompt: str, user_prompt: str, max_out: int = 2000) -> Optional[str]:
    """Claude (Anthropic) primary → Groq llama fallback."""
    if anthropic_client:
        try:
            kwargs = dict(
                model=ANTHROPIC_MODEL,
                max_tokens=max_out,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            if ANTHROPIC_WORKSPACE_ID:
                kwargs["extra_headers"] = {
                    "anthropic-workspace-id": ANTHROPIC_WORKSPACE_ID
                }
            message = anthropic_client.messages.create(**kwargs)
            parts = []
            for block in message.content or []:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            raw = "\n".join(parts).strip()
            if raw:
                return _sanitize_answer(raw)
            logging.warning("Claude returned empty content")
        except Exception as e:
            logging.warning("Claude/Anthropic error, fallback to Groq: %s", e)

    if not groq_client:
        logging.warning("Groq client not configured")
        return None
    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=min(max_out, 1200),
        )
        raw = (completion.choices[0].message.content or "").strip()
        return _sanitize_answer(raw) if raw else None
    except Exception as e:
        logging.warning(f"Groq RAG error: {e}")
        return None


def _call_groq(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Optional[str]:
    """Сохранена сигнатура для generate_rag_answer; temperature игнорируется."""
    return _call_llm(system_prompt, user_prompt, max_out=2000)


def _fallback_from_fragments(fragments: list[dict], limit: int = 2) -> Optional[str]:
    """Если LLM сдался — отдать факты из топ-фрагментов (без дублей)."""
    parts: list[str] = []
    seen: set[str] = set()
    for fr in fragments:
        ans = (fr.get("answer") or "").strip()
        q = (fr.get("question") or "").strip()
        if not ans:
            continue
        # Дедупликация: одинаковые/почти одинаковые фрагменты не повторяем
        key = re.sub(r"\W+", "", ans.lower())[:200]
        if key in seen:
            continue
        seen.add(key)
        if q and len(ans) < 80:
            parts.append(f"{q}\n{ans}")
        else:
            parts.append(ans)
        if len(parts) >= limit:
            break
    if not parts:
        return None
    text = "\n\n".join(parts)
    return _sanitize_answer(text) if text else None


def generate_rag_answer(
    user_question: str,
    fragments: list[dict],
    history: Optional[List[dict]] = None,
    intent: Optional[str] = None,
) -> Optional[str]:
    if not fragments:
        return None

    user_prompt = _build_user_prompt(
        user_question,
        fragments,
        history=None if intent == "define" else history,
    )
    is_define = intent == "define"

    if is_define:
        answer = _call_groq(DEFINE_PROMPT, user_prompt, temperature=0.15)
        if not _is_escalate(answer) and not _define_answer_off_topic(user_question, answer or ""):
            return answer
        if answer and _define_answer_off_topic(user_question, answer):
            logging.info("RAG define → off-topic (цены/компания), retry/fallback")
        logging.info("RAG define pass → uncertain, synthesis")
        answer = _call_groq(SYNTHESIS_PROMPT, user_prompt, temperature=0.1)
        if not _is_escalate(answer) and not _define_answer_off_topic(user_question, answer or ""):
            return answer
        # Для определений: фрагмент только если это не текст о компании
        fb = _fallback_from_fragments(fragments)
        if fb and not _looks_like_company_blurb(fb) and not _define_answer_off_topic(user_question, fb):
            logging.info("RAG define → fallback из фрагментов")
            return fb
        logging.info("RAG define → term fallback (нет релевантного определения)")
        return define_term_fallback(user_question)

    # Проход 1: обычный RAG с учётом истории
    answer = _call_groq(SYSTEM_PROMPT, user_prompt)
    if not _is_escalate(answer):
        return answer

    # Проход 2: синтез из похожих фрагментов
    logging.info("RAG pass 1 → uncertain, пробуем synthesis pass 2")
    answer = _call_groq(SYNTHESIS_PROMPT, user_prompt, temperature=0.15)
    if not _is_escalate(answer):
        return answer

    # specs / followup — фрагмент лучше, чем «не уверен», НО только если он
    # реально отвечает на вопрос (иначе бот «вываливает не то» и выглядит глупо)
    if intent in ("specs", "followup", "rag", "policy"):
        fb = _fallback_from_fragments(fragments)
        if fb and len(fb) > 60:
            if answer_matches_question(user_question, fb):
                logging.info("RAG %s → fallback из фрагментов (fit-check OK)", intent)
                return fb
            logging.info("RAG %s → fallback НЕ в тему (fit-check NO), эскалация", intent)

    logging.info("RAG pass 2 → uncertain, эскалация на оператора")
    return None

ADAPT_SYSTEM = f"""Ты — специалист техподдержки {COMPANY_NAME}, отвечаешь клиенту в Telegram.
{_LANGUAGE_RULE}
{_FORMAT_RULE}
Тебе дали вопрос клиента и официальные факты. Перепиши ответ живым человеческим языком.

Правила:
- Используй ТОЛЬКО переданные факты. Цифры, проценты и названия не меняй.
- Первое предложение — прямой ответ на вопрос клиента по сути (риски → про риски, заработок → про доходность).
- Не начинай с одиночных «Да», «Нет», «Да —», «Нет.» — только если вопрос явно да/нет («это скам?»).
- Не тащи чужую тему из «официальных фактов», если вопрос про другое.
- Короткие абзацы по 1–3 предложения; обращение на «вы».
- Простой вопрос = короткий ответ на 3–6 предложений.
- Запрещено: «согласно базе знаний», канцелярит, «вероятно/возможно».
- Иногда заканчивай встречным вопросом (не в каждом ответе).
- Максимум 1 эмодзи."""


def adapt_factual_answer(question: str, facts: str) -> str:
    """Живой тон поверх официальных фактов. При сбое API — исходные facts."""
    if not question or not facts:
        return facts
    user_prompt = (
        f"Вопрос клиента: {question}\n\n"
        f"Официальные факты (единственный источник правды):\n{facts}\n\n"
        "Сформулируй ответ клиенту:"
    )
    answer = _call_llm(ADAPT_SYSTEM, user_prompt, max_out=1500)
    if not answer or ESCALATE_MARKER in answer or len(answer) < 60:
        return facts
    low = answer.lower()
    if any(
        bad in low
        for bad in ("рисков нет", "не сможете заработать", "гарантиру")
    ):
        return facts
    if not answer_matches_question(question, answer):
        return facts
    return answer


_HUMANIZE_STRICT_SYSTEM = f"""Ты — редактор текстов техподдержки {COMPANY_NAME} в Telegram.
{_LANGUAGE_RULE}
{_FORMAT_RULE}
Тебе дали ГОТОВЫЙ текст. Перефразируй его живым человеческим языком.

СТРОГИЕ ПРАВИЛА (strict):
- Можно менять только формулировки, тон и порядок предложений.
- ЗАПРЕЩЕНО добавлять факты, цифры, проценты, суммы, обещания, которых нет в исходнике.
- ЗАПРЕЩЕНО смягчать или убирать формулировки о рисках, ограничениях, отсутствии гарантий.
- Не меняй смысл. Не выдумывай.
- Выдай только переписанный текст, без пояснений."""

_HUMANIZE_SOFT_SYSTEM = f"""Ты — специалист техподдержки {COMPANY_NAME} в Telegram.
{_LANGUAGE_RULE}
{_FORMAT_RULE}
Тебе дали готовый текст. Сделай его живее и естественнее, сохранив все факты.
Можно чуть перестроить абзацы под разговорный тон поддержки.
Не добавляй цифры и факты, которых нет в исходнике.
Выдай только переписанный текст."""


def _extract_numeric_tokens(text: str) -> set[str]:
    """Цифры, проценты, суммы — для проверки галлюцинаций."""
    found = set()
    for m in re.finditer(r"\d+(?:[.,]\d+)?\s*%?", text or ""):
        found.add(re.sub(r"\s+", "", m.group(0)).replace(",", "."))
    return found


def _humanize_strict_suspicious(source: str, result: str) -> bool:
    """True — результат подозрительно отличается (длина или новые цифры)."""
    if not source or not result:
        return True
    src_len = len(source.strip())
    res_len = len(result.strip())
    if src_len > 0:
        ratio = abs(res_len - src_len) / src_len
        if ratio > 0.45:
            return True
    src_nums = _extract_numeric_tokens(source)
    res_nums = _extract_numeric_tokens(result)
    if res_nums - src_nums:
        return True
    return False


def humanize(text: str, strict: bool) -> str:
    """Единый слой «оживления» текста перед отправкой пользователю."""
    if not text or not text.strip():
        return text
    system = _HUMANIZE_STRICT_SYSTEM if strict else _HUMANIZE_SOFT_SYSTEM
    user_prompt = f"Исходный текст:\n{text}\n\nПерепиши для клиента:"
    result = _call_llm(system, user_prompt, max_out=2000)
    if not result or ESCALATE_MARKER in result or len(result) < 40:
        return text
    if strict and _humanize_strict_suspicious(text, result):
        logging.warning(
            "humanize(strict): подозрительный результат "
            "(длина src=%d res=%d, новые числа=%s) — оставляем исходник",
            len(text),
            len(result),
            sorted(_extract_numeric_tokens(result) - _extract_numeric_tokens(text)),
        )
        return text
    return result


def answer_matches_question(question: str, answer: str) -> bool:
    """Быстрая проверка: отвечает ли текст на вопрос (YES/NO)."""
    if not question or not answer:
        return False
    system = (
        "Ответь строго одним словом YES или NO.\n"
        "YES — если ответ по сути отвечает на вопрос клиента.\n"
        "NO — если ответ про другую тему, тащит чужой процент/контекст "
        "или не объясняет то, о чём спросили."
    )
    user_prompt = f"Вопрос: {question}\n\nОтвет: {answer[:1200]}\n\nВердикт:"
    try:
        raw = _call_llm(system, user_prompt, max_out=600)
        if not raw:
            return True  # при сбое API не блокируем ответ
        token = re.split(r"[\s,.;:]+", raw.strip())[0].upper()
        return token.startswith("YES")
    except Exception as e:
        logging.warning(f"Fit-check error: {e}")
        return True  # при сбое API не блокируем ответ
