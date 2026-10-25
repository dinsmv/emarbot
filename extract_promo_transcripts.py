#!/usr/bin/env python3
"""
Извлечение пар «вопрос → ответ» из транскрипций промо-видео (docx).

Источник: «часть 4  report.docx» и другие файлы HypeScribe с расшифровками.

Пайплайн (как для all_conversations.docx):
  1. Чтение docx → текст с метаданными видео
  2. Разбивка на фрагменты с перекрытием
  3. Groq извлекает Q&A из каждого фрагмента
  4. Дедупликация + сохранение в promo_video_qa.txt
  5. (опционально) пересборка Chroma через build_database.py

Примеры:
  python3 extract_promo_transcripts.py --sample 2
  python3 extract_promo_transcripts.py
  python3 extract_promo_transcripts.py --fresh
  python3 extract_promo_transcripts.py --rebuild-db
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path

import docx
from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

for env_path in (ROOT / ".env", PROJECT_ROOT / ".env"):
    if env_path.is_file():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_INPUT = PROJECT_ROOT / "часть 4  report.docx"
OUTPUT_FILE = ROOT / "promo_video_qa.txt"
CHECKPOINT_FILE = ROOT / "promo_extract_checkpoint.json"

CHUNK_SIZE = 6500
CHUNK_OVERLAP = 500
CHUNK_PAUSE = 1.2
MAX_TOKENS = 3500

EXTRACT_SYSTEM = """Ты — эксперт по базе знаний техподдержки EMAR Capital (торговые советники на Forex).
Извлекай максимум полезных фактов из транскрипции видео/вебинара для бота поддержки."""

EXTRACT_USER = """Фрагмент транскрипции (видео: {video_title}, часть {chunk_no}/{chunk_total}):

---
{chunk}
---

Извлеки ВСЕ полезные сведения для клиентов EMAR Capital в формате:

Вопрос: <как спросил бы клиент>
Ответ: <конкретный ответ: шаги, цифры, названия>

Обязательно не пропускай темы, если они есть в тексте:
• торговые советники Trinity, King, Classic (агрессивность, доходность, риски)
• что такое робот/советник, как работает
• MoniTrading (сервис мониторинга; НЕ пиши FXmonitor)
• регистрация брокера RoboForex / Forex4You, пополнение, вывод USDT
• VPS / GOVPSFX, установка советника
• просадка, сушка, долив, критические ситуации
• торговый баланс, центовые счета, плечо 1:1000
• партнёрская программа, маркетинг-план

Правила:
- Один факт = одна пара (или логически связанная группа шагов)
- Не выдумывай то, чего нет во фрагменте
- Пиши только на русском
- Компания называется EMAR Capital (в тексте может быть Mr Capital — пиши EMAR Capital)
- Не добавляй комментарии «нет информации о…», списки пропущенных тем и примечания
- Если полезного контента нет — ответь ровно: НЕТ"""


def norm_question(q: str) -> str:
    q = unicodedata.normalize("NFKC", q or "").lower()
    q = re.sub(r"[^\w\s]", " ", q, flags=re.UNICODE)
    return re.sub(r"\s+", " ", q).strip()


def clean_answer(text: str) -> str:
    text = re.sub(r"\s*НЕТ информации о:.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\s*-\s*MoniTrading.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\s*-\s*торговых советниках.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\bMr Capital\b", "EMAR Capital", text, flags=re.IGNORECASE)
    text = re.sub(r"FX\s*Monitor", "MoniTrading", text, flags=re.IGNORECASE)
    text = re.sub(r"FXmonitor", "MoniTrading", text, flags=re.IGNORECASE)
    text = re.sub(r"FxMonitor", "MoniTrading", text, flags=re.IGNORECASE)
    text = re.sub(r"^НЕТ\s*[\(\[].*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def clean_question(text: str) -> str:
    text = clean_answer(text)
    return text.strip()


def parse_qa_text(text: str) -> list[dict]:
    pairs: list[dict] = []
    question, answer_lines = None, []

    def flush():
        nonlocal question, answer_lines
        if question and answer_lines:
            ans = clean_answer(" ".join(answer_lines).strip())
            if ans and ans.upper() != "НЕТ" and len(ans) > 15:
                pairs.append({"question": clean_question(question), "answer": ans})
        question, answer_lines = None, []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Вопрос:"):
            flush()
            question = line.replace("Вопрос:", "", 1).strip()
        elif line.startswith("Ответ:"):
            answer_lines = [line.replace("Ответ:", "", 1).strip()]
        elif question is not None:
            if answer_lines:
                answer_lines.append(line)
            else:
                question += " " + line
    flush()
    return pairs


def load_docx_text(path: Path) -> tuple[str, str]:
    doc = docx.Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        return path.stem, ""

    video_title = paragraphs[0]
    # Пропускаем шапку HypeScribe до Overview или первой реплики [00:
    start = 0
    for i, p in enumerate(paragraphs):
        if p.startswith("Overview:") or re.match(r"^\[\d", p):
            start = i
            break
    body = "\n".join(paragraphs[start:])
    return video_title, body


def split_chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            if cut > start:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.is_file():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done_chunks": [], "pairs": [], "source": ""}


def save_checkpoint(data: dict):
    CHECKPOINT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_groq_wait(err: str) -> int | None:
    m = re.search(r"try again in (\d+)m([\d.]+)s", err)
    if m:
        return int(m.group(1)) * 60 + int(float(m.group(2))) + 1
    m = re.search(r"try again in ([\d.]+)s", err)
    if m:
        return int(float(m.group(1))) + 1
    return None


def call_groq(client: Groq, system: str, user: str, temperature: float = 0.15) -> str:
    for attempt in range(8):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=MAX_TOKENS,
            )
            return (completion.choices[0].message.content or "").strip()
        except Exception as e:
            err = str(e)
            wait = _parse_groq_wait(err)
            if wait and attempt < 7:
                print(f"   ⏳ Rate limit, жду {wait}с...")
                time.sleep(wait)
                continue
            raise
    return ""


def load_pairs_from_file(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    pairs: list[dict] = []
    question, answer_lines = None, []

    def flush():
        nonlocal question, answer_lines
        if question and answer_lines:
            q = clean_question(question.strip())
            ans = clean_answer(" ".join(answer_lines).strip())
            if q and ans and ans.upper() != "НЕТ" and len(ans) > 15:
                pairs.append({"question": q, "answer": ans})
        question, answer_lines = None, []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Вопрос:"):
            flush()
            question = line.replace("Вопрос:", "", 1).strip()
        elif line.startswith("Ответ:"):
            answer_lines = [line.replace("Ответ:", "", 1).strip()]
        elif question is not None and answer_lines:
            answer_lines.append(line)
    flush()
    return pairs


def extract_single_chunk(
    path: Path,
    client: Groq,
    chunk_index: int,
) -> list[dict]:
    video_title, body = load_docx_text(path)
    chunks = split_chunks(body)
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise SystemExit(f"❌ chunk_index должен быть 0..{len(chunks) - 1}")
    chunk = chunks[chunk_index]
    print(f"📄 {path.name} — только фрагмент {chunk_index + 1}/{len(chunks)}", flush=True)
    user_prompt = EXTRACT_USER.format(
        video_title=video_title,
        chunk_no=chunk_index + 1,
        chunk_total=len(chunks),
        chunk=chunk,
    )
    result = call_groq(client, EXTRACT_SYSTEM, user_prompt)
    if result.upper() == "НЕТ" or "Вопрос:" not in result:
        print("   (нет пар в фрагменте)")
        return []
    pairs = parse_qa_text(result)
    print(f"   +{len(pairs)} пар из фрагмента")
    return pairs


def dedupe_pairs(pairs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for p in pairs:
        key = norm_question(p["question"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def format_pairs(pairs: list[dict]) -> str:
    blocks = []
    for p in pairs:
        blocks.append(f"Вопрос: {p['question']}\nОтвет: {p['answer']}\n")
    return "\n".join(blocks)


def extract_from_docx(
    path: Path,
    client: Groq,
    sample: int | None = None,
    resume: bool = True,
) -> list[dict]:
    video_title, body = load_docx_text(path)
    if not body:
        print(f"⚠️  Пустой текст: {path}")
        return []

    chunks = split_chunks(body)
    print(f"📄 {path.name}")
    print(f"   Видео: {video_title}")
    print(f"   Символов: {len(body):,} | Фрагментов: {len(chunks)}")

    checkpoint = load_checkpoint() if resume else {"done_chunks": [], "pairs": [], "source": ""}
    if checkpoint.get("source") != str(path):
        checkpoint = {"done_chunks": [], "pairs": [], "source": str(path)}

    done = set(checkpoint.get("done_chunks", []))
    all_pairs = list(checkpoint.get("pairs", []))
    target = chunks[:sample] if sample else chunks

    for i, chunk in enumerate(target):
        if i in done:
            continue
        print(f"   🧠 Фрагмент {i + 1}/{len(target)}...", flush=True)
        user_prompt = EXTRACT_USER.format(
            video_title=video_title,
            chunk_no=i + 1,
            chunk_total=len(target),
            chunk=chunk,
        )
        try:
            result = call_groq(client, EXTRACT_SYSTEM, user_prompt)
        except Exception as e:
            save_checkpoint(checkpoint)
            raise RuntimeError(f"Ошибка на фрагменте {i}: {e}") from e

        if result.upper() != "НЕТ" and "Вопрос:" in result:
            new_pairs = parse_qa_text(result)
            all_pairs.extend(new_pairs)
            print(f"      +{len(new_pairs)} пар (всего {len(all_pairs)})")
        else:
            print("      (нет пар)")

        done.add(i)
        checkpoint["done_chunks"] = sorted(done)
        checkpoint["pairs"] = all_pairs
        save_checkpoint(checkpoint)
        if i + 1 < len(target):
            time.sleep(CHUNK_PAUSE)

    return dedupe_pairs(all_pairs)


def main():
    parser = argparse.ArgumentParser(description="Извлечение Q&A из транскрипций промо-видео")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Путь к docx с транскрипцией",
    )
    parser.add_argument("--sample", type=int, help="Обработать только N фрагментов (тест)")
    parser.add_argument("--fresh", action="store_true", help="Начать с нуля (без checkpoint)")
    parser.add_argument("--rebuild-db", action="store_true", help="Пересобрать Chroma после извлечения")
    parser.add_argument(
        "--finalize-checkpoint",
        action="store_true",
        help="Сохранить результат из checkpoint без повторного вызова API",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Почистить promo_video_qa.txt без вызова API",
    )
    parser.add_argument(
        "--only-chunk",
        type=int,
        metavar="N",
        help="Обработать только фрагмент N (нумерация с 0) и добавить к файлу",
    )
    args = parser.parse_args()

    if args.clean_only:
        pairs = dedupe_pairs(load_pairs_from_file(OUTPUT_FILE))
        OUTPUT_FILE.write_text(format_pairs(pairs), encoding="utf-8")
        print(f"✅ Почищено: {len(pairs)} пар → {OUTPUT_FILE}")
        return

    if args.only_chunk is not None:
        if not args.input.is_file():
            raise SystemExit(f"❌ Файл не найден: {args.input}")
        import os
        if not os.getenv("GROQ_API_KEY"):
            raise SystemExit("❌ GROQ_API_KEY не задан в .env")
        client = Groq()
        new_pairs = extract_single_chunk(args.input, client, args.only_chunk)
        existing = load_pairs_from_file(OUTPUT_FILE)
        merged = dedupe_pairs(existing + new_pairs)
        OUTPUT_FILE.write_text(format_pairs(merged), encoding="utf-8")
        print(f"\n✅ Итого {len(merged)} пар (+{len(new_pairs)} новых) → {OUTPUT_FILE}")
        return

    if args.finalize_checkpoint:
        checkpoint = load_checkpoint()
        pairs = dedupe_pairs(checkpoint.get("pairs", []))
        if not pairs:
            raise SystemExit("❌ Checkpoint пуст — нечего сохранять")
        OUTPUT_FILE.write_text(format_pairs(pairs), encoding="utf-8")
        CHECKPOINT_FILE.unlink(missing_ok=True)
        print(f"✅ Из checkpoint: {len(pairs)} пар → {OUTPUT_FILE}")
        if args.rebuild_db:
            print("\n🗄️  Пересборка базы знаний...")
            import build_database
            build_database.build_db()
        return

    if not args.input.is_file():
        raise SystemExit(f"❌ Файл не найден: {args.input}")

    import os
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("❌ GROQ_API_KEY не задан в .env")

    if args.fresh:
        CHECKPOINT_FILE.unlink(missing_ok=True)

    client = Groq()
    pairs = extract_from_docx(
        args.input,
        client,
        sample=args.sample,
        resume=not args.fresh,
    )

    OUTPUT_FILE.write_text(format_pairs(pairs), encoding="utf-8")
    CHECKPOINT_FILE.unlink(missing_ok=True)
    print(f"\n✅ Сохранено {len(pairs)} уникальных пар → {OUTPUT_FILE}")

    if args.rebuild_db:
        print("\n🗄️  Пересборка базы знаний...")
        import build_database
        build_database.build_db()


if __name__ == "__main__":
    main()
