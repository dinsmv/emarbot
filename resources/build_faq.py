#!/usr/bin/env python3
"""
Сборка resources/faq.json для вкладки FAQ в Mini App.

Источник по умолчанию: finish/faq.docx (~40 вопросов из канала FAQ EMAR CAPITAL).
НЕ использует extracted_qa.txt (это база для RAG-бота, 2600+ записей).

Опционально:
  python3 resources/build_faq.py --from-export
  → взять из faq_export/result.json (экспорт канала FAQ из Telegram Desktop)

Запуск из finish/:
  python3 resources/build_faq.py
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES_DIR = ROOT / "resources"
FAQ_FILE = RES_DIR / "faq.json"
DOCX_FILE = ROOT / "faq.docx"
EXPORT_DIR = RES_DIR / "faq_export"


def flatten_text(text) -> str:
    if isinstance(text, str):
        return text
    if not isinstance(text, list):
        return ""
    chunks = []
    for part in text:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            chunks.append(part.get("text", ""))
    return "".join(chunks)


def parse_faq_docx(path: Path) -> list[dict]:
    import docx

    if not path.is_file():
        return []
    doc = docx.Document(str(path))
    lines = [p.text for p in doc.paragraphs]
    items = []
    question = None
    answer_lines: list[str] = []
    mode = None

    def save():
        nonlocal question, answer_lines
        if question and answer_lines:
            ans = "\n".join(answer_lines).strip()
            if ans:
                items.append({"q": question.strip(), "a": ans})
        question = None
        answer_lines = []

    for line in lines:
        s = line.strip()
        if s.startswith("Вопрос:"):
            save()
            question = s.replace("Вопрос:", "").strip()
            mode = "q"
        elif s.startswith("Ответ:"):
            answer_lines = [s.replace("Ответ:", "").strip()]
            mode = "a"
        elif s:
            if mode == "a":
                answer_lines.append(s)
            elif mode == "q" and question:
                question += " " + s
    save()
    return items


def parse_faq_export(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for msg in data.get("messages", []):
        if msg.get("type") != "message":
            continue
        raw = flatten_text(msg.get("text", "")).strip()
        if not raw or len(raw) < 20:
            continue
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        question = lines[0].strip("*# ")
        answer = "\n".join(lines[1:]).strip()
        if "?" in question:
            items.append({"q": question, "a": answer})
    return items


def dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        key = it["q"].lower().strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка faq.json для Mini App")
    parser.add_argument(
        "--from-export",
        action="store_true",
        help="Взять вопросы из faq_export/result.json вместо faq.docx",
    )
    args = parser.parse_args()

    items: list[dict] = []
    source = ""

    export_json = EXPORT_DIR / "result.json"
    if args.from_export and export_json.is_file():
        items = parse_faq_export(export_json)
        source = str(export_json)
    elif DOCX_FILE.is_file():
        items = parse_faq_docx(DOCX_FILE)
        source = str(DOCX_FILE)
    elif export_json.is_file():
        items = parse_faq_export(export_json)
        source = str(export_json)

    items = dedupe(items)
    payload = {
        "title": "FAQ EMAR Capital",
        "subtitle": "Частые вопросы и ответы",
        "updated": date.today().isoformat(),
        "source": source,
        "count": len(items),
        "items": items,
    }
    FAQ_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    size_kb = FAQ_FILE.stat().st_size // 1024
    print(f"✅ FAQ: {FAQ_FILE}")
    print(f"   Вопросов: {len(items)} ({size_kb} KB)")
    print(f"   Источник: {source or 'не найден — положите faq.docx в finish/'}")
    if not items:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
