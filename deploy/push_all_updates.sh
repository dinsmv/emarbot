#!/bin/bash
# Полная заливка текущих правок панели + бота + Q&A на VPS.
# Запуск с Mac (спросит пароль несколько раз):
#   bash finish/deploy/push_all_updates.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "═══════════════════════════════════════"
echo "  1/2  deploy_all.sh (код + knowledge_db + файлы ≤50MB)"
echo "═══════════════════════════════════════"
bash deploy_all.sh

echo ""
echo "═══════════════════════════════════════"
echo "  2/2  Q&A обменник + видео-ссылки → Chroma"
echo "═══════════════════════════════════════"
VPS="${VPS:-root@148.135.211.59}"
ssh -o ServerAliveInterval=30 "$VPS" bash -s <<'REMOTE'
set -euo pipefail
cd ~/finish
PY=./.venv/bin/python
[[ -x "$PY" ]] || PY=python3

for f in exchanger_qa.txt video_links_qa.txt; do
  if [[ -f "$f" ]]; then
    echo "▶ append $f"
    $PY append_qa_to_db.py "$f" || echo "⚠️  $f не добавлен (проверьте Jina/логи)"
  else
    echo "⚠️  нет $f"
  fi
done

systemctl restart bot
sleep 1
systemctl is-active bot && echo "✅ bot active" || echo "❌ bot not active"
systemctl is-active nginx >/dev/null 2>&1 && echo "✅ nginx active" || true
# туннель если есть
systemctl is-active emar-cf-tunnel >/dev/null 2>&1 && echo "✅ cf-tunnel active" || echo "ℹ️  cf-tunnel не запущен (если панель через trycloudflare — поднимите снова)"
grep -E '^MINIAPP_URL=' .env 2>/dev/null || true
REMOTE

echo ""
echo "═══════════════════════════════════════"
echo "  ✅ Заливка завершена"
echo "═══════════════════════════════════════"
echo "Проверьте в Telegram: Материалы + «ссылка на обменник» / «регистрация forex4you»"
