#!/bin/bash
# Certbot + nginx: ставит nginx при необходимости и выпускает SSL.
# Запуск на VPS: bash ~/finish/deploy/fix_certbot_vps.sh
set -euo pipefail

DOMAIN="${DOMAIN:-materials.emarbot.ru}"
FINISH="${FINISH_DIR:-/root/finish}"

echo "=== Починка certbot + SSL для $DOMAIN ==="

export DEBIAN_FRONTEND=noninteractive

echo "▶ nginx..."
if ! command -v nginx >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq nginx
  echo "   ✅ nginx установлен"
else
  echo "   уже есть: $(nginx -v 2>&1)"
fi

# HTTP-сайт до сертификата (certbot --nginx его дополнит SSL)
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

cat > /etc/nginx/sites-available/miniapp <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    root $FINISH/miniapp;
    index index.html;

    location = /resources.json {
        alias $FINISH/resources/resources.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*";
    }

    location = /faq.json {
        alias $FINISH/resources/faq.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*";
    }

    location /files/ {
        alias $FINISH/resources/files/;
        add_header Access-Control-Allow-Origin "*";
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
ln -sf /etc/nginx/sites-available/miniapp /etc/nginx/sites-enabled/miniapp
nginx -t
systemctl enable nginx >/dev/null 2>&1 || true
systemctl restart nginx

# Вариант 1: snap certbot
if command -v snap >/dev/null 2>&1; then
  echo "▶ Устанавливаю/проверяю certbot (snap)..."
  snap install core 2>/dev/null || true
  snap refresh core 2>/dev/null || true
  snap install --classic certbot 2>/dev/null || true
  if [[ -x /snap/bin/certbot ]]; then
    ln -sf /snap/bin/certbot /usr/bin/certbot
    # плагин nginx для snap
    snap set certbot trust-plugin-with-root=ok 2>/dev/null || true
    snap install certbot-dns-cloudflare 2>/dev/null || true
  fi
fi

# python3-certbot-nginx как запасной вариант плагина
apt-get install -y -qq python3-certbot-nginx 2>/dev/null || true

if ! command -v certbot >/dev/null 2>&1; then
  apt-get install -y -qq certbot python3-certbot-nginx
fi

if ! certbot --version >/dev/null 2>&1; then
  echo "❌ certbot не запускается"
  certbot --version 2>&1 || true
  exit 1
fi

echo "▶ certbot OK: $(certbot --version 2>&1 | head -1)"

echo "▶ Выпуск сертификата (Let's Encrypt)..."
# noninteractive: если email уже был — ок; иначе --register-unsafely-without-email
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email \
  --redirect || certbot --nginx -d "$DOMAIN" --agree-tos --register-unsafely-without-email --redirect

nginx -t && systemctl reload nginx

echo ""
echo "Проверка HTTPS:"
curl -sI "https://$DOMAIN/" | head -5 || echo "(пусто — SSL ещё не поднялся)"
curl -sI "https://$DOMAIN/resources.json" | head -5 || true
echo ""
echo "✅ Готово. Дальше: bash ~/finish/deploy/stabilize_miniapp.sh"
