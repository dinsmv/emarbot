#!/bin/bash
# Проверка: все файлы из resources.json есть на диске и отдаются по HTTPS.
# Запуск на VPS: bash ~/finish/deploy/verify_materials.sh
set -euo pipefail

FINISH="${FINISH_DIR:-/root/finish}"
DOMAIN="${DOMAIN:-materials.emarbot.ru}"
JSON="$FINISH/resources/resources.json"
FILES_DIR="$FINISH/resources/files"

echo "=== 1. Структура (должно быть в miniapp/, не в finish/) ==="
for f in app.js index.html styles.css; do
  if [[ -f "$FINISH/$f" && -f "$FINISH/miniapp/$f" ]]; then
    echo "   ⚠️  Дубликат: $FINISH/$f и miniapp/$f (nginx читает только miniapp/)"
  elif [[ -f "$FINISH/miniapp/$f" ]]; then
    echo "   ✅ miniapp/$f"
  else
    echo "   ❌ нет miniapp/$f"
  fi
done

echo ""
echo "=== 2. Мусор от оборванной загрузки ==="
find "$FILES_DIR" -name '*.orkDcg' -o -name '.*.mp4.*' 2>/dev/null | head -5 || echo "   (нет)"

echo ""
echo "=== 3. Ссылки из resources.json ==="
python3 <<PY
import json, subprocess
from pathlib import Path
from urllib.parse import urlparse

finish = Path("$FINISH")
data = json.loads((finish / "resources" / "resources.json").read_text())
domain = "$DOMAIN"

local_files = 0
tg_links = 0
other = 0
problems = []

for cat in data.get("categories", []):
    for item in cat.get("items", []):
        url = item.get("url", "")
        title = item.get("title", "")
        if url.startswith("/files/"):
            local_files += 1
            print(f"   ⚠️  Локальный файл (лучше заменить ссылкой на канал): {title}")
            problems.append(title)
            continue
        if not url.startswith("http"):
            continue
        host = urlparse(url).netloc.lower()
        if "t.me" in host or "telegram" in host:
            tg_links += 1
            kind = "пост" if "/c/" in url else "канал"
            print(f"   ✅ Telegram ({kind}): {title[:50]}")
        else:
            other += 1
            try:
                r = subprocess.run(
                    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "8", url],
                    capture_output=True, text=True, timeout=12,
                )
                code = r.stdout.strip() or "000"
            except Exception:
                code = "err"
            mark = "✅" if code in ("200", "301", "302") else "⚠️"
            print(f"   {mark} HTTP {code}: {title[:50]}")

print()
print(f"Итого: Telegram {tg_links}, внешние {other}, локальные /files/ {local_files}")
if local_files:
    print("   → Запустите на Mac: cd finish && python3 resources/build_catalog.py")
    raise SystemExit(1)
PY

echo ""
echo "=== 4. Mini App UI ==="
for u in "/" "/resources.json" "/app.js?v=9"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "https://$DOMAIN$u")
  echo "   $u → HTTP $code"
done
echo ""
echo "✅ Проверка завершена"
