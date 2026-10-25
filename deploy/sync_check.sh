#!/bin/bash
# Сверка файлов Mac (finish/) и VPS (~/finish/) по SHA-256.
#
# Запуск на Mac из корня проекта:
#   bash finish/deploy/sync_check.sh
#   bash finish/deploy/sync_check.sh --miniapp      # только miniapp
#   bash finish/deploy/sync_check.sh --with-videos  # + видео/PDF (долго)
#   bash finish/deploy/sync_check.sh --all          # показать и совпадающие файлы
#
# Переменные:
#   VPS=root@IP REMOTE=~/finish bash finish/deploy/sync_check.sh
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCAL="${LOCAL_DIR:-$ROOT/finish}"
VPS="${VPS:-root@148.135.211.59}"
REMOTE="${REMOTE:-~/finish}"

ONLY_MINIAPP=false
WITH_VIDEOS=false
WITH_DB=false
SHOW_ALL=false
SHOW_DIFF=false
MISSING_FILES=()
DIFF_FILES=()

# Одно SSH-соединение на всю проверку (пароль спросит 1 раз, не на каждый файл)
SSH_CTL="${TMPDIR:-/tmp}/emar-sync-$$"
SSH_OPTS=(
  -o ConnectTimeout=15
  -o ControlMaster=auto
  -o "ControlPath=$SSH_CTL"
  -o ControlPersist=120
)

cleanup_ssh() {
  ssh -O exit -o "ControlPath=$SSH_CTL" "$VPS" 2>/dev/null || true
}
trap cleanup_ssh EXIT

ssh_cmd() {
  # -n: не читать stdin (иначе ssh внутри while съедает список файлов)
  ssh -n "${SSH_OPTS[@]}" "$VPS" "$@"
}

for arg in "$@"; do
  case "$arg" in
    --miniapp) ONLY_MINIAPP=true ;;
    --with-videos) WITH_VIDEOS=true ;;
    --with-db) WITH_DB=true ;;
    --all) SHOW_ALL=true ;;
    --diff) SHOW_DIFF=true ;;
    -h|--help)
      echo "Использование: bash finish/deploy/sync_check.sh [--miniapp] [--with-videos] [--with-db] [--all] [--diff]"
      echo ""
      echo "  Сравнение по содержимому файлов (SHA-256), не по дате/размеру."
      echo "  knowledge_db по умолчанию пропускается (собирается на VPS)."
      echo "  --with-db сравнить и knowledge_db (обычно не нужно)"
      echo "  --all   показать и совпадающие файлы"
      echo "  --diff  для разных файлов показать diff (первые 40 строк)"
      exit 0
      ;;
  esac
done

echo "════════════════════════════════════════"
echo "  Сверка Mac ↔ VPS"
echo "  Локально: $LOCAL"
echo "  Сервер:   $VPS:$REMOTE"
echo "════════════════════════════════════════"

if [[ ! -d "$LOCAL" ]]; then
  echo "❌ Папка не найдена: $LOCAL"
  exit 1
fi

# Проверка SSH (без BatchMode — работает и с паролем)
echo ""
echo "▶ Подключение к серверу..."
if ! ssh_cmd "test -d $REMOTE"; then
  echo "❌ Не удалось подключиться к $VPS"
  echo "   или на сервере нет папки $REMOTE"
  echo ""
  echo "   Проверьте вручную:"
  echo "   ssh $VPS"
  echo "   ls -la $REMOTE"
  exit 1
fi
echo "   ✅ SSH OK, папка $REMOTE найдена"

# Абсолютный путь на VPS (~ в кавычках в sha256sum не раскрывается)
REMOTE_DIR=$(ssh_cmd "cd $REMOTE 2>/dev/null && pwd" || true)
if [[ -z "$REMOTE_DIR" ]]; then
  echo "❌ Не удалось определить путь $REMOTE на сервере"
  exit 1
fi
echo "   Путь на VPS: $REMOTE_DIR"

OK=0
DIFF=0
MISS_REMOTE=0

build_file_list() {
  if $ONLY_MINIAPP; then
    (cd "$LOCAL" && find miniapp -type f ! -name '.DS_Store' 2>/dev/null | sort)
    return
  fi

  local find_args=(
    .
    -type f
    ! -path './.env'
    ! -path './venv/*'
    ! -path './__pycache__/*'
    ! -name '.DS_Store'
    ! -name 'dialogs_state.json'
    ! -name 'kb_build_checkpoint.json'
  )

  if ! $WITH_VIDEOS; then
    find_args+=( ! -path './resources/files/*' )
  fi

  # knowledge_db собирается на VPS — локальная копия часто устаревшая
  if ! $WITH_DB; then
    find_args+=( ! -path './knowledge_db/*' )
  fi

  (cd "$LOCAL" && find "${find_args[@]}" 2>/dev/null | sed 's|^\./||' | sort)
}

check_one() {
  local rel="$1"
  local local_file="$LOCAL/$rel"

  if [[ ! -f "$local_file" ]]; then
    return
  fi

  local local_sum remote_sum
  local_sum=$(shasum -a 256 "$local_file" | awk '{print $1}')
  remote_sum=$(ssh_cmd "sha256sum \"$REMOTE_DIR/$rel\" 2>/dev/null" | awk '{print $1}' || true)

  if [[ -z "$remote_sum" ]]; then
    echo "   ❌ нет на VPS:  $rel"
    MISSING_FILES+=("$rel")
    MISS_REMOTE=$((MISS_REMOTE + 1))
    return
  fi

  if [[ "$local_sum" == "$remote_sum" ]]; then
    OK=$((OK + 1))
    if $SHOW_ALL; then
      echo "   ✅ $rel"
    fi
  else
    echo "   ❌ РАЗНОЕ содержимое: $rel"
    echo "      Mac: ${local_sum:0:12}…  VPS: ${remote_sum:0:12}…"
    DIFF_FILES+=("$rel")
    DIFF=$((DIFF + 1))
    if $SHOW_DIFF; then
      echo "      --- diff (Mac vs VPS, до 40 строк) ---"
      ssh_cmd "cat \"$REMOTE_DIR/$rel\" 2>/dev/null" > "/tmp/emar-remote-$$" || true
      diff -u "/tmp/emar-remote-$$" "$local_file" 2>/dev/null | head -40 | sed 's/^/      /' || true
      rm -f "/tmp/emar-remote-$$"
      echo "      ---"
    fi
  fi
}

echo ""
if $ONLY_MINIAPP; then
  echo "▶ Режим: только miniapp/"
elif $WITH_VIDEOS; then
  echo "▶ Режим: все файлы включая resources/files/ (может занять время)"
elif $WITH_DB; then
  echo "▶ Режим: код + knowledge_db"
else
  echo "▶ Режим: код и каталог (без видео/PDF и knowledge_db)"
fi
echo "▶ Сравнение: SHA-256 (содержимое файлов, байт в байт)"
echo ""

FILES=()
while IFS= read -r _line; do
  FILES+=("$_line")
done < <(build_file_list)
TOTAL=${#FILES[@]}
echo "▶ Файлов к проверке: $TOTAL"
echo ""

for rel in "${FILES[@]}"; do
  [[ -n "$rel" ]] || continue
  check_one "$rel"
done

echo ""
echo "────────────────────────────────────────"
echo "Проверено файлов: $TOTAL"
echo "Итого: ✅ $OK одинаковых | ❌ $DIFF разных | нет на VPS: $MISS_REMOTE"

if [[ $DIFF -eq 0 && $MISS_REMOTE -eq 0 ]]; then
  echo ""
  echo "✅ Локальная finish/ и VPS совпадают."
  exit 0
fi

echo ""
echo "Чтобы залить Mac → VPS:"
if [[ ${#MISSING_FILES[@]} -gt 0 || ${#DIFF_FILES[@]} -gt 0 ]]; then
  echo ""
  echo "Один файл (scp):"
  for rel in "${MISSING_FILES[@]}" "${DIFF_FILES[@]}"; do
    echo "  scp \"$LOCAL/$rel\" $VPS:$REMOTE_DIR/$rel"
  done
  echo ""
  has_py=false
  for rel in "${MISSING_FILES[@]}" "${DIFF_FILES[@]}"; do
    [[ "$rel" == *.py ]] && has_py=true
  done
  if $has_py; then
    echo "После заливки .py-файлов перезапустите бота:"
    echo "  ssh $VPS systemctl restart bot"
    echo ""
  fi
fi
echo "Всё сразу:"
echo "  cd \"$ROOT\" && bash deploy.sh"
if $ONLY_MINIAPP || [[ $DIFF -gt 0 && $DIFF -le 5 ]]; then
  echo "Или только miniapp:"
  echo "  scp \"$LOCAL/miniapp/\"* $VPS:$REMOTE_DIR/miniapp/"
fi
exit 1
