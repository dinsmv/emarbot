#!/bin/bash
# Обновление всего на VPS одной командой (запускать на Mac).
#
#   cd "/Users/madinanasimova/Documents/личное/автоматизация/bot_emar"
#   bash deploy.sh              # код + каталог (без тяжёлых видео)
#   bash deploy.sh --full         # + все PDF/видео (~1.7 GB)
#   bash deploy.sh --rebuild-db   # + пересборка knowledge_db на VPS
#
# Переменные (при необходимости):
#   VPS=root@148.135.211.59 REMOTE=~/finish bash deploy.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FINISH="$ROOT/finish"
VPS="${VPS:-root@148.135.211.59}"
REMOTE="${REMOTE:-~/finish}"
DOMAIN="${DOMAIN:-materials.emarbot.ru}"

FULL=false
REBUILD_DB=false
for arg in "$@"; do
  case "$arg" in
    --full) FULL=true ;;
    --rebuild-db) REBUILD_DB=true ;;
    -h|--help)
      echo "Использование: bash deploy.sh [--full] [--rebuild-db]"
      exit 0
      ;;
  esac
done

RSYNC_SSH='ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10'
RSYNC_OPTS=(-avz --partial --progress --timeout=300 -e "$RSYNC_SSH")

echo "═══════════════════════════════════════"
echo "  EMAR Bot — деплой на $VPS"
echo "═══════════════════════════════════════"

# ── 1. Пакет finish/ — единственный источник (корневые дубликаты удалены) ──
echo ""
echo "▶ Пакет finish/..."
mkdir -p "$FINISH/deploy" "$FINISH/miniapp" "$FINISH/resources/files"

if [[ ! -f "$FINISH/bot.py" ]]; then
  echo "   ❌ Нет $FINISH/bot.py — проверьте папку finish/"
  exit 1
fi

echo "   Пакет готов: $(du -sh "$FINISH" | cut -f1)"

# ── 2. Заливка на VPS ──
echo ""
echo "▶ Загрузка на сервер..."
ssh "$VPS" "mkdir -p $REMOTE/deploy $REMOTE/miniapp $REMOTE/resources/files"

# Код и скрипты (без .env — не перезаписываем ключи на сервере)
rsync "${RSYNC_OPTS[@]}" \
  --exclude '.env' \
  --exclude 'knowledge_db/' \
  --exclude 'resources/files/' \
  --exclude '__pycache__/' \
  --exclude '.DS_Store' \
  "$FINISH/" "$VPS:$REMOTE/"

# Тяжёлые материалы — только с --full
if $FULL; then
  echo ""
  echo "▶ Загрузка resources/files/ (~1.7 GB)..."
  if [[ -d "$FINISH/resources/files" ]]; then
    rsync "${RSYNC_OPTS[@]}" "$FINISH/resources/files/" "$VPS:$REMOTE/resources/files/"
  else
    echo "   ⚠️  finish/resources/files/ не найдена локально"
  fi
else
  echo ""
  echo "   ℹ️  Видео/PDF не заливались (добавьте --full для полной синхронизации)"
fi

# ── 3. Обновление на сервере ──
echo ""
echo "▶ Настройка на VPS..."
REBUILD_FLAG=""
$REBUILD_DB && REBUILD_FLAG="--rebuild-db"

ssh "$VPS" "chmod +x $REMOTE/remote_update.sh $REMOTE/recover_vps.sh 2>/dev/null; DOMAIN=$DOMAIN bash $REMOTE/remote_update.sh $REBUILD_FLAG"

echo ""
echo "═══════════════════════════════════════"
echo "  ✅ Деплой завершён"
echo "═══════════════════════════════════════"
echo ""
echo "Проверьте бота в Telegram: /start"
echo "Mini App: https://$DOMAIN/ (нужен SSL + MINIAPP_URL в .env)"
echo ""
echo "Полезные команды на VPS:"
echo "  journalctl -u bot -n 30 --no-pager"
echo "  journalctl -u miniapp -n 20 --no-pager"
echo "  systemctl status bot miniapp"
