"""Диспетчер режима ответа: policy vs adapt vs kb.

policy — официальные правила (просадка/долив/риски/trust): факты дословно,
         только лёгкий strict-humanize без новых цифр.
adapt  — есть готовые факты (priority), но формулировку подстраиваем под вопрос.
kb     — ответа в priority нет: ищем в базе (RAG), затем адаптируем под вопрос.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from intent_router import (
    INTENT_DEFINE,
    INTENT_HOWTO,
    INTENT_POLICY,
    INTENT_SPECS,
    INTENT_TRUST,
)
from priority_qa import should_keep_priority_verbatim

MODE_POLICY = "policy"
MODE_ADAPT = "adapt"
MODE_KB = "kb"

ALL_MODES = (MODE_POLICY, MODE_ADAPT, MODE_KB)


@dataclass
class ModeDecision:
    mode: str
    reason: str

    @property
    def label(self) -> str:
        return f"{self.mode}:{self.reason}"


def decide_answer_mode(
    question: str,
    intent: str,
    history=None,
    *,
    has_priority: bool,
) -> ModeDecision:
    """Выбирает, как формулировать текстовый ответ.

    Вызывать после match_priority_answer: has_priority = bool(priority).
    Каналы template / catalog / materials / operator обрабатываются в bot.py отдельно.
    """
    q = (question or "").strip()
    intent = (intent or "").strip().lower()

    # Критичные темы: не давать LLM переиначивать суть
    if intent == INTENT_POLICY:
        return ModeDecision(MODE_POLICY, "intent_policy")
    if has_priority and should_keep_priority_verbatim(q, history):
        return ModeDecision(MODE_POLICY, "priority_verbatim")
    if intent == INTENT_TRUST and has_priority:
        return ModeDecision(MODE_POLICY, "trust_priority")

    # Есть официальный блок — переписать под формулировку клиента
    if has_priority:
        return ModeDecision(MODE_ADAPT, "priority_adapt")

    # Иначе — база знаний
    if intent == INTENT_DEFINE:
        return ModeDecision(MODE_KB, "define")
    if intent == INTENT_SPECS:
        return ModeDecision(MODE_KB, "specs")
    if intent == INTENT_HOWTO:
        return ModeDecision(MODE_KB, "howto")
    return ModeDecision(MODE_KB, f"rag:{intent or 'general'}")


def render_text_answer(
    mode: str,
    question: str,
    draft: str,
    *,
    intent: Optional[str] = None,
) -> str:
    """Постобработка черновика по режиму. При сбое API возвращает draft."""
    from ai_utils import adapt_factual_answer, humanize

    if not draft or not draft.strip():
        return draft

    mode = (mode or MODE_KB).strip().lower()
    intent = (intent or "").strip().lower()

    if mode == MODE_POLICY:
        out = humanize(draft, strict=True)
        logging.info("answer_mode=policy → humanize(strict)")
        return out or draft

    if mode == MODE_ADAPT:
        out = adapt_factual_answer(question, draft)
        logging.info("answer_mode=adapt → adapt_factual_answer")
        return out or draft

    # kb: определения уже собраны DEFINE_PROMPT — не размывать
    if intent == INTENT_DEFINE:
        logging.info("answer_mode=kb/define → raw")
        return draft

    # Остальной RAG: живой ответ строго по найденным фактам
    out = adapt_factual_answer(question, draft)
    logging.info("answer_mode=kb → adapt_factual_answer")
    return out or draft
