#!/bin/bash
# Починка зависшего nginx для Mini App.
# Запуск на VPS: bash ~/finish/deploy/fix_nginx_hang.sh
set -euo pipefail

DOMAIN="${DOMAIN:-materials.emarbot.ru}"
FINISH="${FINISH_DIR:-/root/finish}"
CERT="/etc/letsencrypt/live/$DOMAIN"

echo "=== 1. Убираем лишние конфиги nginx ==="
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
# оставляем только miniapp
ls -la /etc/nginx/sites-enabled/

echo ""
echo "=== 2. Права на файлы ==="
chmod 711 /root
chmod 755 "$FINISH" "$FINISH/miniapp" "$FINISH/resources" "$FINISH/resources/files"
find "$FINISH/miniapp" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "$FINISH/resources" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "$FINISH/resources/files" -type f -exec chmod 644 {} \; 2>/dev/null || true

echo ""
echo "=== 3. Чистый конфиг (только статика, без proxy) ==="
cat > /etc/nginx/sites-available/miniapp <<EOF
server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate $CERT/fullchain.pem;
    ssl_certificate_key $CERT/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root $FINISH/miniapp;
    index index.html;

    location /files/ {
        alias $FINISH/resources/files/;
        sendfile on;
        tcp_nopush on;
        add_header Access-Control-Allow-Origin "*";
        add_header Accept-Ranges bytes;
    }

    location = /resources.json {
        alias $FINISH/resources/resources.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*";
        add_header Cache-Control "no-cache";
    }

    location / {
        try_files \$uri /index.html;
    }
}

server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}
EOF

ln -sf /etc/nginx/sites-available/miniapp /etc/nginx/sites-enabled/miniapp

echo ""
echo "=== 4. Перезапуск nginx (сброс зависших worker-ов) ==="
nginx -t
systemctl stop nginx
sleep 1
fuser -k 80/tcp 443/tcp 2>/dev/null || true
sleep 1
systemctl start nginx
sleep 1

echo ""
echo "=== 5. Проверка (должно быть < 1 сек) ==="
for URL in "https://$DOMAIN/" "https://$DOMAIN/resources.json" "https://$DOMAIN/app.js"; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$URL")
  echo "   $URL → HTTP $CODE"
done

echo ""
echo "=== 6. Бот ==="
grep MINIAPP_URL "$FINISH/.env" 2>/dev/null || echo "   ⚠️  MINIAPP_URL не найден в .env"
systemctl is-active bot && echo "   bot: active" || echo "   ⚠️  bot не запущен"

echo ""
echo "✅ Готово. Закройте Telegram полностью и откройте Mini App снова."
