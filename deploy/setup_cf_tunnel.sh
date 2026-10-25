#!/bin/bash
# Обход блокировки входящего HTTPS на Hostkey:
# Cloudflare Tunnel (исходящее соединение с VPS → Cloudflare → мир).
#
# Запуск на VPS:
#   bash ~/finish/deploy/setup_cf_tunnel.sh
#
# После старта скопируйте URL вида https://xxxx.trycloudflare.com
# и на Mac выполните:
#   MINIAPP_URL='https://xxxx.trycloudflare.com/' bash deploy/set_miniapp_url.sh
#
set -euo pipefail

FINISH="${FINISH_DIR:-/root/finish}"
BIN=/usr/local/bin/cloudflared
SERVICE=/etc/systemd/system/emar-cf-tunnel.service
URL_FILE="$FINISH/cf_tunnel_url.txt"

echo "=== Cloudflare Tunnel для Mini App ==="

arch=$(uname -m)
case "$arch" in
  x86_64|amd64) asset="cloudflared-linux-amd64" ;;
  aarch64|arm64) asset="cloudflared-linux-arm64" ;;
  *) echo "❌ Архитектура $arch не поддержана"; exit 1 ;;
esac

if [[ ! -x "$BIN" ]]; then
  echo "▶ Установка cloudflared..."
  tmp=$(mktemp)
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/$asset" -o "$tmp"
  install -m 755 "$tmp" "$BIN"
  rm -f "$tmp"
fi
echo "   $($BIN --version 2>/dev/null | head -1)"

# Локальный HTTP без SSL — туннель сам даёт HTTPS снаружи
# nginx на :80 редиректит на HTTPS — нужен отдельный listener без редиректа
echo "▶ Nginx: локальный HTTP для туннеля на 127.0.0.1:8088"
CERT="/etc/letsencrypt/live/materials.emarbot.ru"
cat > /etc/nginx/sites-available/miniapp-tunnel <<EOF
server {
    listen 127.0.0.1:8088;
    server_name _;

    root $FINISH/miniapp;
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;

    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        try_files /index.html =404;
    }
    location = /resources.json {
        alias $FINISH/resources/resources.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*";
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }
    location = /faq.json {
        alias $FINISH/resources/faq.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*";
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }
    location /files/ {
        alias $FINISH/resources/files/;
        sendfile on;
        add_header Access-Control-Allow-Origin "*";
        charset utf-8;
    }
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
ln -sf /etc/nginx/sites-available/miniapp-tunnel /etc/nginx/sites-enabled/miniapp-tunnel
nginx -t
systemctl reload nginx

echo "▶ systemd: emar-cf-tunnel"
cat > "$SERVICE" <<EOF
[Unit]
Description=EMAR Mini App Cloudflare Tunnel
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=$BIN tunnel --no-autoupdate --url http://127.0.0.1:8088
Restart=always
RestartSec=5
StandardOutput=append:/var/log/emar-cf-tunnel.log
StandardError=append:/var/log/emar-cf-tunnel.log

[Install]
WantedBy=multi-user.target
EOF

touch /var/log/emar-cf-tunnel.log
systemctl daemon-reload
systemctl enable emar-cf-tunnel >/dev/null
systemctl restart emar-cf-tunnel

echo "▶ Ждём URL туннеля (до 45 сек)..."
url=""
for i in $(seq 1 45); do
  url=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' /var/log/emar-cf-tunnel.log 2>/dev/null | tail -1 || true)
  if [[ -n "$url" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$url" ]]; then
  echo "❌ URL не появился. Лог:"
  tail -40 /var/log/emar-cf-tunnel.log || true
  echo ""
  echo "Проверьте: systemctl status emar-cf-tunnel"
  exit 1
fi

# без завершающего слэша в файле — добавим при записи в .env
url="${url%/}"
echo "$url/" > "$URL_FILE"
echo "   ✅ Tunnel URL: $url/"

# Обновляем MINIAPP_URL на сервере и перезапускаем бота
ENV_FILE="$FINISH/.env"
if [[ -f "$ENV_FILE" ]]; then
  if grep -q '^MINIAPP_URL=' "$ENV_FILE"; then
    sed -i "s|^MINIAPP_URL=.*|MINIAPP_URL=$url/|" "$ENV_FILE"
  else
    echo "MINIAPP_URL=$url/" >> "$ENV_FILE"
  fi
  echo "   ✅ MINIAPP_URL обновлён в $ENV_FILE"
  systemctl restart bot
  sleep 1
  systemctl is-active bot >/dev/null && echo "   ✅ bot restarted" || echo "   ⚠️  bot не active"
fi

echo ""
echo "═══════════════════════════════════════"
echo "  Mini App через Cloudflare Tunnel"
echo "  $url/"
echo "═══════════════════════════════════════"
echo ""
echo "Проверьте в браузере: $url/"
echo "В Telegram полностью закройте бота и откройте Материалы снова."
echo ""
echo "URL сохранён: $URL_FILE"
echo "Лог туннеля:  tail -f /var/log/emar-cf-tunnel.log"
echo ""
echo "На Mac синхронизируйте .env:"
echo "  scp root@148.135.211.59:~/finish/.env finish/.env"
echo "  # и поправьте корневой .env → MINIAPP_URL=$url/"
echo ""
