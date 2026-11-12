#!/usr/bin/env bash
# PythonAnywhere 上拉最新代码并让 Web App 重载。
# 手动用法：bash ~/nudge/pythonanywhere/deploy.sh
set -euo pipefail

REPO="${NUDGE_REPO:-$HOME/nudge}"
VENV="${NUDGE_VENV:-$HOME/.virtualenvs/nudge}"

cd "$REPO"
git fetch --depth=1 origin main
git reset --hard origin/main
mkdir -p backend/data

if [ -x "$VENV/bin/pip" ]; then
  "$VENV/bin/pip" install -q -r pythonanywhere/requirements.txt
fi

touch pythonanywhere/wsgi.py
echo "deployed $(git rev-parse --short HEAD) at $(date -Is)"

