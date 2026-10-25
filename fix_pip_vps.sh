#!/bin/bash
# Исправление pip + OpenSSL + requests на Ubuntu 20.04
# Запуск на VPS: cd ~/finish && bash fix_pip_vps.sh
set -euo pipefail

echo "=== Исправление pip / OpenSSL / requests ==="

apt-get update -qq
apt-get install -y python3-pip python3-openssl libssl-dev 2>/dev/null || \
  apt-get install -y python3-pip libssl-dev

PIP="python3 -m pip"

# Переустановка pip если сломан
if ! $PIP --version >/dev/null 2>&1; then
  if /usr/local/bin/pip3 --version >/dev/null 2>&1; then
    PIP="/usr/local/bin/pip3"
  else
    curl -fsSL https://bootstrap.pypa.io/pip/3.8/get-pip.py -o /tmp/get-pip.py
    python3 /tmp/get-pip.py
    PIP="python3 -m pip"
  fi
fi

echo "▶ pip: $($PIP --version)"

echo "▶ Обновляю pyopenssl, cryptography, requests..."
$PIP install --upgrade pip setuptools wheel -q
# urllib3<2 — иначе ломается системный certbot (ImportError: appengine)
$PIP install --upgrade --force-reinstall \
  "pyopenssl>=22.0.0" "cryptography>=41.0.0" "urllib3>=1.26.0,<2" "requests>=2.28.0" -q

echo "▶ pysqlite3 для ChromaDB..."
$PIP install pysqlite3-binary -q

echo "▶ Проверка import requests..."
python3 -c "import requests; print('requests OK:', requests.__version__)"
python3 -c "import chroma_sqlite_fix; import chromadb; print('chromadb OK')"

echo ""
echo "✅ Готово! Теперь:"
echo "   cd ~/finish && python3 build_database.py"
echo "   systemctl restart bot miniapp"
echo "   systemctl status bot"
