#!/usr/bin/env python3
"""
Сборка resources.json без ссылок на канал «Промо Материалы».

Видео-инструкции: текст поста + ссылки YouTube/RuTube из экспорта.
PDF/фото/аудио: локальные файлы в resources/files/.
Инфо-посты (Cardex, мониторинги, эмодзи…): текст из экспорта.

Запуск из finish/:
  python3 resources/build_catalog.py
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES_DIR = ROOT / "resources"
FILES_DIR = RES_DIR / "files"
CATALOG = RES_DIR / "resources.json"
EXPORT_DIR = RES_DIR / "promo_export"

ICONS = {
    "links": "🔗",
    "instructions": "📋",
    "documents": "📄",
    "video": "🎬",
    "info": "ℹ️",
    "other": "📎",
}
TITLES = {
    "links": "Полезные ссылки",
    "instructions": "Инструкции",
    "documents": "PDF и документы",
    "video": "Видео",
    "info": "Полезная информация",
    "other": "Шаблоны и прочее",
}

STORIES_INVITE = "https://t.me/+RIcXuIFtSro0OGIy"

# Название в каталоге → локальный файл (если есть)
LOCAL_FILES: dict[str, str] = {
    "условные обозначения валютной пары monitrading": "monitrading-pair-legend.png",
    "условные обозначения валютной пары fxmonitor": "monitrading-pair-legend.png",
    "как поделиться мониторингом": "how-to-share-monitoring.jpg",
    "какую ссылку выбрать": "какую ссылку выбрать.jpeg",
    "краткий обзор monitrading": "Краткий обзор FXmonitor.mp4",
    "краткий обзор fxmonitor": "Краткий обзор FXmonitor.mp4",
    "маркетнг план forex4you": "Маркетнг план Forex4You.pdf",
    "партнерская программа forex4you": "Маркетнг план Forex4You.pdf",
    "партнерская программа roboforex": "Партнерская программа RoboForex.pdf",
    "звук денег для уведомлений": "Звук денег.mp3",
}

# Видео без YouTube/RuTube — только локальный файл
LOCAL_VIDEO_FILES = {
    "Краткий обзор MoniTrading",
}

# Убрано из каталога
REMOVED_TITLES = {
    "Официальная презентация EMAR CAPITAL",
    "Презентация торговых советников KING",
    "Презентация новейших технологий EMAR CAPITAL",
}

TITLE_MSG_IDS: dict[str, int] = {
    "Forex4You: регистрация, открытие счета и пополнение": 37,
    "Регистрация на брокере FOREX4YOU": 37,
    "Пополнение брокера FOREX4YOU": 38,
    "Регистрация на брокере ROBOFOREX": 39,
    "Пополнение брокера ROBOFOREX": 46,
    "Регистрация и аренда сервера GOVPSFX": 41,
    "Как зайти на VPS сервер": 42,
    "MoniTrading: Регистрация и обзор": 43,
    "Регистрация мониторинга MoniTrading": 43,
    "Краткий обзор MoniTrading": 30,
    "Как поставить советники на сушку": 45,
    "Презентация торговых советников KING": 40,
    "Презентация новейших технологий EMAR CAPITAL": 44,
}

VIDEO_TITLES = [t for t in TITLE_MSG_IDS if t not in REMOVED_TITLES]

FILE_TITLES = [
    ("Условные обозначения валютной пары MoniTrading", "photo"),
    ("Как поделиться мониторингом", "photo"),
    ("Партнерская программа RoboForex", "pdf"),
    ("Партнерская программа Forex4You", "pdf"),
    ("Звук Денег для уведомлений", "audio"),
]

INFO_ITEMS = [
    ("Маркетинг план компании EMAR CAPITAL", 15),
    ("Набор эмодзи Emar Capital для статуса Telegram", 33),
    ("Обменник USDT — Cardex", 34),
    ("Ссылки на мониторинги компании (TRINITY / KING / CLASSIC)", 36),
]

INFO_TEXT_OVERRIDES: dict[str, str] = {
    "Ссылки на мониторинги компании (TRINITY / KING / CLASSIC)": (
        "Ссылки на мониторинги компании:\n\nTRINITY\n\n1 — TRINITY AGGRESSIVE\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--trinity/11930211\n\n- Мониторинг MoniTrading - https://monitrading.online/s/TIpfHL?account=afa268d70c9e6\n\n2 — TRINITY MEDIUM\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--trinity-m/11930255\n\n- Мониторинг MoniTrading - https://monitrading.online/s/se8dzU?account=a8f98d1b725aa\n\n3 — TRINITY CONSERVATIVE\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--trinity-k/11930259\n\n- Мониторинг MoniTrading - https://monitrading.online/s/WYPHyP?account=a6f467a8c1f7f\n\nKING\n\n1 — KING AGGRESSIVE\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--king-aggressive/11930194\n\n- Мониторинг MoniTrading - https://monitrading.online/s/BfQijj?account=a132f519f772e\n\n2 — KING MEDIUM\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--king-medium/11930201\n\n- Мониторинг MoniTrading - https://monitrading.online/s/tCBuIi?account=a2d4533dc9da2\n\n3 — KING CONSERVATIVE\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--king-conservative/11930203#portfolioSettingsBtn\n\n- Мониторинг MoniTrading - https://monitrading.online/s/WZ5DOO?account=aac69b5f23a2b\n\nCLASSIC\n\n1 — CLASSIC AGGRESSIVE\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--classic/11974119\n\n- Мониторинг MoniTrading - https://monitrading.online/s/ddoSLr?account=a3a019f495654\n\n2 — CLASSIC MEDIUM\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--classic-m/11974124\n\n- Мониторинг MoniTrading - https://monitrading.online/s/2aQb2c?account=a21a6dc725d77\n\n3 — CLASSIC CONSERVATIVE\n\n- Мониторинг MyFxBook - https://www.myfxbook.com/portfolio/emar-capital--classic-k/11974129\n\n- Мониторинг MoniTrading - https://monitrading.online/s/dXkg4B?account=a540b365ffa8d"
    ),

    "Маркетинг план компании EMAR CAPITAL": (
        "Маркетинг план компании EMAR CAPITAL\n\n"
        "✅ 500$ — Стоимость Продукта\n\n"
        "Распределение 49% / 51% — Большая часть партнёрам\n\n"
        "1 линия — 170$\n"
        "2 линия — 50$\n"
        "3 линия — 35$"
    ),
    "Обменник USDT — Cardex": (
        "Официальный партнёр Emar Capital по обмену и международным платежам — "
        "компания Cardex.\n\n"
        "С 2017 года — услуги в 60+ странах для физических и юридических лиц.\n\n"
        "Что можно решить:\n"
        "• Обмен валюты на USDT (покупка советников, пополнение депозитов и обратный обмен)\n"
        "• Оплата недвижимости, авто, учёбы, лечения и отдыха за рубежом\n"
        "• Международные инвойсы и бизнес-платежи\n"
        "• Пополнение зарубежных карт\n\n"
        "Офисы: Москва, Санкт-Петербург, Казань, Дубай, Бали.\n\n"
        "Telegram: https://t.me/m/c7IG774aN2My\n"
        "Кодовое слово: EMAR CAPITAL"
    ),
    "Набор эмодзи Emar Capital для статуса Telegram": (
        "Набор эмодзи Emar Capital для статуса Telegram.\n\n"
        "Для установки нажмите на эмодзи в канале и выберите «Сделать статусом»."
    ),
}

INFO_URL_OVERRIDES: dict[str, str] = {
    "Обменник USDT — Cardex": "https://t.me/m/c7IG774aN2My",
    "Набор эмодзи Emar Capital для статуса Telegram": "https://t.me/addemoji/EMARCAPITAL",
}

INFO_OPEN_LABEL_OVERRIDES: dict[str, str] = {
    "Обменник USDT — Cardex": "💬 Открыть чат",
    "Набор эмодзи Emar Capital для статуса Telegram": "Открыть пак эмодзи",
}

INFO_NO_COPY: set[str] = {
    "Маркетинг план компании EMAR CAPITAL",
}

MONITORING_HTML_FILE = RES_DIR / "files" / "emoji" / "monitoring_body.html"
INFO_HTML_OVERRIDES: dict[str, str] = {}
if MONITORING_HTML_FILE.exists():
    INFO_HTML_OVERRIDES[
        "Ссылки на мониторинги компании (TRINITY / KING / CLASSIC)"
    ] = MONITORING_HTML_FILE.read_text(encoding="utf-8")


BASE_CATEGORIES: dict[str, list] = {
    "links": [
        {"title": "Аккаунт техподдержки", "type": "link", "url": "https://t.me/Emarcapitalbot"},
        {"title": "Официальный канал", "type": "link", "url": "https://t.me/+Gm7KW3-AZNVmOWEy"},
        {"title": "Отзывы компании", "type": "link", "url": "https://t.me/+MHHLqnoy8mUzYjYy"},
        {"title": "Сайт компании", "type": "link", "url": "https://emarcapital.pro/"},
        {"title": "Stories для контента", "type": "link", "url": STORIES_INVITE},
        {"title": "Обменник USDT компании", "type": "link", "url": "https://t.me/m/c7IG774aN2My"},
    ],
    "instructions": [],  # заполняется из экспорта
    "documents": [],
    "info": [],
    "other": [
        {
            "title": "Шаблон для подачи заявки на установку в техподдержку",
            "type": "text",
            "text": (
                "Шаблон для подачи заявки на установку теста в техподдержку\n\n"
                "VPS сервер:\nIp - \nЛогин - \nПароль - \n\n"
                "Данные торгового счета:\nНомер:\nПароль: \nСервер брокера:\n\n"
                "Ключ MoniTrading:\n\nТест сроком на 2 недели\n\n"
                "Добрый вечер, Прошу установить лицензию торгового советника ....... "
                "(название торгового советника)"
            ),
        },
        {
            "title": "Шаблон заявки на обновление Советника",
            "type": "text",
            "text": (
                "Шаблон заявки на обновление Советника:\n\nЗдравствуйте! \n\n"
                "Прошу обновить торговый советник \"название советника\" \n\n"
                "Данные счета:\n\nНомер счета - \nСервер брокера - \n\n"
                "Данные сервера:\n\nIp - \nЛогин - \nПароль -"
            ),
        },
        {
            "title": "Шаблон на перенос советника между брокерами",
            "type": "text",
            "text": (
                "Шаблон для переноса советника между брокерами\n\n"
                "VPS сервер:\nIp - \nЛогин - \nПароль - \n\n"
                "ОТКУДА ПЕРЕНОСИМ (Старый счет)\nДанные торгового счета:\n"
                "Номер:\nПароль: \nСервер брокера:\n\n\n"
                "КУДА ПЕРЕНОСИМ (Новый счет)\nДанные торгового счета:\n"
                "Номер:\nПароль: \nСервер брокера:\n\nКлюч MoniTrading:\n"
                "(ОБЯЗАТЕЛЬНО ПОДГОТОВЬТЕ МОНИТОР, УДАЛИТЕ СТАРЫЕ СОВЕТНИКИ ОТТУДА)\n\n"
                "Ваш ник телеграм: @...\n\nНик телеграм вашего пригласителя: @…\n\n"
                "Какой у вас счет: USD или USD Cent\n\n"
                "Добрый вечер, Прошу перенести лицензию торгового советника ....... "
                "(название торгового советника)"
            ),
        },
        {
            "title": "Шаблон на перенос между серверами",
            "type": "text",
            "text": (
                "Шаблон для переноса советника на новый сервер\n\n"
                "Данные торгового счета:\nНомер:\nПароль: \nСервер брокера:\n\n\n"
                "❌ ОТКУДА ПЕРЕНОСИМ (Старый сервер)\n\nVPS сервер:\nIp - \nЛогин - \nПароль - \n\n\n"
                "✅ КУДА ПЕРЕНОСИМ (Новый сервер)\n\nVPS сервер:\nIp - \nЛогин - \nПароль - \n\n"
                "🔑 Ключ MoniTrading: (вставьте ключ)\n\nВаш ник телеграм: @...\n\n"
                "Ник телеграм вашего пригласителя: @…\n\n"
                "Добрый вечер, прошу перенести лицензию торгового советника (название советика) "
                "на новый сервер"
            ),
        },
    ],
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def find_export_root(explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    candidates.append(EXPORT_DIR)
    for path in candidates:
        if (path / "result.json").is_file():
            return path
    return None


def flatten_text(text) -> str:
    if isinstance(text, str):
        return text
    if not isinstance(text, list):
        return ""
    chunks: list[str] = []
    for part in text:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            t = part.get("type", "")
            if t == "text_link":
                label = part.get("text", "").strip()
                href = part.get("href", "")
                chunks.append(f"{label}: {href}" if label else href)
            elif t in ("plain", "bold", "mention", "italic"):
                chunks.append(part.get("text", ""))
            elif part.get("text"):
                chunks.append(part.get("text", ""))
    return re.sub(r"\n{3,}", "\n\n", "".join(chunks)).strip()


def extract_video_links(text) -> list[dict]:
    if not isinstance(text, list):
        return []
    seen: set[str] = set()
    out: list[dict] = []
    section = ""
    for part in text:
        if isinstance(part, dict) and part.get("type") == "bold" and part.get("text"):
            section = part["text"].strip().replace("\n", " ")
            continue
        if not isinstance(part, dict) or part.get("type") != "text_link":
            continue
        href = part.get("href", "")
        if not href or ("youtu" not in href and "rutube" not in href):
            continue
        if href in seen:
            continue
        seen.add(href)
        label = part.get("text", "").strip() or "Смотреть"
        section_l = section.lower()
        platform = ""
        if any(k in section_l for k in ("iphone", "android", "macos", "mac")):
            platform = "iPhone / Android / Mac"
        elif "windows" in section_l:
            platform = "Windows"
        if platform:
            if "youtube" in label.lower() or "youtu.be" in href:
                label = f"{platform} — YouTube"
            elif "rutube" in label.lower() or "rutube" in href:
                label = f"{platform} — RuTube"
        elif "youtube" in label.lower() or "youtu.be" in href:
            label = "YouTube"
        elif "rutube" in label.lower() or "rutube" in href:
            label = "RuTube"
        out.append({"label": label, "url": href})
    return out


def load_messages(export_root: Path) -> dict[int, dict]:
    data = json.loads((export_root / "result.json").read_text(encoding="utf-8"))
    return {int(m["id"]): m for m in data.get("messages", []) if m.get("id")}


def best_msg_for_title(title: str, messages: dict[int, dict]) -> dict | None:
    t = norm(title)
    best, score = None, 0.0
    for msg in messages.values():
        if msg.get("type") != "message":
            continue
        text = flatten_text(msg.get("text", ""))
        if not text:
            continue
        first = norm(text.split("\n")[0])
        s = SequenceMatcher(None, t, first).ratio()
        if t in first or first in t:
            s = max(s, 0.88)
        if s > score:
            best, score = msg, s
    return best if score >= 0.45 else None


def resolve_local_file(title: str) -> str | None:
    t = norm(title.replace("🔥", ""))
    for key, fname in LOCAL_FILES.items():
        if key in t or t in key:
            if (FILES_DIR / fname).is_file():
                return fname
    for f in FILES_DIR.iterdir() if FILES_DIR.is_dir() else []:
        if norm(f.stem) in t or t in norm(f.stem):
            return f.name
    return None


def build_video_item(title: str, messages: dict[int, dict]) -> dict:
    msg_id = TITLE_MSG_IDS.get(title)
    msg = messages.get(msg_id) if msg_id else best_msg_for_title(title, messages)
    text = flatten_text(msg.get("text", "")) if msg else title
    links = extract_video_links(msg.get("text", [])) if msg else []
    caption = text.split("\n\n")[0].strip() if text else title
    if caption.startswith("🧭") or len(caption) < 3:
        caption = title
    # Старое название сервиса → MoniTrading
    caption = re.sub(r"FX\s*MONITOR", "MoniTrading", caption, flags=re.IGNORECASE)
    caption = re.sub(r"FxMonitor|FXmonitor", "MoniTrading", caption)
    item = {
        "title": title,
        "type": "video",
        "media": "video",
        "text": caption,
        "video_links": links,
    }
    if not links:
        item["note"] = "Ссылки YouTube/RuTube пока не найдены в экспорте"
    return item


def build_file_item(title: str, media: str) -> dict:
    fname = resolve_local_file(title)
    item = {
        "title": title,
        "type": "file",
        "media": media,
        "text": title,
    }
    if fname:
        item["file"] = fname
    else:
        item["note"] = "Файл не найден в resources/files/"
    return item


def clean_export_text(text: str) -> str:
    """Убирает мусорные эмодзи из экспорта, оставляет текст и URL."""
    text = re.sub(r"[🔠📏]", "", text)
    text = re.sub(r"[0-9]️⃣", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_info_item(title: str, msg_id: int, messages: dict[int, dict]) -> dict:
    if title in INFO_TEXT_OVERRIDES:
        text = INFO_TEXT_OVERRIDES[title]
    else:
        msg = messages.get(msg_id)
        text = clean_export_text(flatten_text(msg.get("text", ""))) if msg else title
    item = {"title": title, "type": "info", "text": text}
    if title in INFO_URL_OVERRIDES:
        item["url"] = INFO_URL_OVERRIDES[title]
    if title in INFO_OPEN_LABEL_OVERRIDES:
        item["openLabel"] = INFO_OPEN_LABEL_OVERRIDES[title]
    if title in INFO_NO_COPY:
        item["noCopy"] = True
    if title in INFO_HTML_OVERRIDES:
        item["html"] = INFO_HTML_OVERRIDES[title]
    fname = resolve_local_file(title)
    if fname:
        item["file"] = fname
        item["media"] = "photo"
    return item


def build(export_root: Path | None) -> dict:
    resolved = find_export_root(export_root)
    messages: dict[int, dict] = load_messages(resolved) if resolved else {}

    instructions = []
    for t in VIDEO_TITLES:
        if t in LOCAL_VIDEO_FILES:
            instructions.append(build_file_item(t, "video"))
        else:
            instructions.append(build_video_item(t, messages))
    instructions.append(
        {"title": "Телеграм бот для уведомлений", "type": "link", "url": "https://t.me/MoniTrading_bot"}
    )
    instructions.append(build_file_item("Условные обозначения валютной пары MoniTrading", "photo"))
    instructions.append(build_file_item("Как поделиться мониторингом", "photo"))
    instructions.append(build_file_item("Звук Денег для уведомлений", "audio"))

    documents = [build_file_item(title, media) for title, media in FILE_TITLES if media == "pdf"]
    info = [build_info_item(title, mid, messages) for title, mid in INFO_ITEMS]

    other = list(BASE_CATEGORIES["other"])

    categories = []
    built = {
        "links": BASE_CATEGORIES["links"],
        "instructions": instructions,
        "documents": documents,
        "info": info,
        "other": other,
    }
    for cat_id, items in built.items():
        if not items:
            continue
        categories.append(
            {"id": cat_id, "title": TITLES[cat_id], "icon": ICONS[cat_id], "items": items}
        )

    catalog = {
        "title": "EMAR Capital",
        "subtitle": "Материалы, инструкции и ссылки",
        "updated": date.today().isoformat(),
        "categories": categories,
    }

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    videos_ok = sum(1 for c in categories for i in c["items"] if i.get("video_links"))
    files_ok = sum(1 for c in categories for i in c["items"] if i.get("file"))
    print(f"✅ Каталог: {CATALOG}")
    print(f"   Видео с YouTube/RuTube: {videos_ok}")
    print(f"   Локальных файлов: {files_ok}")
    if not resolved:
        print("   ⚠️  result.json не найден — положите в finish/resources/promo_export/")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка resources.json")
    parser.add_argument("--export", type=Path, help="Папка экспорта с result.json")
    args = parser.parse_args()
    build(args.export)


if __name__ == "__main__":
    main()
