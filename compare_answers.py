"""Сверка старых ответов из Google Sheet с текущим пайплайном бота.

Запуск из finish/:
  python3 compare_answers.py --limit 10          # пилот, только консоль
  python3 compare_answers.py --limit 10 --write  # пилот + лист «Сравнение»
  python3 compare_answers.py --write             # все строки → лист «Сравнение»
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import chroma_sqlite_fix  # noqa: F401
import chromadb
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")

from aggression import needs_operator  # noqa: E402
from ai_utils import (  # noqa: E402
    _call_llm,
    generate_rag_answer,
    get_embedding,
    humanize,
    reformulate_for_search,
)
from answer_mode import decide_answer_mode, render_text_answer  # noqa: E402
from dialog_context import (  # noqa: E402
    combine_with_context,
    extract_advisor_entity,
    normalize_user_question,
    resolve_advisor_followup,
)
from doliv_calculator import try_doliv_plan  # noqa: E402
from intent_router import (  # noqa: E402
    CAPABILITIES_REPLY,
    GREETING_REPLY,
    INTENT_CATALOG,
    INTENT_DEFINE,
    INTENT_FOLLOWUP,
    INTENT_GREETING,
    INTENT_HOWTO,
    INTENT_OPERATOR,
    INTENT_TEMPLATE,
    allows_materials,
    classify_intent,
)
from materials import (  # noqa: E402
    format_catalog_list,
    looks_like_catalog_list_request,
    looks_like_material_request,
    match_material,
    match_material_bundle,
    material_clarify_message,
)
from priority_qa import match_priority_answer  # noqa: E402
from templates import (  # noqa: E402
    TEMPLATE_CLARIFY_MSG,
    looks_like_template_request,
    match_template,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("compare")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
CRED_FILE = ROOT / "service_account.json"
RESULT_SHEET = "Сравнение"

POROG = 0.5
RAG_TOP_K = 5
FOLLOWUP_MINUTES = 10
QUESTION_WORDS = (
    "что", "как", "какой", "какая", "какие", "каков", "где", "когда",
    "почему", "зачем", "сколько", "можно", "нужно", "кто", "чем", "откуда",
)

_chroma = chromadb.PersistentClient(path="knowledge_db")
_collection = _chroma.get_collection("faq")


# ---------------------------------------------------------------------------
# Google Sheet
# ---------------------------------------------------------------------------
def open_spreadsheet():
    if not SHEET_ID:
        raise SystemExit("GOOGLE_SHEET_ID не задан в .env")
    if not CRED_FILE.exists():
        raise SystemExit(f"Нет credentials: {CRED_FILE}")
    creds = Credentials.from_service_account_file(str(CRED_FILE), scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID)


def load_log_rows(ss) -> list[dict]:
    ws = ss.worksheet("Лист1")
    values = ws.get_all_values()
    if not values:
        return []
    rows = []
    for i, row in enumerate(values[1:], start=2):
        # A дата, B id, C ник, D вопрос, E ответ, F лог
        while len(row) < 6:
            row.append("")
        date_s, _uid, nick, question, old_answer, status = row[:6]
        if not (question or "").strip():
            continue
        rows.append(
            {
                "sheet_row": i,
                "date": date_s.strip(),
                "nick": (nick or "").strip() or "—",
                "question": question.strip(),
                "old_answer": (old_answer or "").strip(),
                "status": (status or "").strip(),
            }
        )
    return rows


def write_results(ss, results: list[dict]) -> None:
    try:
        ws = ss.worksheet(RESULT_SHEET)
        ss.del_worksheet(ws)
    except gspread.WorksheetNotFound:
        pass
    ws = ss.add_worksheet(title=RESULT_SHEET, rows=max(len(results) + 10, 100), cols=10)
    header = [
        "Дата",
        "Ник",
        "Вопрос",
        "Старый ответ",
        "Новый ответ",
        "Тип вопроса",
        "Вердикт",
        "Комментарий судьи",
    ]
    data = [header]
    for r in results:
        data.append(
            [
                r["date"],
                r["nick"],
                r["question"],
                r["old_answer"],
                r["new_answer"],
                r["qtype"],
                r["verdict"],
                r["comment"],
            ]
        )
    ws.update(data, value_input_option="USER_ENTERED")
    log.info("Записано %d строк на лист «%s»", len(results), RESULT_SHEET)


# ---------------------------------------------------------------------------
# Классификация самостоятельный / продолжение
# ---------------------------------------------------------------------------
def _parse_dt(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def _has_question_word(text: str) -> bool:
    t = text.lower()
    return any(re.search(rf"\b{re.escape(w)}\b", t) for w in QUESTION_WORDS) or "?" in text


def classify_types(rows: list[dict]) -> None:
    """Пишет в каждую строку qtype и prev_question / prev_answer."""
    for i, row in enumerate(rows):
        row["qtype"] = "самостоятельный"
        row["prev_question"] = ""
        row["prev_answer"] = ""
        if i == 0:
            continue
        prev = rows[i - 1]
        if prev["nick"] != row["nick"]:
            continue
        dt = _parse_dt(row["date"])
        pdt = _parse_dt(prev["date"])
        if not dt or not pdt:
            continue
        delta_min = (dt - pdt).total_seconds() / 60.0
        if delta_min < 0 or delta_min > FOLLOWUP_MINUTES:
            continue
        q = row["question"]
        words = _word_count(q)
        ql = q.lower().strip()
        # эвристика: короткое без вопросительных слов ИЛИ явное уточнение к прошлому
        looks_follow = (
            (words < 15 and not _has_question_word(q))
            or re.fullmatch(
                r"(да|нет|ок|окey|ага|угу|не знаю|не осведомлен|не осведомлён|"
                r"хорошо|понял|понятно|а|и|ну)[!?.]*",
                ql,
            )
            is not None
            or bool(
                re.match(
                    r"^(а |и |ну |ещё|еще|там|тут|про |у него|то есть|а если|"
                    r"а что если|значит )",
                    ql,
                )
            )
        )
        if looks_follow:
            row["qtype"] = "продолжение"
            row["prev_question"] = prev["question"]
            row["prev_answer"] = prev["old_answer"]


# ---------------------------------------------------------------------------
# Текущий пайплайн бота (без Telegram / без записи в логи)
# ---------------------------------------------------------------------------
def search_context(question: str):
    try:
        emb = get_embedding(question)
    except Exception as e:
        log.error("embedding failed: %s", e)
        return None
    try:
        results = _collection.query(
            query_embeddings=[emb],
            n_results=max(RAG_TOP_K * 3, 12),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        log.error("chroma failed: %s", e)
        return None
    if not results["documents"] or not results["documents"][0]:
        return None
    if results["distances"][0][0] > POROG:
        return None

    entity = extract_advisor_entity(question)
    entity_tokens = []
    if entity:
        low = entity.lower()
        for tok in ("aggressive", "medium", "conservative", "classic", "king", "trinity"):
            if tok in low:
                entity_tokens.append(tok)

    fragments = []
    for i in range(len(results["documents"][0])):
        distance = results["distances"][0][i]
        if distance > POROG:
            continue
        meta = results["metadatas"][0][i] or {}
        qmeta = meta.get("question", "")
        ans = results["documents"][0][i]
        blob = f"{qmeta} {ans}".lower()
        boost = 0.0
        if entity_tokens:
            hits = sum(1 for t in entity_tokens if t in blob)
            if hits:
                boost = -0.08 * hits
            elif any(t in blob for t in ("aggressive", "medium", "conservative")):
                boost = 0.12
        fragments.append(
            {"question": qmeta, "answer": ans, "distance": distance + boost}
        )

    seen = set()
    unique = []
    for f in sorted(fragments, key=lambda x: x["distance"]):
        key = "".join((f["answer"] or "").lower().split())[:200]
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique[:RAG_TOP_K] or None


def _looks_like_followup(question: str) -> bool:
    t = (question or "").lower().strip()
    return len(t) < 50 or bool(
        re.match(r"^(а |и |ну |ещё|еще|там|тут|про него|у него)", t)
    )


def build_search_query(question: str, history: list[dict]) -> str:
    resolved = resolve_advisor_followup(question, history) if history else None
    if resolved:
        return resolved
    if not history:
        return question
    contextual = combine_with_context(question, history)
    if contextual != question:
        if _looks_like_followup(question) or len(question) < 50:
            return reformulate_for_search(contextual, history)
        return contextual
    if _looks_like_followup(question):
        return reformulate_for_search(question, history)
    return question


def generate_current_answer(question: str, history: list[dict] | None = None) -> str:
    """Синхронный аналог _handle_user_question без Telegram."""
    history = history or []
    вопрос = normalize_user_question(question)
    route = classify_intent(вопрос, history)

    if route.intent == INTENT_GREETING:
        reply = CAPABILITIES_REPLY if route.reason == "capabilities" else GREETING_REPLY
        return humanize(reply, strict=True)

    if route.intent == INTENT_OPERATOR or needs_operator(вопрос):
        return "[эскалация: оператор]"

    if route.intent == INTENT_TEMPLATE or (
        looks_like_template_request(вопрос) and route.intent != INTENT_HOWTO
    ):
        template = match_template(вопрос, history=history)
        if template:
            return f"📝 {template['title']}\n\n{template['text']}"
        return TEMPLATE_CLARIFY_MSG

    if route.intent == INTENT_CATALOG or looks_like_catalog_list_request(вопрос):
        return format_catalog_list()

    doliv_plan = try_doliv_plan(вопрос)
    if doliv_plan:
        return doliv_plan

    priority = match_priority_answer(вопрос, history=history)
    if priority:
        mode = decide_answer_mode(
            вопрос, route.intent, history, has_priority=True
        )
        return render_text_answer(
            mode.mode, вопрос, priority, intent=route.intent
        )

    if allows_materials(route.intent):
        bundle = match_material_bundle(вопрос, history=history)
        if bundle:
            titles = ", ".join(m["title"] for m in bundle)
            return f"[материалы: {titles}]"
        material = match_material(вопрос, history=history)
        if material:
            return f"[материал: {material['title']}]"
        contextual_q = combine_with_context(вопрос, history)
        if looks_like_material_request(contextual_q):
            return material_clarify_message()

    search_q = build_search_query(вопрос, history)
    fragments = search_context(search_q)
    if not fragments and route.intent == INTENT_FOLLOWUP:
        alt_q = combine_with_context(вопрос, history)
        if alt_q != search_q:
            fragments = search_context(alt_q)
    if not fragments:
        return "[эскалация: ответ не найден в базе]"

    draft = generate_rag_answer(
        вопрос, fragments, history=history, intent=route.intent
    )
    if not draft and route.intent == INTENT_DEFINE:
        from ai_utils import define_term_fallback

        draft = define_term_fallback(вопрос)
    if draft:
        mode = decide_answer_mode(
            вопрос, route.intent, history, has_priority=False
        )
        return render_text_answer(
            mode.mode, вопрос, draft, intent=route.intent
        )
    return "[эскалация: ИИ не уверен в ответе]"


# ---------------------------------------------------------------------------
# GPT-судья
# ---------------------------------------------------------------------------
JUDGE_SYSTEM = """Ты — строгий судья качества ответов бота техподдержки EMAR Capital.
Сравни СТАРЫЙ и НОВЫЙ ответ на один и тот же вопрос пользователя.

Критерии:
1) Полнота: новый покрывает вопрос не хуже старого? (лучше / так же / хуже)
2) Точность: есть ли в новом факты/цифры, которых не было в старом и которые
   выглядят выдуманными / не подтверждёнными? (да / нет)
3) Стиль: новый звучит живее/по-человечески? (лучше / так же / хуже)

Финальный вердикт ОДНИМ из:
УЛУЧШЕНИЕ | БЕЗ ИЗМЕНЕНИЙ | УХУДШЕНИЕ | ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ
(последнее — если точность=да или есть сомнение в выдуманных фактах)

Ответь СТРОГО в формате:
ВЕРДИКТ: <одно из четырёх>
КОММЕНТАРИЙ: <одна короткая фраза>"""


def judge_pair(question: str, old: str, new: str) -> tuple[str, str]:
    if not new:
        return "УХУДШЕНИЕ", "Новый ответ пустой."
    if not old:
        return "ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ", "Старого ответа нет в логе."
    # одинаковый текст — без LLM
    if old.strip() == new.strip():
        return "БЕЗ ИЗМЕНЕНИЙ", "Тексты совпадают."

    user = (
        f"Вопрос клиента:\n{question}\n\n"
        f"СТАРЫЙ ответ:\n{old[:2500]}\n\n"
        f"НОВЫЙ ответ:\n{new[:2500]}\n"
    )
    raw = _call_llm(JUDGE_SYSTEM, user, max_out=800)
    if not raw:
        return "ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ", "Судья недоступен (ошибка API)."

    verdict = "ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ"
    comment = raw.strip().split("\n")[0][:200]
    for line in raw.splitlines():
        line = line.strip()
        up = line.upper()
        if up.startswith("ВЕРДИКТ"):
            body = line.split(":", 1)[-1].strip().upper()
            for v in (
                "УЛУЧШЕНИЕ",
                "БЕЗ ИЗМЕНЕНИЙ",
                "УХУДШЕНИЕ",
                "ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ",
            ):
                if v in body:
                    verdict = v
                    break
        if line.upper().startswith("КОММЕНТАРИЙ"):
            comment = line.split(":", 1)[-1].strip()
    return verdict, comment


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(limit: int | None, write: bool) -> None:
    ss = open_spreadsheet()
    rows = load_log_rows(ss)
    log.info("Загружено строк с вопросами: %d", len(rows))
    classify_types(rows)

    if limit:
        rows = rows[:limit]
        log.info("Пилот: берём первые %d строк", limit)

    results = []
    counts = {
        "УЛУЧШЕНИЕ": 0,
        "БЕЗ ИЗМЕНЕНИЙ": 0,
        "УХУДШЕНИЕ": 0,
        "ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ": 0,
    }

    for idx, row in enumerate(rows, 1):
        q = row["question"]
        log.info("[%d/%d] %s | %s | %s", idx, len(rows), row["qtype"], row["nick"], q[:60])

        history = []
        if row["qtype"] == "продолжение" and row["prev_question"]:
            history = [
                {"role": "user", "text": row["prev_question"], "ts": 0},
                {
                    "role": "assistant",
                    "text": row["prev_answer"] or "(предыдущий ответ)",
                    "ts": 0,
                },
            ]

        try:
            new_answer = generate_current_answer(q, history=history)
        except Exception as e:
            log.exception("pipeline error")
            new_answer = f"[ошибка пайплайна: {e}]"

        verdict, comment = judge_pair(q, row["old_answer"], new_answer)
        counts[verdict] = counts.get(verdict, 0) + 1

        results.append(
            {
                "date": row["date"],
                "nick": row["nick"],
                "question": q,
                "old_answer": row["old_answer"],
                "new_answer": new_answer,
                "qtype": row["qtype"],
                "verdict": verdict,
                "comment": comment,
            }
        )

        print("\n" + "=" * 72)
        print(f"#{idx}  {row['date']}  {row['nick']}  [{row['qtype']}]")
        print(f"Q: {q}")
        print(f"OLD: {row['old_answer'][:400]}{'…' if len(row['old_answer'])>400 else ''}")
        print(f"NEW: {new_answer[:400]}{'…' if len(new_answer)>400 else ''}")
        print(f"→ {verdict}: {comment}")

    total = len(results) or 1
    print("\n" + "#" * 72)
    print(f"СВОДКА: всего {len(results)} вопросов")
    for k in (
        "УЛУЧШЕНИЕ",
        "БЕЗ ИЗМЕНЕНИЙ",
        "УХУДШЕНИЕ",
        "ТРЕБУЕТ ПРОВЕРКИ ЧЕЛОВЕКОМ",
    ):
        n = counts.get(k, 0)
        print(f"  {k}: {n} ({100.0 * n / total:.1f}%)")

    if write:
        write_results(ss, results)
    else:
        log.info("Лист не обновляли (нет флага --write)")


def main():
    p = argparse.ArgumentParser(description="Сравнение старых/новых ответов бота")
    p.add_argument("--limit", type=int, default=None, help="Сколько первых строк обработать")
    p.add_argument("--write", action="store_true", help="Записать лист «Сравнение»")
    args = p.parse_args()
    run(limit=args.limit, write=args.write)


if __name__ == "__main__":
    main()
