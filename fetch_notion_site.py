#!/usr/bin/env python3
"""
Скачивание публичного Notion-сайта EMAR CAPITAL Academy без Export.

Использует внутренние API Notion (loadCachedPageChunkV2 + syncRecordValues),
как notion-site-fetch: https://pypi.org/project/notion-site-fetch/

Пример:
  cd finish
  python3 fetch_notion_site.py
  python3 fetch_notion_site.py --url "https://abalone-magic-c2b.notion.site/EMAR-CAPITAL-Academy-4ca89e0d379083bb96d88168315e00de"
"""
from __future__ import annotations

import argparse
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

ROOT = Path(__file__).resolve().parent
DEFAULT_URL = (
    "https://abalone-magic-c2b.notion.site/"
    "EMAR-CAPITAL-Academy-4ca89e0d379083bb96d88168315e00de"
)
EXPORT_DIR = ROOT / "resources" / "notion_export"

NOTION_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (notion-reader)",
}
MAX_RETRIES = 10
RETRY_BACKOFF = 1.0


def notion_post(client: httpx.Client, url: str, payload: dict) -> dict:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.post(url, headers=NOTION_HEADERS, json=payload)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (attempt + 2) * 3
                m = re.search(r"retry-after[:\s]+(\d+)", resp.text, re.I)
                if m:
                    wait = max(wait, int(m.group(1)))
                time.sleep(wait)
                last_err = httpx.HTTPStatusError(
                    f"429 from {url}",
                    request=resp.request,
                    response=resp,
                )
                continue
            if resp.status_code >= 500:
                last_err = httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}: {resp.text[:200]}",
                    request=resp.request,
                    response=resp,
                )
            else:
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            last_err = exc
        time.sleep(RETRY_BACKOFF * (attempt + 1))
    assert last_err is not None
    raise last_err


def pick_api_base(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".notion.site"):
        return f"https://{host}/api/v3"
    return "https://www.notion.so/api/v3"


def parse_page_id(url: str) -> str:
    path = unquote(urlparse(url).path or "/")
    hex_path = re.sub(r"[^0-9a-fA-F]", "", path)
    match = re.search(r"([0-9a-fA-F]{32})$", hex_path)
    if not match:
        raise ValueError(f"Не удалось извлечь page id из URL: {url}")
    raw = match.group(1).lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def fetch_all_blocks(
    page_id: str,
    client: httpx.Client,
    api_base: str,
    *,
    sync_missing: bool = True,
) -> tuple[dict[str, dict], str]:
    blocks: dict[str, dict] = {}
    cursor: dict = {"stack": []}
    chunk_no = 0
    space_id = ""

    while True:
        data = notion_post(
            client,
            f"{api_base}/loadCachedPageChunkV2",
            {
                "page": {"id": page_id},
                "limit": 100,
                "cursor": cursor,
                "chunkNumber": chunk_no,
                "verticalColumns": False,
            },
        )
        space_id = data.get("spaceId") or space_id
        for bid, rec in (data.get("recordMap") or {}).get("block", {}).items():
            val = rec.get("value", {}).get("value")
            if val:
                blocks[bid] = val

        cursors = data.get("cursors") or []
        nxt = cursors[0] if cursors else None
        if not nxt or not nxt.get("stack"):
            break
        cursor = {"stack": nxt["stack"]}
        chunk_no += 1

    if not space_id:
        raise RuntimeError(f"spaceId не получен для страницы {page_id}")

    if not sync_missing:
        return blocks, space_id

    while True:
        missing = {
            cid
            for blk in blocks.values()
            for cid in (blk.get("content") or [])
            if cid not in blocks
        }
        if not missing:
            break
        got_new = False
        batch_list = list(missing)
        for start in range(0, len(batch_list), 100):
            batch = batch_list[start : start + 100]
            sync = notion_post(
                client,
                "https://www.notion.so/api/v3/syncRecordValues",
                {
                    "requests": [
                        {
                            "pointer": {
                                "table": "block",
                                "id": bid,
                                "spaceId": space_id,
                            },
                            "version": -1,
                        }
                        for bid in batch
                    ]
                },
            )
            for bid, rec in (sync.get("recordMap") or {}).get("block", {}).items():
                val = rec.get("value", {}).get("value")
                if val and bid not in blocks:
                    blocks[bid] = val
                    got_new = True
            time.sleep(0.4)
        if not got_new:
            break

    return blocks, space_id


def render_rich_text(runs) -> str:
    if not runs:
        return ""
    parts: list[str] = []
    for run in runs:
        if not run:
            continue
        plain = run[0] if len(run) > 0 else ""
        deco = run[1] if len(run) > 1 else []
        link = None
        bold = italic = strike = code = False
        for d in deco or []:
            if not d:
                continue
            tag = d[0]
            if tag == "b":
                bold = True
            elif tag == "i":
                italic = True
            elif tag == "s":
                strike = True
            elif tag == "c":
                code = True
            elif tag == "a" and len(d) > 1:
                link = d[1]
        text = plain
        if code:
            text = f"`{text}`"
        else:
            if bold:
                text = f"**{text}**"
            if italic:
                text = f"*{text}*"
            if strike:
                text = f"~~{text}~~"
        if link:
            text = f"[{text}]({link})"
        parts.append(text)
    return "".join(parts)


def page_title(blocks: dict[str, dict], page_id: str) -> str:
    blk = blocks.get(page_id) or {}
    runs = (blk.get("properties") or {}).get("title") or []
    return render_rich_text(runs).strip() or page_id


def render_block_lines(
    block_id: str,
    blocks: dict[str, dict],
    indent: int,
    list_pos: int,
    root_page_id: str,
) -> list[str]:
    blk = blocks.get(block_id)
    if not blk:
        return []
    btype = blk.get("type")
    title = render_rich_text((blk.get("properties") or {}).get("title") or [])
    prefix = "    " * indent
    lines: list[str] = []

    if btype == "page":
        if title and block_id != root_page_id:
            lines.extend([f"{prefix}## {title}", ""])
    elif btype == "header":
        lines.extend([f"{prefix}## {title}", ""])
    elif btype == "sub_header":
        lines.extend([f"{prefix}### {title}", ""])
    elif btype == "sub_sub_header":
        lines.extend([f"{prefix}#### {title}", ""])
    elif btype == "text":
        if title:
            lines.extend([f"{prefix}{title}", ""])
    elif btype == "bulleted_list":
        lines.append(f"{prefix}- {title}")
    elif btype == "numbered_list":
        lines.append(f"{prefix}{list_pos}. {title}")
    elif btype == "to_do":
        checked = (blk.get("properties") or {}).get("checked") == [["Yes"]]
        mark = "[x]" if checked else "[ ]"
        lines.append(f"{prefix}- {mark} {title}")
    elif btype == "toggle":
        lines.append(f"{prefix}- {title}")
    elif btype == "quote":
        lines.extend([f"{prefix}> {title}", ""])
    elif btype == "callout":
        icon = (blk.get("format") or {}).get("page_icon", "")
        lead = f"{icon} " if icon and not str(icon).startswith("/") else ""
        lines.extend([f"{prefix}> {lead}{title}", ""])
    elif btype == "divider":
        lines.extend([f"{prefix}---", ""])
    elif btype == "code":
        lang = render_rich_text((blk.get("properties") or {}).get("language") or [])
        lines.append(f"{prefix}```{lang.lower()}")
        for ln in title.split("\n"):
            lines.append(f"{prefix}{ln}")
        lines.extend([f"{prefix}```", ""])
    elif btype == "image":
        src = render_rich_text((blk.get("properties") or {}).get("source") or [])
        cap = render_rich_text((blk.get("properties") or {}).get("caption") or [])
        if src:
            lines.extend([f"{prefix}![{cap}]({src})", ""])
    elif btype in ("bookmark", "video", "embed", "file", "pdf", "audio"):
        link = render_rich_text(
            (blk.get("properties") or {}).get("source")
            or (blk.get("properties") or {}).get("link")
            or []
        )
        if link:
            lines.extend([f"{prefix}[{title or link}]({link})", ""])
    elif btype == "equation":
        eq = render_rich_text((blk.get("properties") or {}).get("title") or [])
        lines.extend([f"{prefix}$${eq}$$", ""])
    elif btype in ("column_list", "column", "table_of_contents", "breadcrumb"):
        pass
    elif title:
        lines.extend([f"{prefix}{title}", ""])

    child_ids = blk.get("content") or []
    nest = btype in ("bulleted_list", "numbered_list", "to_do", "toggle")
    child_indent = indent + 1 if nest else indent

    num = 0
    prev_type = None
    for cid in child_ids:
        child = blocks.get(cid) or {}
        ctype = child.get("type")
        if ctype == "numbered_list":
            num = num + 1 if prev_type == "numbered_list" else 1
        else:
            num = 0
        lines.extend(render_block_lines(cid, blocks, child_indent, num, root_page_id))
        prev_type = ctype

    return lines


def collapse_lines(lines: list[str]) -> str:
    out: list[str] = []
    prev_blank = False
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank
    return "\n".join(out).rstrip() + "\n"


def render_page_md(page_id: str, blocks: dict[str, dict]) -> str:
    title = page_title(blocks, page_id)
    body = collapse_lines(render_block_lines(page_id, blocks, 0, 0, page_id))
    return f"# {title}\n\n{body}"


def child_page_ids(page_id: str, blocks: dict[str, dict]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def walk(bid: str):
        blk = blocks.get(bid)
        if not blk:
            return
        if blk.get("type") == "page" and bid != page_id and bid not in seen:
            seen.add(bid)
            found.append(bid)
            return  # не углубляемся в содержимое вложенных страниц
        for cid in blk.get("content") or []:
            walk(cid)

    walk(page_id)
    return found


def slugify(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^\w\s\-]", " ", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:120] or "page"


def fetch_site(root_url: str, out_dir: Path, resume: bool = True) -> list[Path]:
    api_base = pick_api_base(root_url)
    root_id = parse_page_id(root_url)
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = out_dir / ".fetch_checkpoint.json"
    manifest_path = out_dir / ".page_manifest.json"
    import json

    if resume and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        seen_pages = set(manifest.keys())
    elif resume and checkpoint_path.is_file():
        cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        seen_pages = set(cp.get("seen", []))
    else:
        seen_pages = set()

    if resume and checkpoint_path.is_file():
        cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        queue = [p for p in cp.get("queue", []) if p not in seen_pages]
        if seen_pages:
            print(f"↩️  Продолжаем: уже {len(seen_pages)} стр., в очереди {len(queue)}")
    else:
        queue = []

    if not queue:
        queue = [root_id]

    saved: list[Path] = list(out_dir.glob("*.md"))

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        while queue:
            page_id = queue.pop(0)
            if page_id in seen_pages:
                continue
            seen_pages.add(page_id)

            print(f"📥 {page_id}...", flush=True)
            use_sync = page_id != root_id
            blocks, _space = fetch_all_blocks(
                page_id, client, api_base, sync_missing=use_sync
            )
            if page_id not in blocks:
                print(f"   ⚠️  страница не найдена в ответе, пропуск")
                continue

            title = page_title(blocks, page_id)
            md = render_page_md(page_id, blocks)
            fname = f"{slugify(title)}.md"
            path = out_dir / fname
            # дубликаты имён
            if path.exists() and path.read_text(encoding="utf-8")[:50] != md[:50]:
                path = out_dir / f"{slugify(title)}_{page_id[:8]}.md"
            path.write_text(md, encoding="utf-8")
            saved.append(path)
            print(f"   ✅ {title[:60]} → {path.name} ({len(md)} симв.)")

            manifest_path = out_dir / ".page_manifest.json"
            import json

            manifest: dict[str, str] = {}
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest[page_id] = path.name
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            for child_id in child_page_ids(page_id, blocks):
                if child_id not in seen_pages and child_id not in queue:
                    queue.append(child_id)

            checkpoint_path.write_text(
                json.dumps({"seen": sorted(seen_pages), "queue": queue}, ensure_ascii=False),
                encoding="utf-8",
            )
            time.sleep(1.5)

    checkpoint_path.unlink(missing_ok=True)

    return saved


def main():
    parser = argparse.ArgumentParser(description="Скачать публичный Notion-сайт в Markdown")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=EXPORT_DIR)
    parser.add_argument("--fresh", action="store_true", help="Скачать заново")
    args = parser.parse_args()

    if args.fresh and args.out.is_dir():
        for f in args.out.glob("*.md"):
            f.unlink()

    files = fetch_site(args.url, args.out, resume=not args.fresh)
    print(f"\n✅ Сохранено {len(files)} страниц в {args.out}")
    print("Дальше: python3 extract_notion_academy.py")


if __name__ == "__main__":
    main()
