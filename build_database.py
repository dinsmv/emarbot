from __future__ import annotations

import json
import re
import time
from pathlib import Path

import chroma_sqlite_fix  # noqa: F401
import chromadb
import docx
from ai_utils import get_embeddings_batch

# --- Настройки ---
INPUT_FILE = "extracted_qa.txt"
SUPPLEMENTAL_FILE = "supplemental_qa.txt"
PROMO_VIDEO_QA_FILE = "promo_video_qa.txt"
NOTION_ACADEMY_QA_FILE = "notion_academy_qa.txt"
NOTION_HUBS_QA_FILE = "notion_hubs_qa.txt"
ADVISOR_SPECS_QA_FILE = "advisor_specs_qa.txt"
CRITICAL_QA_FILE = "critical_situation_qa.txt"
CRITICAL_DOCX = Path(__file__).resolve().parent / "Emar. Критическая ситуация.docx"
CRITICAL_DOCX_FALLBACK = Path(__file__).resolve().parent.parent / "Emar. Критическая ситуация.docx"
DB_PATH = "knowledge_db"
DOCX_FILE = "faq.docx"
CHECKPOINT_FILE = "kb_build_checkpoint.json"
BATCH_SIZE = 32
BATCH_PAUSE = 1.0  # сек между пакетами — снижает 429 от Jina


def load_qa_pairs(path):
    print(f"📖 Читаю файл {path}...")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    pairs, question, answer_lines, mode = [], None, [], None

    def save():
        if question and answer_lines:
            ans = " ".join(answer_lines).strip()
            if ans:
                pairs.append({"question": question.strip(), "answer": ans})

    for line in lines:
        s = line.strip()
        if s.startswith("Вопрос:"):
            save()
            question = s.replace("Вопрос:", "").strip()
            answer_lines, mode = [], "q"
        elif s.startswith("Ответ:"):
            answer_lines, mode = [s.replace("Ответ:", "").strip()], "a"
        elif s:
            if mode == "a":
                answer_lines.append(s)
            elif mode == "q":
                question += " " + s
    save()
    print(f"✅ Найдено пар вопрос-ответ: {len(pairs)}")
    return pairs


def load_docx_pairs(path):
    print(f"📖 Читаю файл {path}...")
    doc = docx.Document(path)
    lines = [p.text for p in doc.paragraphs]
    pairs, question, answer_lines, mode = [], None, [], None

    def save():
        if question and answer_lines:
            ans = " ".join(answer_lines).strip()
            if ans:
                pairs.append({"question": question.strip(), "answer": ans})

    for line in lines:
        s = line.strip()
        if s.startswith("Вопрос:"):
            save()
            question = s.replace("Вопрос:", "").strip()
            answer_lines, mode = [], "q"
        elif s.startswith("Ответ:"):
            answer_lines, mode = [s.replace("Ответ:", "").strip()], "a"
        elif s:
            if mode == "a":
                answer_lines.append(s)
            elif mode == "q":
                question += " " + s
    save()
    print(f"✅ Из {path} найдено пар: {len(pairs)}")
    return pairs


def load_checkpoint() -> int:
    p = Path(CHECKPOINT_FILE)
    if p.exists():
        try:
            return int(json.loads(p.read_text()).get("done", 0))
        except Exception:
            pass
    return 0


def save_checkpoint(done: int):
    Path(CHECKPOINT_FILE).write_text(
        json.dumps({"done": done}, ensure_ascii=False),
        encoding="utf-8",
    )


def load_critical_docx(path: Path) -> list[dict]:
    """Критическая ситуация — разбивка по разделам и карточкам советников (без обрезки)."""
    path = CRITICAL_DOCX if CRITICAL_DOCX.is_file() else CRITICAL_DOCX_FALLBACK
    if not path.is_file():
        print(f"   ⚠️  {path.name} не найден — пропуск")
        return []
    print(f"📖 Читаю {path.name} (полная разбивка)...")
    doc = docx.Document(str(path))
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if not paras:
        return []

    def is_advisor_header(t: str) -> bool:
        if not t.startswith("EMAR "):
            return False
        return any(x in t for x in ("Conservative", "Medium", "Aggressive", "Trinity X"))

    sections: list[tuple[str, list[str]]] = []
    cur_title = "intro"
    cur: list[str] = []
    for t in paras:
        if is_advisor_header(t):
            if cur:
                sections.append((cur_title, cur))
            cur_title = re.sub(r"[⭐💰\s]+$", "", t).strip()
            cur = [t]
        else:
            cur.append(t)
    if cur:
        sections.append((cur_title, cur))

    pairs: list[dict] = []
    intro_text = "\n".join(sections[0][1]) if sections else ""
    if intro_text:
        pairs.append({
            "question": "Действия в критической ситуации EMAR Capital",
            "answer": intro_text,
        })
        pairs.append({
            "question": "Что делать в критической ситуации / при критической просадке?",
            "answer": intro_text,
        })

    headings = [
        "Что такое критические показатели?",
        "Как правильно выполнить долив?",
        "Рекомендации по управлению просадкой",
        "Когда можно вывести подушку безопасности?",
        "Что произойдёт, если я не выполню долив?",
    ]
    idxs = sorted(
        (intro_text.find(h), h) for h in headings if intro_text.find(h) >= 0
    )
    for n, (i, h) in enumerate(idxs):
        end = idxs[n + 1][0] if n + 1 < len(idxs) else len(intro_text)
        chunk = intro_text[i:end].strip()
        if not chunk:
            continue
        pairs.append({"question": h.rstrip("?"), "answer": chunk})
        if "правильно выполнить долив" in h:
            pairs.append({
                "question": "Как сделать долив из портфеля роботов / перевод 90% между советниками",
                "answer": chunk,
            })
        if "Рекомендации по управлению просадкой" in h:
            pairs.append({
                "question": "Рекомендации по управлению просадкой 0-20 20-30 долив 50%",
                "answer": chunk,
            })
        if "вывести подушку" in h:
            pairs.append({
                "question": "Когда можно вывести подушку безопасности / долив",
                "answer": chunk,
            })
        if "не выполню долив" in h:
            pairs.append({
                "question": "Что будет если не сделать долив",
                "answer": chunk,
            })

    for title, lines in sections[1:]:
        body = "\n".join(lines)
        pairs.append({
            "question": f"Полное описание советника {title} из файла критической ситуации",
            "answer": body,
        })
        pairs.append({
            "question": f"{title} технические параметры и принцип работы",
            "answer": body,
        })
        pairs.append({
            "question": f"Что такое {title}?",
            "answer": body,
        })

    print(f"✅ Из критической ситуации: {len(pairs)} пар(ы)")
    return pairs


def build_db():
    pairs = load_qa_pairs(INPUT_FILE)
    pairs += load_docx_pairs(DOCX_FILE)
    if Path(SUPPLEMENTAL_FILE).is_file():
        pairs += load_qa_pairs(SUPPLEMENTAL_FILE)
    if Path(PROMO_VIDEO_QA_FILE).is_file():
        pairs += load_qa_pairs(PROMO_VIDEO_QA_FILE)
    if Path(NOTION_ACADEMY_QA_FILE).is_file():
        pairs += load_qa_pairs(NOTION_ACADEMY_QA_FILE)
    if Path(NOTION_HUBS_QA_FILE).is_file():
        pairs += load_qa_pairs(NOTION_HUBS_QA_FILE)
    if Path(ADVISOR_SPECS_QA_FILE).is_file():
        pairs += load_qa_pairs(ADVISOR_SPECS_QA_FILE)
    # Полный критический DOCX (без обрезки). Файл critical_situation_qa.txt — зеркало для аудита.
    if Path(CRITICAL_QA_FILE).is_file():
        pairs += load_qa_pairs(CRITICAL_QA_FILE)
    else:
        pairs += load_critical_docx(
            CRITICAL_DOCX if CRITICAL_DOCX.is_file() else CRITICAL_DOCX_FALLBACK
        )

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        total_q = f.read().count("Вопрос:")
    unique = len(set(p["question"] for p in pairs))
    print(f"🔎 Всего 'Вопрос:' в файле: {total_q}")
    print(f"🔎 Распознано пар: {len(pairs)} | Уникальных: {unique} | Дублей: {len(pairs) - unique}")

    if not pairs:
        print("❌ Не найдено ни одной пары!")
        return

    start_idx = load_checkpoint()
    client = chromadb.PersistentClient(path=DB_PATH)

    if start_idx > 0:
        print(f"▶ Продолжаю с записи {start_idx} (чекпоинт)")
        try:
            collection = client.get_collection("faq")
        except Exception:
            print("   Коллекция не найдена — начинаю с нуля")
            start_idx = 0
            collection = None
    else:
        collection = None

    if collection is None:
        print("🗄️  Создаю базу данных...")
        try:
            client.delete_collection("faq")
        except Exception:
            pass
        collection = client.create_collection("faq", metadata={"hnsw:space": "cosine"})

    total = len(pairs)
    print(f"🧠 Эмбеддинги Jina (пакетами по {BATCH_SIZE}, с {start_idx} до {total})...")

    i = start_idx
    while i < total:
        batch = pairs[i : i + BATCH_SIZE]
        questions = [p["question"] for p in batch]
        embeddings = get_embeddings_batch(questions)

        collection.add(
            ids=[str(j) for j in range(i, i + len(batch))],
            embeddings=embeddings,
            documents=[p["answer"] for p in batch],
            metadatas=[{"question": p["question"]} for p in batch],
        )

        i += len(batch)
        save_checkpoint(i)
        print(f"   Обработано {i} из {total}...")
        if i < total:
            time.sleep(BATCH_PAUSE)

    Path(CHECKPOINT_FILE).unlink(missing_ok=True)
    print(f"\n✅ ГОТОВО! База знаний: {total} пар.")
    print(f"📂 Сохранена в: {DB_PATH}")


if __name__ == "__main__":
    build_db()
