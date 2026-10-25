#!/usr/bin/env python3
"""
Извлечение Q&A из экспорта Notion (EMAR CAPITAL Academy).

Шаг 1 — скачать сайт (если нет Export):
  python3 fetch_notion_site.py

Шаг 1 (альтернатива) — в Notion: ⋯ → Export → Markdown & CSV, включить подстраницы.
  Распаковать ZIP в finish/resources/notion_export/

Шаг 2 — запуск:
  cd finish
  python3 extract_notion_academy.py
  python3 extract_notion_academy.py --sample 2   # тест
  python3 build_database.py                      # пересборка базы

Результат: notion_academy_qa.txt → подключается в build_database.py
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
EXPORT_DIR = ROOT / "resources" / "notion_export"
OUTPUT_FILE = ROOT / "notion_academy_qa.txt"
CHECKPOINT_FILE = ROOT / "notion_extract_checkpoint.json"

for env_path in (ROOT / ".env", PROJECT_ROOT / ".env"):
    if env_path.is_file():
        load_dotenv(env_path)
        break

GROQ_MODEL = "llama-3.3-70b-versatile"
CHUNK_SIZE = 6000
CHUNK_OVERLAP = 400
CHUNK_PAUSE = 1.2
MAX_TOKENS = 3500

EXTRACT_SYSTEM = """Ты — эксперт по базе знаний EMAR Capital Academy.
Извлекай факты для бота техподдержки из официальных материалов академии."""

EXTRACT_USER = """Раздел академии: {page_title}
Фрагмент {chunk_no}/{chunk_total}:

---
{chunk}
---

Извлеки ВСЕ полезные сведения в формате:

Вопрос: <как спросил бы клиент>
Ответ: <конкретный ответ: шаги, цифры, названия>

Темы (если есть в тексте): знакомство с компанией, основные понятия, критическая ситуация,
Classic / King / Trinity, Forex4You (регистрация, верификация, счёт, пополнение, вывод),
MoniTrading, VPS, просадка, сушка, долив.

Правила:
- Не выдумывай
- MoniTrading, не FXmonitor
- EMAR Capital
- Пиши только на русском
- Если контента нет — ответь: НЕТ"""


def norm_question(q: str) -> str:
    q = unicodedata.normalize("NFKC", q or "").lower()
    q = re.sub(r"[^\w\s]", " ", q, flags=re.UNICODE)
    return re.sub(r"\s+", " ", q).strip()


def clean_answer(text: str) -> str:
    text = re.sub(r"\s*НЕТ информации о:.*", "", text, flags=re.I | re.S)
    text = re.sub(r"\bFX\s*Monitor\b", "MoniTrading", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def parse_qa_text(text: str) -> list[dict]:
    pairs: list[dict] = []
    question, answer_lines = None, []

    def flush():
        nonlocal question, answer_lines
        if question and answer_lines:
            ans = clean_answer(" ".join(answer_lines).strip())
            if ans and ans.upper() != "НЕТ" and len(ans) > 15:
                pairs.append({"question": question.strip(), "answer": ans})
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
    flush()
    return pairs


def page_title_from_path(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if len(parts) > 1:
        return " / ".join(p.replace(".md", "").replace("_", " ") for p in parts[:-1] + [parts[-1]])
    return path.stem.replace("_", " ")


def load_markdown_pages(export_dir: Path) -> list[tuple[str, str]]:
    pages: list[tuple[str, str]] = []
    skip_names = {"EMAR_CAPITAL_Academy.md"}  # дубликат всего сайта, контент в подстраницах
    for path in sorted(export_dir.rglob("*.md")):
        if path.name in skip_names or path.name.lower() in ("readme.md",):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if len(text) < 80:
            continue
        title = page_title_from_path(path, export_dir)
        pages.append((title, text))
    return pages


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


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.is_file():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": [], "pairs": []}


def save_checkpoint(data: dict):
    CHECKPOINT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_retry_seconds(err: str) -> int | None:
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", err, re.I)
    if m:
        mins = int(m.group(1) or 0)
        secs = float(m.group(2) or 0)
        return int(mins * 60 + secs) + 2
    m = re.search(r"try again in ([\d.]+)s", err)
    if m:
        return int(float(m.group(1))) + 1
    return None


def call_groq(client: Groq, system: str, user: str) -> str:
    for attempt in range(12):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.15,
                max_tokens=MAX_TOKENS,
            )
            return (completion.choices[0].message.content or "").strip()
        except Exception as e:
            err = str(e)
            wait = _parse_retry_seconds(err)
            if wait and attempt < 11:
                print(f"   ⏳ Rate limit, жду {wait}с...", flush=True)
                time.sleep(wait)
                continue
            if attempt >= 11 or "403" in err or "Forbidden" in err:
                raise RuntimeError(f"Groq недоступен: {err}") from e
            raise
    return ""


def dedupe_pairs(pairs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for p in pairs:
        key = norm_question(p["question"])
        if key and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def strip_md(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s{2,}", " ", text).strip()


def extract_heuristic_pairs(page_title: str, text: str) -> list[dict]:
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
        question = heading if "?" in heading else f"{heading} ({page_title})"
        pairs.append({"question": question, "answer": content[:2500]})

    for m in re.finditer(r"^-\s+(.+?)\n((?:    .+\n?)+)", body, re.MULTILINE):
        title = strip_md(m.group(1))
        content = strip_md(m.group(2))
        if len(content) >= 40 and len(title) >= 3:
            pairs.append({"question": title, "answer": content[:2500]})

    for m in re.finditer(r"\*\*(.+?\?)\*\*\s*\n+(.+?)(?=\n(?:#{1,4}|\*\*|---|\Z))", body, re.S):
        question = strip_md(m.group(1))
        content = strip_md(m.group(2))
        if len(content) >= 40:
            pairs.append({"question": question, "answer": content[:2500]})

    return pairs


def heuristic_fill(pages: list[tuple[str, str]]) -> list[dict]:
    pairs: list[dict] = []
    for title, body in pages:
        got = extract_heuristic_pairs(title, body)
        pairs.extend(got)
        print(f"   📄 {title[:50]}: +{len(got)} пар")
    return pairs


def finalize_output(pairs: list[dict], rebuild_db: bool = False):
    pairs = dedupe_pairs(pairs)
    OUTPUT_FILE.write_text(format_pairs(pairs), encoding="utf-8")
    CHECKPOINT_FILE.unlink(missing_ok=True)
    print(f"\n✅ {len(pairs)} пар → {OUTPUT_FILE}")
    if rebuild_db:
        import build_database

        build_database.build_db()


def format_pairs(pairs: list[dict]) -> str:
    return "\n".join(f"Вопрос: {p['question']}\nОтвет: {p['answer']}\n" for p in pairs)


def main():
    parser = argparse.ArgumentParser(description="Q&A из экспорта Notion Academy")
    parser.add_argument("--input", type=Path, default=EXPORT_DIR)
    parser.add_argument("--sample", type=int, help="Только N фрагментов (тест)")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--rebuild-db", action="store_true")
    parser.add_argument(
        "--heuristic-fill",
        action="store_true",
        help="Добавить Q&A эвристикой из markdown (без Groq)",
    )
    parser.add_argument(
        "--finalize-checkpoint",
        action="store_true",
        help="Записать результат из checkpoint + heuristic-fill",
    )
    args = parser.parse_args()

    if not args.input.is_dir():
        raise SystemExit(
            f"❌ Папка не найдена: {args.input}\n"
            "Экспортируйте Notion → Markdown & CSV и распакуйте сюда."
        )

    pages = load_markdown_pages(args.input)
    if not pages:
        raise SystemExit(f"❌ Нет .md файлов в {args.input}")

    if args.finalize_checkpoint:
        cp = load_checkpoint()
        all_pairs = list(cp.get("pairs", []))
        print(f"📦 Из checkpoint: {len(all_pairs)} пар")
        if args.heuristic_fill or not all_pairs:
            print("📄 Эвристика по markdown...")
            all_pairs.extend(heuristic_fill(pages))
        finalize_output(all_pairs, rebuild_db=args.rebuild_db)
        return

    if args.heuristic_fill and not args.sample:
        print(f"📚 Страниц: {len(pages)} | режим: эвристика")
        pairs = heuristic_fill(pages)
        finalize_output(pairs, rebuild_db=args.rebuild_db)
        return

    tasks: list[tuple[str, str, int, int]] = []
    for title, body in pages:
        chunks = split_chunks(body)
        for i, chunk in enumerate(chunks):
            tasks.append((title, chunk, i + 1, len(chunks)))

    print(f"📚 Страниц: {len(pages)} | Фрагментов: {len(tasks)}")

    import os
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("❌ GROQ_API_KEY не задан в .env")

    if args.fresh:
        CHECKPOINT_FILE.unlink(missing_ok=True)

    cp = load_checkpoint()
    done = set(cp.get("done", []))
    all_pairs = list(cp.get("pairs", []))

    client = Groq()
    target = tasks[: args.sample] if args.sample else tasks

    for idx, (title, chunk, cno, ctotal) in enumerate(target):
        key = f"{title}|{cno}/{ctotal}"
        if key in done:
            continue
        print(f"   🧠 [{idx + 1}/{len(target)}] {title[:50]}...", flush=True)
        user = EXTRACT_USER.format(page_title=title, chunk_no=cno, chunk_total=ctotal, chunk=chunk)
        try:
            result = call_groq(client, EXTRACT_SYSTEM, user)
        except RuntimeError as e:
            print(f"   ⚠️  {e}")
            print("   📄 Добираем эвристикой + checkpoint...")
            cp = {"done": sorted(done), "pairs": all_pairs}
            save_checkpoint(cp)
            rest_pairs = heuristic_fill(pages)
            finalize_output(all_pairs + rest_pairs, rebuild_db=args.rebuild_db)
            return
        if result.upper() != "НЕТ" and "Вопрос:" in result:
            new = parse_qa_text(result)
            all_pairs.extend(new)
            print(f"      +{len(new)} пар (всего {len(all_pairs)})")
        done.add(key)
        cp = {"done": sorted(done), "pairs": all_pairs}
        save_checkpoint(cp)
        if idx + 1 < len(target):
            time.sleep(CHUNK_PAUSE)

    finalize_output(all_pairs, rebuild_db=args.rebuild_db)


if __name__ == "__main__":
    main()
