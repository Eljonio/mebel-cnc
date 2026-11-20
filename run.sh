#!/usr/bin/env bash
# ./run.sh                          — тумба, пенал и общий заказ, тесты
# ./run.sh products/моё.yaml ...    — свои изделия (несколько = один заказ, общий раскрой)
# кухня: .venv/bin/python -m mebel.kitchen products/kuhnya-g.yaml [--preview|--render]  -> out/kuhnya-g/
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f viewer/dist/viewer.bundle.js ] || { npm install --no-audit --no-fund && npm run build; }
[ -f viewer/dist/kitchen.bundle.js ] || { npm install --no-audit --no-fund && npm run build:kitchen; }
if [ $# -gt 0 ]; then .venv/bin/python -m mebel "$@"; exit; fi
.venv/bin/python -m pytest -q
.venv/bin/python -m mebel products/tumba-800.yaml
.venv/bin/python -m mebel products/penal-400.yaml
.venv/bin/python -m mebel products/tumba-800.yaml products/penal-400.yaml
