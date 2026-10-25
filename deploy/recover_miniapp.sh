#!/bin/bash
# Восстановление Mini App — всё через nginx, без proxy (стабильно на 1 GB RAM).
# Запуск на VPS: bash ~/finish/deploy/recover_miniapp.sh
set -euo pipefail

DOMAIN="${DOMAIN:-materials.emarbot.ru}"
FINISH="${FINISH_DIR:-/root/finish}"
CERT="/etc/letsencrypt/live/$DOMAIN"

echo "=== 1. Права для nginx ==="
chmod 711 /root
chmod 755 "$FINISH" "$FINISH/miniapp" "$FINISH/resources" "$FINISH/resources/files"
find "$FINISH/miniapp" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "$FINISH/resources" -type f -exec chmod 644 {} \; 2>/dev/null || true
find "$FINISH/resources/files" -type f -exec chmod 644 {} \; 2>/dev/null || true
echo "   ✅ права OK"

if [[ ! -f "$CERT/fullchain.pem" ]]; then
  echo "❌ Нет SSL: $CERT/fullchain.pem"
  exit 1
fi

echo ""
echo "=== 2. nginx — только статика, без python-proxy ==="
cat > /etc/nginx/sites-available/miniapp <<EOF
# EMAR Mini App — полностью статика через nginx (не зависает)
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
    alias /root/finish/resources/files/;
    
    # Таймауты для больших файлов
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    
    # Буферизация и таймауты
    send_timeout 300s;
    
    # Размер буфера
    output_buffers 2 512k;
    postpone_output 1460;
    
    # Заголовки
    add_header Access-Control-Allow-Origin "*";
    add_header Accept-Ranges bytes;
    add_header Cache-Control "public, max-age=3600";
    
    # Кириллица в именах файлов
    charset utf-8;
    
    # Для видео — важно!
    mp4;
    mp4_buffer_size 1m;
    mp4_max_buffer_size 20m;
}

    location = /resources.json {
        alias $FINISH/resources/resources.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*";
        add_header Cache-Control "no-cache";
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
systemctl restart nginx

echo ""
echo "=== 3. miniapp.service — опционально (для разработки) ==="
systemctl stop miniapp 2>/dev/null || true
echo "   ℹ️  python miniapp остановлен — nginx отдаёт всё сам"

echo ""
echo "=== 4. Проверка ==="
curl -sf --max-time 5 "https://$DOMAIN/" | head -c 30 && echo " ← index.html"
curl -sf --max-time 5 "https://$DOMAIN/resources.json" | head -c 40 && echo " ← catalog"
SAMPLE=$(find "$FINISH/resources/files" -type f \( -name '*.mp4' -o -name '*.MOV' -o -name '*.mov' \) 2>/dev/null | head -1)
if [[ -n "$SAMPLE" ]]; then
  NAME=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$(basename "$SAMPLE")")
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 -r 0-999 "https://$DOMAIN/files/$NAME")
  echo "   /files/ тест: HTTP $CODE"
fi
echo ""
echo "✅ Готово. Закройте Mini App в Telegram и откройте снова."
