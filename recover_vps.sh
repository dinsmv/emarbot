#!/bin/bash
# Полная починка на VPS одной командой (если deploy/ не залился):
#   cd ~/finish && bash recover_vps.sh
set -euo pipefail
cd "$(dirname "$0")"

DOMAIN="${DOMAIN:-materials.emarbot.ru}"

echo "=== Зависимости (без openai) ==="
pip3 install python-telegram-bot[job-queue] python-dotenv chromadb groq requests gspread oauth2client python-docx openpyxl -q

echo ""
echo "=== База знаний ==="
if python3 -c "
import chromadb
c = chromadb.PersistentClient(path='knowledge_db')
col = c.get_collection('faq')
print('faq:', col.count())
" 2>/dev/null; then
  echo "knowledge_db OK"
else
  echo "Пересобираю knowledge_db..."
  python3 build_database.py
fi

echo ""
echo "=== Mini App service ==="
cat > /etc/systemd/system/miniapp.service <<EOF
[Unit]
Description=EMAR Mini App
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/finish
Environment=MINIAPP_PORT=8765
ExecStart=/usr/bin/python3 /root/finish/serve_miniapp.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable miniapp
systemctl restart miniapp
sleep 1

if curl -sf http://127.0.0.1:8765/resources.json | head -c 80; then
  echo ""
  echo "✅ Mini App работает"
else
  echo "❌ Mini App не отвечает"
  journalctl -u miniapp -n 20 --no-pager
  exit 1
fi

echo ""
echo "=== Nginx для $DOMAIN ==="
cat > /etc/nginx/sites-available/miniapp <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/miniapp /etc/nginx/sites-enabled/miniapp
nginx -t && systemctl reload nginx
echo "✅ nginx настроен (пока HTTP)"

echo ""
echo "=== Бот ==="
systemctl restart bot
sleep 2
systemctl status bot --no-pager | head -12 || true

echo ""
echo "=== Дальше ==="
echo "1. DNS: A-запись materials.emarbot.ru → 148.135.211.59"
echo "2. Проверка: dig +short materials.emarbot.ru"
echo "3. SSL:  certbot --nginx -d materials.emarbot.ru"
echo "4. .env: MINIAPP_URL=https://materials.emarbot.ru/"
echo "5.       systemctl restart bot"
