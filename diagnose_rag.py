#!/usr/bin/env python3
"""Диагностика RAG на VPS: cd ~/finish && python3 diagnose_rag.py"""
from __future__ import annotations

import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import chroma_sqlite_fix  # noqa: F401
import chromadb
from dotenv import load_dotenv

load_dotenv()

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "что такое торговые советники?"

print("=" * 60)
print("EMAR Bot — диагностика RAG")
print("=" * 60)

# 1. Версия ai_utils
print("\n▶ 1. Версия ai_utils.py")
with open("ai_utils.py", encoding="utf-8") as f:
    src = f.read()
if "synthesis pass 2" in src:
    print("   ✅ Двухпроходная логика (pass 2) — ЕСТЬ")
else:
    print("   ❌ СТАРЫЙ ai_utils — нет synthesis pass 2")
    print("      → залейте: scp finish/ai_utils.py root@VPS:~/finish/")

# 2. API ключи
print("\n▶ 2. API ключи в .env")
for key in ("GROQ_API_KEY", "JINA_API_KEY", "TELEGRAM_TOKEN"):
    val = os.getenv(key, "")
    print(f"   {key}: {'✅ задан (' + val[:8] + '...)' if val else '❌ ПУСТО'}")

test_mode = os.getenv("DISABLE_OPERATOR_ESCALATION", "")
print(f"   DISABLE_OPERATOR_ESCALATION: {test_mode or '(выкл)'}")

# 3. База знаний
print("\n▶ 3. База знаний (knowledge_db)")
try:
    client = chromadb.PersistentClient(path="knowledge_db")
    col = client.get_collection("faq")
    count = col.count()
    print(f"   ✅ Коллекция faq: {count} записей")
except Exception as e:
    print(f"   ❌ Ошибка knowledge_db: {e}")
    sys.exit(1)

# 4. Поиск (Jina + Chroma)
print(f"\n▶ 4. Поиск по вопросу: «{QUESTION}»")
try:
    from ai_utils import get_embedding

    emb = get_embedding(QUESTION)
    print(f"   ✅ Jina embedding: {len(emb)} dims")

    results = col.query(
        query_embeddings=[emb],
        n_results=5,
        include=["documents", "metadatas", "distances"],
    )
    if not results["documents"] or not results["documents"][0]:
        print("   ❌ Поиск вернул 0 фрагментов → not_found")
        sys.exit(1)

    POROG = 0.5
    fragments = []
    for i in range(len(results["documents"][0])):
        d = results["distances"][0][i]
        meta = results["metadatas"][0][i] or {}
        q = meta.get("question", "")[:70]
        mark = "✅" if d <= POROG else "⛔"
        print(f"   {mark} distance={d:.3f}  «{q}»")
        if d <= POROG:
            fragments.append({
                "question": meta.get("question", ""),
                "answer": results["documents"][0][i],
                "distance": d,
            })

    if not fragments:
        print(f"   ❌ Все фрагменты хуже порога {POROG} → not_found")
        sys.exit(1)
    print(f"   ✅ Подходящих фрагментов: {len(fragments)}")
except Exception as e:
    print(f"   ❌ Ошибка поиска: {e}")
    sys.exit(1)

# 5. Генерация ответа (Groq)
print("\n▶ 5. Генерация ответа (Groq)")
try:
    from ai_utils import generate_rag_answer, _call_groq, SYSTEM_PROMPT, SYNTHESIS_PROMPT, _build_user_prompt, _is_escalate

    user_prompt = _build_user_prompt(QUESTION, fragments)

    ans1 = _call_groq(SYSTEM_PROMPT, user_prompt)
    if _is_escalate(ans1):
        print("   pass 1: ❌ отказ или пусто")
        if ans1:
            print(f"            ответ: {ans1[:120]}")
    else:
        print(f"   pass 1: ✅ {ans1[:200]}...")

    ans2 = _call_groq(SYNTHESIS_PROMPT, user_prompt, temperature=0.15)
    if _is_escalate(ans2):
        print("   pass 2: ❌ отказ или пусто")
        if ans2:
            print(f"            ответ: {ans2[:120]}")
    else:
        print(f"   pass 2: ✅ {ans2[:200]}...")

    final = generate_rag_answer(QUESTION, fragments)
    if final:
        print(f"\n   ✅ ИТОГ: бот должен ответить:\n   {final[:400]}")
    else:
        print("\n   ❌ ИТОГ: generate_rag_answer → None → «не уверен в ответе»")
        print("      Причина: Groq отказал на обоих проходах ИЛИ старый ai_utils.py")
except Exception as e:
    print(f"   ❌ Ошибка Groq: {e}")

print("\n" + "=" * 60)
