#!/usr/bin/env python3
"""
Инкрементальное добавление Q&A в существующую Chroma-коллекцию faq.
НЕ удаляет и НЕ пересобирает базу — только collection.add с новыми ids.

  cd ~/finish   # на VPS
  python3 append_qa_to_db.py notion_hubs_qa.txt
  python3 append_qa_to_db.py notion_hubs_qa.txt --dry-run

Ids: берёт max(числовой id) в коллекции и продолжает (3502 → 3503…).
Пропускает вопросы, чей текст уже есть в metadata.question (нормализованно).
"""
from __future__ import annotations

import argparse
import re
import time
import unicodedata
from pathlib import Path

import chroma_sqlite_fix  # noqa: F401
import chromadb

from ai_utils import get_embeddings_batch
from build_database import load_qa_pairs

DB_PATH = "knowledge_db"
COLLECTION = "faq"
BATCH_SIZE = 32
BATCH_PAUSE = 1.0


def norm_q(q: str) -> str:
    q = unicodedata.normalize("NFKC", q or "").lower()
    q = re.sub(r"[^\w\s]", " ", q, flags=re.UNICODE)
    return re.sub(r"\s+", " ", q).strip()


def max_numeric_id(ids: list[str]) -> int:
    mx = -1
    for i in ids:
        try:
            mx = max(mx, int(i))
        except (TypeError, ValueError):
            continue
    return mx


def existing_questions(collection) -> set[str]:
    data = collection.get(include=["metadatas"])
    out: set[str] = set()
    for meta in data.get("metadatas") or []:
        if not meta:
            continue
        q = meta.get("question") or ""
        key = norm_q(q)
        if key:
            out.add(key)
    return out


def append_file(path: Path, dry_run: bool = False) -> None:
    if not path.is_file():
        raise SystemExit(f"❌ Нет файла: {path}")

    pairs = load_qa_pairs(str(path))
    if not pairs:
        raise SystemExit("❌ В файле нет пар")

    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_collection(COLLECTION)

    all_ids = collection.get(include=[])["ids"]
    start_id = max_numeric_id(all_ids) + 1
    count_before = collection.count()
    print(f"Коллекция {COLLECTION}: count={count_before}, ids={len(all_ids)}, next_id={start_id}")

    have = existing_questions(collection)
    print(f"Уже вопросов в metadata: {len(have)}")

    fresh = []
    for p in pairs:
        key = norm_q(p["question"])
        if not key or key in have:
            continue
        have.add(key)
        fresh.append(p)

    print(f"Из файла: {len(pairs)} | новых (не дубль): {len(fresh)} | пропуск дублей: {len(pairs) - len(fresh)}")
    if not fresh:
        print("Нечего добавлять.")
        return

    if dry_run:
        print("DRY-RUN — примеры новых ids:")
        for i, p in enumerate(fresh[:5]):
            print(f"  id={start_id + i}  Q: {p['question'][:80]}")
        print(f"… всего было бы добавлено: {len(fresh)}")
        return

    i = 0
    while i < len(fresh):
        batch = fresh[i : i + BATCH_SIZE]
        emb = get_embeddings_batch([p["question"] for p in batch])
        ids = [str(start_id + i + j) for j in range(len(batch))]
        collection.add(
            ids=ids,
            embeddings=emb,
            documents=[p["answer"] for p in batch],
            metadatas=[{"question": p["question"]} for p in batch],
        )
        i += len(batch)
        print(f"   +{i}/{len(fresh)} (last id {ids[-1]})")
        if i < len(fresh):
            time.sleep(BATCH_PAUSE)

    print(f"\n✅ Готово. Было count={count_before}, стало count={collection.count()}")
    print(f"   Добавлено {len(fresh)} пар, ids {start_id}…{start_id + len(fresh) - 1}")


def main():
    ap = argparse.ArgumentParser(description="Инкремент Q&A в Chroma faq")
    ap.add_argument("qa_file", type=Path, help="Файл Вопрос:/Ответ: (например notion_hubs_qa.txt)")
    ap.add_argument("--dry-run", action="store_true", help="Только показать, не писать")
    args = ap.parse_args()
    append_file(args.qa_file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
