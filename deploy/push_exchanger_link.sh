#!/bin/bash
# Обновить ссылку обменника на VPS + добавить Q&A в базу + рестарт бота.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VPS="${VPS:-root@148.135.211.59}"
FINISH="$ROOT/finish"
SCP='scp -o ServerAliveInterval=30'
SSH='ssh -o ServerAliveInterval=30'

echo "▶ Заливаю файлы..."
$SCP "$FINISH/resources/resources.json" "$VPS:~/finish/resources/resources.json"
$SCP "$FINISH/resources/build_catalog.py" "$VPS:~/finish/resources/build_catalog.py"
$SCP "$FINISH/brand.py" "$VPS:~/finish/brand.py"
$SCP "$FINISH/materials.py" "$VPS:~/finish/materials.py"
$SCP "$FINISH/supplemental_qa.txt" "$VPS:~/finish/supplemental_qa.txt"
$SCP "$FINISH/exchanger_qa.txt" "$VPS:~/finish/exchanger_qa.txt"
$SCP "$FINISH/miniapp/index.html" "$VPS:~/finish/miniapp/index.html"

echo "▶ На VPS: Q&A + restart..."
$SSH "$VPS" bash -s <<'REMOTE'
set -euo pipefail
cd ~/finish
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python append_qa_to_db.py exchanger_qa.txt || echo "⚠️ append_qa пропущен (проверьте Jina)"
else
  python3 append_qa_to_db.py exchanger_qa.txt || echo "⚠️ append_qa пропущен"
fi
systemctl restart bot
sleep 1
systemctl is-active bot && echo "✅ bot active" || echo "⚠️ bot not active"
REMOTE

echo ""
echo "Готово. В Telegram: «ссылка на обменник» → https://t.me/m/c7IG774aN2My"
