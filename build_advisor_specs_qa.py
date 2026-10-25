#!/usr/bin/env python3
"""
Полные Q&A-карточки советников из Notion markdown (технические параметры + принцип работы).

  cd finish
  python3 build_advisor_specs_qa.py
  # → advisor_specs_qa.txt (подключается в build_database.py)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPORT = ROOT / "resources" / "notion_export"
OUTPUT = ROOT / "advisor_specs_qa.txt"

# Файлы карточек продуктов
_ADVISOR_GLOB = "EMAR_*.md"


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"^[-*]\s+", "", text, flags=re.M)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _product_name(path: Path, body: str) -> str:
    m = re.search(r"^#\s*\*?\*?(.+?)\*?\*?\s*$", body, re.M)
    if m:
        name = _strip_md(m.group(1))
        name = re.sub(r"\s+", " ", name).strip()
        return name
    return path.stem.replace("_", " ")


def _section(body: str, *headers: str) -> str:
    """Вырезает секцию от заголовка до следующего ### или конца."""
    for h in headers:
        pat = rf"###\s*\*?\*?[^\n]*{re.escape(h)}[^\n]*\n(.*?)(?=\n###|\n---|\Z)"
        m = re.search(pat, body, re.I | re.S)
        if m:
            return m.group(1).strip()
    return ""


def _params_as_text(section: str) -> str:
    lines = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith("["):
            continue
        line = _strip_md(line.lstrip("- ").strip())
        if line:
            lines.append(f"• {line}")
    return "\n".join(lines)


def _principle_as_text(section: str) -> str:
    parts: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith("["):
            continue
        line = _strip_md(line.lstrip("- ").strip())
        if line:
            parts.append(line)
    return " ".join(parts)


def build_pairs_for_file(path: Path) -> list[dict]:
    body = path.read_text(encoding="utf-8", errors="ignore")
    name = _product_name(path, body)
    if not name or len(body) < 100:
        return []

    params = _section(body, "Технические параметры", "технические параметры")
    principle = _section(body, "Принцип работы", "принцип работы")
    protection = _section(body, "Система защиты", "система защиты", "преимущества")

    pairs: list[dict] = []

    if params:
        params_text = _params_as_text(params)
        if len(params_text) > 40:
            pairs.append({
                "question": f"Какие технические параметры у {name}?",
                "answer": f"Технические параметры {name}:\n{params_text}",
            })
            pairs.append({
                "question": f"Технические параметры советника {name}",
                "answer": f"Технические параметры {name}:\n{params_text}",
            })
            pairs.append({
                "question": f"{name} депозит лот пары платформа",
                "answer": f"Технические параметры {name}:\n{params_text}",
            })

    if principle:
        ptext = _principle_as_text(principle)
        if len(ptext) > 80:
            pairs.append({
                "question": f"Какой принцип работы у {name}?",
                "answer": ptext,
            })
            pairs.append({
                "question": f"Как работает {name}?",
                "answer": ptext,
            })
            pairs.append({
                "question": f"Что такое {name}?",
                "answer": ptext,
            })
            pairs.append({
                "question": f"{name} это что за бот / советник?",
                "answer": ptext,
            })

    if protection:
        prot = _principle_as_text(protection)
        if len(prot) > 60:
            pairs.append({
                "question": f"Какая система защиты у {name}?",
                "answer": prot,
            })
            pairs.append({
                "question": f"Преимущества {name}",
                "answer": prot,
            })

    # Полная карточка одним блоком — для широких вопросов
    full_parts = []
    if params:
        full_parts.append("Технические параметры:\n" + _params_as_text(params))
    if principle:
        full_parts.append("Принцип работы: " + _principle_as_text(principle))
    if protection:
        full_parts.append("Защита и преимущества: " + _principle_as_text(protection))
    if full_parts:
        full = "\n\n".join(full_parts)
        pairs.append({
            "question": f"Полное описание советника {name}",
            "answer": full[:8000],
        })

    return pairs


def main():
    if not EXPORT.is_dir():
        raise SystemExit(f"Нет папки {EXPORT}")

    all_pairs: list[dict] = []
    files = sorted(EXPORT.glob(_ADVISOR_GLOB))
    # не дублируем огромный EMAR_CAPITAL_Academy.md
    files = [f for f in files if f.name != "EMAR_CAPITAL_Academy.md"]

    for path in files:
        got = build_pairs_for_file(path)
        print(f"  {path.name}: +{len(got)} пар")
        all_pairs.extend(got)

    # дедуп по вопросу
    seen: set[str] = set()
    unique: list[dict] = []
    for p in all_pairs:
        key = re.sub(r"\s+", " ", p["question"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    lines = []
    for p in unique:
        lines.append(f"Вопрос: {p['question']}")
        lines.append(f"Ответ: {p['answer']}")
        lines.append("")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ {len(unique)} пар → {OUTPUT}")


if __name__ == "__main__":
    main()
