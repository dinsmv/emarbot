#!/bin/bash
# Диагностика и починка на VPS:
#   cd ~/finish && bash deploy/fix_vps.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 1. Зависимости ==="
pip3 install -r requirements.txt -q

echo ""
echo "=== 2. База знаний ==="
if [ ! -d knowledge_db ] || [ ! -f knowledge_db/chroma.sqlite3 ]; then
  echo "knowledge_db не найдена — пересобираю..."
  python3 build_database.py
else
  echo "knowledge_db есть ($(du -sh knowledge_db | cut -f1))"
  python3 -c "
import chromadb
c = chromadb.PersistentClient(path='knowledge_db')
try:
    col = c.get_collection('faq')
    print('Коллекция faq:', col.count(), 'записей')
except Exception as e:
    print('Ошибка коллекции:', e)
    raise SystemExit(1)
" || python3 build_database.py
fi

echo ""
echo "=== 3. Mini App ==="
bash deploy/setup_miniapp_vps.sh
sleep 1
if curl -sf http://127.0.0.1:8765/resources.json | head -c 80; then
  echo ""
  echo "✅ Mini App отвечает"
else
  echo "❌ Mini App не отвечает — смотрите: journalctl -u miniapp -n 30"
fi

echo ""
echo "=== 4. Тест запуска бота ==="
python3 -c "
import chromadb
from dotenv import load_dotenv
load_dotenv()
c = chromadb.PersistentClient(path='knowledge_db')
c.get_collection('faq')
print('Chroma OK')
" || exit 1

echo ""
echo "=== 5. Перезапуск бота ==="
systemctl restart bot
sleep 2
systemctl status bot --no-pager | head -15

echo ""
echo "=== Готово ==="
echo "Если bot failed — пришлите вывод:"
echo "  journalctl -u bot -n 40 --no-pager"
