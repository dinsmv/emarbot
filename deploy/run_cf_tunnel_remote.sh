#!/bin/bash
# На Mac: залить скрипт туннеля на VPS и запустить.
#   bash finish/deploy/run_cf_tunnel_remote.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VPS="${VPS:-root@148.135.211.59}"

echo "▶ Копирую setup_cf_tunnel.sh на $VPS..."
scp -o ServerAliveInterval=30 \
  "$ROOT/finish/deploy/setup_cf_tunnel.sh" \
  "$VPS:~/finish/deploy/setup_cf_tunnel.sh"

echo "▶ Запускаю на VPS (введите пароль)..."
ssh -o ServerAliveInterval=30 "$VPS" 'chmod +x ~/finish/deploy/setup_cf_tunnel.sh && bash ~/finish/deploy/setup_cf_tunnel.sh'

echo ""
echo "▶ Забираю URL и .env с VPS..."
scp -o ServerAliveInterval=30 "$VPS:~/finish/cf_tunnel_url.txt" /tmp/emar_cf_url.txt 2>/dev/null || true
scp -o ServerAliveInterval=30 "$VPS:~/finish/.env" "$ROOT/finish/.env" 2>/dev/null || true

if [[ -f /tmp/emar_cf_url.txt ]]; then
  URL=$(cat /tmp/emar_cf_url.txt | tr -d '\r\n')
  echo "MINIAPP_URL=$URL"
  if [[ -f "$ROOT/.env" ]]; then
    if grep -q '^MINIAPP_URL=' "$ROOT/.env"; then
      # mac sed
      sed -i '' "s|^MINIAPP_URL=.*|MINIAPP_URL=$URL|" "$ROOT/.env" 2>/dev/null \
        || sed -i "s|^MINIAPP_URL=.*|MINIAPP_URL=$URL|" "$ROOT/.env"
    else
      echo "MINIAPP_URL=$URL" >> "$ROOT/.env"
    fi
    echo "   ✅ обновлён $ROOT/.env"
  fi
  echo ""
  echo "Откройте в браузере: $URL"
fi
