#!/usr/bin/env python3
"""
Доизвлечение Q&A из недоизвлечённых хабов Notion → notion_hubs_qa.txt.

Не трогает notion_academy_qa.txt и не пересобирает базу.

  cd finish
  python3 extract_notion_hubs.py
"""
from __future__ import annotations

import os
import random
import re
import time
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from extract_notion_academy import (
    EXTRACT_SYSTEM,
    call_groq,
    clean_answer,
    dedupe_pairs,
    format_pairs,
    norm_question,
    parse_qa_text,
    strip_md,
)

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / "resources" / "notion_export"
OUTPUT_FILE = ROOT / "notion_hubs_qa.txt"
ACADEMY_FILE = ROOT / "notion_academy_qa.txt"
CHECKPOINT_FILE = ROOT / "notion_hubs_checkpoint.json"

for env_path in (ROOT / ".env", ROOT.parent / ".env"):
    if env_path.is_file():
        load_dotenv(env_path)
        break

# Страницы с 0 или <5 пар в notion_academy_qa (по диагностике) + приоритет заказчика
HUB_FILES = [
    "Ответы_на_вопросы_для_начинающих.md",
    "ЗНАКОМСТВО_С_КОМПАНИЕЙ.md",
    "ОСНОВНЫЕ_ПОНЯТИЯ.md",
    "Словарь-глоссарий_терминов_трейдинга.md",
    "Линейка_Classic.md",
    "Линейка_King.md",
    "Линейка_Trinity.md",
    "Подключение_к_VPS.md",
    "Базовые_уроки_по_Forex.md",
    "Брокер_и_его_функции.md",
    "VPS_или_удаленный_сервер_-_назначение.md",
    "VPS_сервер.md",
    "ДЕЙСТВИЯ_В_КРИТИЧЕСКОЙ_СИТУАЦИИ.md",
]

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 350
CHUNK_PAUSE = 1.2
MAX_TOKENS = 3500
GROQ_MODEL = "llama-3.3-70b-versatile"

FAQ_EXTRACT_USER = """Раздел: {page_title}
Фрагмент {chunk_no}/{chunk_total} FAQ «вопрос → ответ».

---
{chunk}
---

Извлеки КАЖДЫЙ вопрос отдельной парой. Не объединяй несколько вопросов в одну.
Формат строго:

Вопрос: <текст вопроса клиента>
Ответ: <полный ответ>

Правила: не выдумывай; MoniTrading не FXmonitor; только русский.
Если в фрагменте нет Q&A — ответь: НЕТ"""

GLOSSARY_EXTRACT_USER = """Раздел глоссария: {page_title}
Фрагмент {chunk_no}/{chunk_total}:

---
{chunk}
---

Каждый термин = отдельная пара.
Вопрос формулируй как: «Что такое <термин>?»
Ответ — определение из текста.

Формат:
Вопрос: Что такое <термин>?
Ответ: <определение>

Не выдумывай. Только русский. Если терминов нет — НЕТ"""

HUB_EXTRACT_USER = """Раздел академии: {page_title}
Фрагмент {chunk_no}/{chunk_total}:

---
{chunk}
---

Извлеки ВСЕ полезные сведения максимально подробно (лучше больше коротких пар, чем 2–3 общих).

Вопрос: <как спросил бы клиент>
Ответ: <конкретный ответ: шаги, цифры, названия>

Не выдумывай. MoniTrading. EMAR Capital. Только русский.
Если контента нет — НЕТ"""


def split_chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        if end < len(text):
            cut = text.rfind("\n", start + CHUNK_SIZE // 2, end)
            if cut > start:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def extract_faq_structural(text: str) -> list[dict]:
    """Парсит '- **Вопрос?**' + ответ курсивом/абзацами."""
    pairs: list[dict] = []
    # split by list items that look like questions
    pattern = re.compile(
        r"^-\s+\*{0,3}\s*(.+?)\s*\*{0,3}\s*\n((?:[ \t]+.+\n?)*)",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        q = strip_md(m.group(1))
        a = strip_md(m.group(2))
        q = re.sub(r"^\*+|\*+$", "", q).strip()
        if len(q) < 8 or len(a) < 25:
            continue
        if not ("?" in q or q.lower().startswith(("как", "что", "чем", "есть", "можно", "сколько", "какую", "какой", "какие", "где", "когда", "я ", "гарантир", "существ", "отлича"))) :
            # still allow bold FAQ titles without ?
            if len(q) < 15:
                continue
        pairs.append({"question": q.rstrip("? ") + ("?" if "?" not in q else ""), "answer": clean_answer(a)[:2500]})
    return pairs


def extract_glossary_structural(text: str) -> list[dict]:
    """**Термин** — определение"""
    pairs: list[dict] = []
    for m in re.finditer(
        r"\*\*([^*]+?)\*\*\s*[—–\-]\s*(.+?)(?=\n\n|\n\*\*|\n###|\n---|\Z)",
        text,
        re.S,
    ):
        term = strip_md(m.group(1))
        definition = strip_md(m.group(2))
        if len(term) < 2 or len(definition) < 20:
            continue
        # skip letter headers like "А"
        if len(term) <= 2 and term.isalpha():
            continue
        pairs.append(
            {
                "question": f"Что такое {term}?",
                "answer": clean_answer(definition)[:2500],
            }
        )
    return pairs


def extract_headings_structural(page_title: str, text: str) -> list[dict]:
    """## / ### заголовки → пары (для ОСНОВНЫЕ ПОНЯТИЯ, линеек)."""
    pairs: list[dict] = []
    body = text
    if body.startswith("# "):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    for chunk in re.split(r"\n(?=#{2,4}\s+)", body):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^(#{2,4})\s+(.+)$", chunk)
        if not m:
            continue
        heading = strip_md(m.group(2))
        content = strip_md(chunk[m.end() :].strip())
        if len(content) < 40 or len(heading) < 3:
            continue
        if heading.lower() in ("вывод", "а", "б", "в", "г", "д"):
            continue
        question = heading if "?" in heading else f"Что такое {heading}?" if heading[:1].islower() or len(heading.split()) <= 4 else heading
        if "?" not in question and not question.lower().startswith(("что", "как", "зачем", "чем")):
            question = f"{heading} — что это?"
        pairs.append({"question": question, "answer": clean_answer(content)[:2500], "_page": page_title})
    return pairs


def load_existing_questions() -> set[str]:
    if not ACADEMY_FILE.is_file():
        return set()
    text = ACADEMY_FILE.read_text(encoding="utf-8")
    keys = set()
    for line in text.splitlines():
        if line.startswith("Вопрос:"):
            keys.add(norm_question(line[7:]))
    return keys


def page_title_of(path: Path) -> str:
    return path.stem.replace("_", " ")


def extract_page(path: Path, client: Groq | None) -> list[dict]:
    title = page_title_of(path)
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if len(text) < 80:
        print(f"   ⏭  {path.name}: слишком коротко ({len(text)} симв.)")
        return []

    name = path.name
    pairs: list[dict] = []

    if name == "Ответы_на_вопросы_для_начинающих.md":
        pairs = extract_faq_structural(text)
        print(f"   📋 FAQ structural: {len(pairs)}")
        # добор LLM по чанкам на случай пропусков
        if client and len(pairs) < 30:
            pairs.extend(_llm_chunks(client, title, text, FAQ_EXTRACT_USER))
    elif "Словарь" in name or "глоссарий" in name.lower():
        pairs = extract_glossary_structural(text)
        print(f"   📕 Glossary structural: {len(pairs)}")
        if client and len(pairs) < 40:
            pairs.extend(_llm_chunks(client, title, text, GLOSSARY_EXTRACT_USER))
    elif name == "ОСНОВНЫЕ_ПОНЯТИЯ.md":
        pairs = extract_headings_structural(title, text)
        print(f"   📑 Headings structural: {len(pairs)}")
        if client:
            pairs.extend(_llm_chunks(client, title, text, HUB_EXTRACT_USER))
    else:
        # линейки / VPS / знакомство — LLM + headings
        pairs = extract_headings_structural(title, text)
        print(f"   📑 Headings: {len(pairs)}")
        if client:
            pairs.extend(_llm_chunks(client, title, text, HUB_EXTRACT_USER))

    for p in pairs:
        p.pop("_page", None)
        p["question"] = p["question"].strip()
        p["answer"] = clean_answer(p["answer"])
    return [p for p in pairs if p["question"] and len(p["answer"]) > 15]


def _llm_chunks(client: Groq, title: str, text: str, user_tmpl: str) -> list[dict]:
    out: list[dict] = []
    chunks = split_chunks(text)
    for i, chunk in enumerate(chunks):
        print(f"      🧠 LLM {title[:40]} [{i+1}/{len(chunks)}]", flush=True)
        user = user_tmpl.format(
            page_title=title, chunk_no=i + 1, chunk_total=len(chunks), chunk=chunk
        )
        try:
            result = call_groq(client, EXTRACT_SYSTEM, user)
        except RuntimeError as e:
            print(f"      ⚠️  {e}")
            break
        if result.upper() != "НЕТ" and "Вопрос:" in result:
            new = parse_qa_text(result)
            out.extend(new)
            print(f"         +{len(new)}")
        if i + 1 < len(chunks):
            time.sleep(CHUNK_PAUSE)
    return out


def main():
    import json

    random.seed(42)
    existing = load_existing_questions()
    print(f"Уже в notion_academy_qa.txt: {len(existing)} уникальных вопросов")
    print(f"Хабов к обработке: {len(HUB_FILES)}")
    print("Список:")
    for f in HUB_FILES:
        p = EXPORT_DIR / f
        print(f"  {'✅' if p.is_file() else '❌'} {f}")

    if not os.getenv("GROQ_API_KEY"):
        print("⚠️  GROQ_API_KEY нет — только structural extractors")
        client = None
    else:
        client = Groq()

    per_page: dict[str, int] = {}
    all_pairs: list[dict] = []

    for fname in HUB_FILES:
        path = EXPORT_DIR / fname
        if not path.is_file():
            per_page[fname] = 0
            continue
        print(f"\n▶ {fname}")
        got = extract_page(path, client)
        # убрать дубли с academy и внутри
        fresh = []
        for p in got:
            key = norm_question(p["question"])
            if not key or key in existing:
                continue
            existing.add(key)
            fresh.append(p)
        # page-local dedupe already via existing set
        per_page[fname] = len(fresh)
        all_pairs.extend(fresh)
        print(f"   → новых пар (не дубль academy): {len(fresh)}")

    all_pairs = dedupe_pairs(all_pairs)
    OUTPUT_FILE.write_text(format_pairs(all_pairs), encoding="utf-8")
    CHECKPOINT_FILE.unlink(missing_ok=True)

    print("\n" + "=" * 60)
    print("ПАРЫ ПО СТРАНИЦАМ (новые, без дублей academy):")
    for fname in HUB_FILES:
        print(f"  {per_page.get(fname, 0):4d}  {fname}")
    print(f"\nИТОГО уникальных в {OUTPUT_FILE.name}: {len(all_pairs)}")

    samples = random.sample(all_pairs, min(5, len(all_pairs))) if all_pairs else []
    print("\n5 СЛУЧАЙНЫХ ПРИМЕРОВ:")
    for i, p in enumerate(samples, 1):
        print(f"\n--- {i} ---")
        print(f"Вопрос: {p['question']}")
        ans = p["answer"]
        print(f"Ответ: {ans[:400]}{'…' if len(ans)>400 else ''}")

    # stats sidecar
    stats = {"per_page": per_page, "total": len(all_pairs)}
    (ROOT / "notion_hubs_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
