#!/bin/bash
# Стабилизация Mini App: nginx + права + проверка. Не трогает бота.
# Запуск на VPS: bash ~/finish/deploy/stabilize_miniapp.sh
set -euo pipefail

DOMAIN="${DOMAIN:-materials.emarbot.ru}"
FINISH="${FINISH_DIR:-/root/finish}"
CERT="/etc/letsencrypt/live/$DOMAIN"

echo "=== EMAR Mini App — стабилизация ==="

echo ""
echo "▶ 1. Права"
chmod 711 /root
chmod 755 "$FINISH" "$FINISH/miniapp" "$FINISH/resources" "$FINISH/resources/files"
find "$FINISH/miniapp" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "$FINISH/resources" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "$FINISH/resources/files" -type f -exec chmod 644 {} \; 2>/dev/null || true
rm -f "$FINISH/resources/files/".*.orkDcg 2>/dev/null || true
rm -f "$FINISH/app.js" "$FINISH/index.html" "$FINISH/styles.css" 2>/dev/null || true
echo "   ✅ OK"

if [[ ! -f "$CERT/fullchain.pem" ]]; then
  echo "❌ Нет SSL: $CERT/fullchain.pem"
  exit 1
fi

echo ""
echo "▶ 2. nginx — статика, gzip, без python-proxy"
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

cat > /etc/nginx/sites-available/miniapp <<EOF
# EMAR Mini App — статика (стабильно на 1 GB RAM)
server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate $CERT/fullchain.pem;
    ssl_certificate_key $CERT/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    ssl_buffer_size 4k;

    root $FINISH/miniapp;
    index index.html;

    gzip on;
    gzip_vary on;
    gzip_min_length 256;
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
        tcp_nopush on;
        tcp_nodelay on;
        send_timeout 300s;
        add_header Access-Control-Allow-Origin "*";
        add_header Accept-Ranges bytes;
        add_header Cache-Control "public, max-age=3600";
        charset utf-8;
    }

    location ~* \\.(js|css)$ {
        add_header Cache-Control "public, max-age=300";
        try_files \$uri =404;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}

server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}
EOF

ln -sf /etc/nginx/sites-available/miniapp /etc/nginx/sites-enabled/miniapp
nginx -t

echo ""
echo "▶ 3. Перезапуск nginx (жёсткий — сброс зависших worker)"
systemctl stop nginx
sleep 1
fuser -k 80/tcp 443/tcp 2>/dev/null || true
sleep 1
systemctl start nginx
sleep 1

systemctl stop miniapp 2>/dev/null || true
echo "   miniapp.service остановлен (nginx отдаёт всё сам)"

echo ""
echo "▶ 4. Проверка с VPS"
for URL in \
  "https://$DOMAIN/" \
  "https://$DOMAIN/resources.json" \
  "https://$DOMAIN/faq.json" \
  "https://$DOMAIN/app.js?v=19" \
  "https://$DOMAIN/index.html"
do
  T=$(curl -s -o /dev/null -w "%{http_code} %{time_total}s" --max-time 8 "$URL")
  echo "   $URL → $T"
done

echo ""
echo "▶ 5. Важно для Telegram Desktop"
echo "   Если видите «Обновить Telegram» внизу — обновите клиент."
echo "   Старый Desktop часто показывает пустой экран Mini App."

echo ""
echo "✅ Готово. Полностью закройте Telegram → откройте Mini App снова."
