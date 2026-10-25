#!/bin/bash
# Настройка nginx для стабильной отдачи видео (Range + без буферизации).
# Не трогает SSL от certbot — только дописывает proxy-настройки.
# Запуск на VPS: bash ~/finish/deploy/fix_nginx_video.sh
set -euo pipefail

CONF="/etc/nginx/sites-enabled/miniapp"
MARKER="# emar-video-proxy"

if [[ ! -f "$CONF" ]]; then
  echo "❌ Нет $CONF"
  exit 1
fi

if grep -q "$MARKER" "$CONF"; then
  echo "✅ nginx уже настроен для видео"
  nginx -t && systemctl reload nginx
  exit 0
fi

python3 <<'PY'
from pathlib import Path
conf = Path("/etc/nginx/sites-enabled/miniapp")
text = conf.read_text()
block = """
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
"""
marker = "        # emar-video-proxy"
if marker.strip() in text:
    print("already patched")
    raise SystemExit(0)
# вставить после proxy_set_header X-Forwarded-Proto (последнее вхождение в location /)
needle = "proxy_set_header X-Forwarded-Proto"
idx = text.rfind(needle)
if idx < 0:
    # certbot-конфиг без этой строки — после proxy_pass
    needle = "proxy_pass"
    idx = text.rfind(needle)
    line_end = text.find("\n", idx)
    new = text[:line_end+1] + block + marker + "\n" + text[line_end+1:]
else:
    line_end = text.find("\n", idx)
    new = text[:line_end+1] + block + marker + "\n" + text[line_end+1:]
conf.write_text(new)
print("✅ proxy-настройки добавлены")
PY

nginx -t
systemctl reload nginx
echo "✅ nginx перезагружен"
