#!/bin/bash
# Заливка ASCII-имён фото (фикс 404 на iPhone) на VPS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VPS="${VPS:-root@148.135.211.59}"
FINISH="$ROOT/finish"
SCP='scp -o ServerAliveInterval=30'
SSH='ssh -o ServerAliveInterval=30'

$SCP "$FINISH/resources/files/monitrading-pair-legend.png" \
     "$FINISH/resources/files/how-to-share-monitoring.jpg" \
     "$VPS:~/finish/resources/files/"
$SCP "$FINISH/resources/resources.json" "$VPS:~/finish/resources/resources.json"
$SCP "$FINISH/miniapp/index.html" "$VPS:~/finish/miniapp/index.html"

$SSH "$VPS" 'chmod 644 ~/finish/resources/files/monitrading-pair-legend.png ~/finish/resources/files/how-to-share-monitoring.jpg ~/finish/resources/resources.json ~/finish/miniapp/index.html'

echo "✅ Готово. В Mini App закройте карточку и откройте «Условные обозначения» снова."
