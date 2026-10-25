#!/bin/bash
# HTTPS для Mini App. Вызывает fix_certbot_vps.sh если certbot сломан.
# Запуск на VPS: bash ~/finish/deploy/enable_ssl.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$DIR/fix_certbot_vps.sh"
