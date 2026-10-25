#!/bin/bash
# Запуск на VPS после загрузки файлов (из ~/finish):
#   bash setup_miniapp_vps.sh
set -euo pipefail

cd "$(dirname "$0")/.."
FINISH="${FINISH_DIR:-$HOME/finish}"

echo "=== Mini App setup in $FINISH ==="

mkdir -p "$FINISH/resources/files"

if ! grep -q MINIAPP_URL "$FINISH/.env" 2>/dev/null; then
  echo ""
  echo "Добавьте в $FINISH/.env:"
  echo "  MINIAPP_URL=https://ВАШ_ДОМЕН/"
  echo ""
fi

# systemd
if [ -f deploy/miniapp.service ]; then
  sed "s|/root/finish|$FINISH|g" deploy/miniapp.service | sudo tee /etc/systemd/system/miniapp.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable miniapp
  sudo systemctl restart miniapp
  echo "✅ miniapp.service запущен (порт 8765)"
fi

echo ""
echo "Дальше:"
echo "  1. nginx + certbot (см. deploy/nginx-miniapp.conf)"
echo "  2. MINIAPP_URL=https://домен/ в .env"
echo "  3. systemctl restart bot"
