#!/bin/bash
# Запускается на VPS после deploy.sh / deploy_all.sh
# Ubuntu 24.04: пакеты ставятся в ~/finish/.venv (PEP 668)
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

DOMAIN="${DOMAIN:-materials.emarbot.ru}"
REBUILD=false
for arg in "$@"; do
  [[ "$arg" == "--rebuild-db" ]] && REBUILD=true
done

echo "=== remote_update.sh ==="

echo "▶ Python venv..."
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq python3-venv python3-full >/dev/null 2>&1 || true

if [[ ! -x "$PY" ]]; then
  python3 -m venv "$VENV"
  echo "   создан $VENV"
else
  echo "   уже есть $VENV"
fi

echo "▶ Зависимости в venv..."
"$PIP" install -U pip -q
if "$PIP" install -r requirements.txt -q; then
  echo "   ✅ requirements.txt"
else
  echo "   ⚠️  requirements.txt — пробую по пакетам"
  "$PIP" install -q \
    "python-telegram-bot[job-queue]" python-dotenv chromadb groq anthropic requests \
    gspread oauth2client python-docx openpyxl pysqlite3-binary || true
fi
"$PIP" install -q anthropic pysqlite3-binary || true

echo "▶ systemd: bot.service + miniapp.service..."
# Подставляем путь к venv-python
if [[ -f deploy/bot.service ]]; then
  sed "s|/usr/bin/python3|$PY|g; s|WorkingDirectory=/root/finish|WorkingDirectory=$ROOT|g" \
    deploy/bot.service > /etc/systemd/system/bot.service
  systemctl daemon-reload
  systemctl enable bot >/dev/null 2>&1 || true
  echo "   ✅ bot.service → $PY"
fi
if [[ -f deploy/miniapp.service ]]; then
  sed "s|/usr/bin/python3|$PY|g; s|WorkingDirectory=/root/finish|WorkingDirectory=$ROOT|g" \
    deploy/miniapp.service > /etc/systemd/system/miniapp.service
  systemctl daemon-reload
  systemctl enable miniapp >/dev/null 2>&1 || true
  echo "   ✅ miniapp.service → $PY"
fi

echo "▶ База знаний..."
kb_ok=false
if [[ -f knowledge_db/chroma.sqlite3 ]] && "$PY" -c "
import chroma_sqlite_fix
import chromadb
c = chromadb.PersistentClient(path='knowledge_db')
print('faq:', c.get_collection('faq').count())
" 2>/dev/null; then
  echo "   knowledge_db OK"
  kb_ok=true
fi

if ! $kb_ok || $REBUILD; then
  if $kb_ok && $REBUILD; then
    echo "   --rebuild-db: пересобираю..."
  else
    echo "   Пересобираю knowledge_db..."
  fi
  if "$PY" build_database.py; then
    echo "   ✅ knowledge_db готова"
  else
    echo "   ❌ Ошибка build_database.py — см. вывод выше"
  fi
fi

echo "▶ Nginx + Mini App (статика + SSL)..."
if [[ -f deploy/stabilize_miniapp.sh ]]; then
  DOMAIN="$DOMAIN" bash deploy/stabilize_miniapp.sh || true
else
  echo "   ⚠️  deploy/stabilize_miniapp.sh не найден"
fi

echo "▶ Бот..."
systemctl restart bot
systemctl restart miniapp 2>/dev/null || true
sleep 2
if systemctl is-active --quiet bot; then
  echo "   ✅ bot работает"
else
  echo "   ❌ bot не запустился:"
  journalctl -u bot -n 25 --no-pager || true
fi
if systemctl is-active --quiet miniapp 2>/dev/null; then
  echo "   ✅ miniapp работает"
fi

echo "=== Готово ==="
