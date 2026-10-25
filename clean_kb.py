"""Аудит базы знаний ChromaDB. Запуск вручную: python3 clean_kb.py
Ничего не удаляет — только отчёт kb_issues.txt.
"""
from __future__ import annotations

from pathlib import Path

import chromadb

DB_PATH = "knowledge_db"
COLLECTION = "faq"
REPORT = Path("kb_issues.txt")

SITE_MARKERS = (
    "на сайте",
    "на нашем сайте",
    "в разделе вопросов",
    "сайте компании",
)


def _site_hit(doc: str) -> bool:
    low = (doc or "").lower()
    return any(m in low for m in SITE_MARKERS)


def _dup_key(doc: str) -> str:
    return "".join((doc or "").lower().split())


def main() -> None:
    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_collection(COLLECTION)
    data = collection.get(include=["documents", "metadatas"])

    ids = data.get("ids") or []
    docs = data.get("documents") or []

    site_rows: list[tuple[str, str]] = []
    seen_keys: dict[str, str] = {}
    dup_rows: list[tuple[str, str]] = []

    for doc_id, doc in zip(ids, docs):
        text = doc or ""
        if _site_hit(text):
            site_rows.append((doc_id, text[:150]))
        key = _dup_key(text)
        if not key:
            continue
        if key in seen_keys:
            dup_rows.append((doc_id, text[:100]))
        else:
            seen_keys[key] = doc_id

    lines: list[str] = []
    lines.append("ССЫЛКИ НА САЙТ")
    lines.append("=" * 40)
    if not site_rows:
        lines.append("(нет)")
    else:
        for doc_id, preview in site_rows:
            lines.append(f"id={doc_id}")
            lines.append(preview)
            lines.append("")

    lines.append("")
    lines.append("ДУБЛИКАТЫ")
    lines.append("=" * 40)
    if not dup_rows:
        lines.append("(нет)")
    else:
        for doc_id, preview in dup_rows:
            lines.append(f"id={doc_id}")
            lines.append(preview)
            lines.append("")

    lines.append("")
    lines.append("СТАТИСТИКА")
    lines.append("=" * 40)
    lines.append(f"всего: {len(ids)}")
    lines.append(f"с «сайтом»: {len(site_rows)}")
    lines.append(f"дублей: {len(dup_rows)}")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Отчёт записан в {REPORT.resolve()}")
    print(f"всего={len(ids)} сайт={len(site_rows)} дублей={len(dup_rows)}")


if __name__ == "__main__":
    main()
