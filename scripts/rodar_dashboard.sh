#!/usr/bin/env bash
# Sobe um servidor HTTP local e abre o dashboard do ORCA.
# Uso: scripts/rodar_dashboard.sh [porta]
set -euo pipefail

PORTA="${1:-8000}"
DIRETORIO_RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Servindo docs/ em http://localhost:${PORTA}/dashboard/ (Ctrl+C para parar)"
cd "$DIRETORIO_RAIZ"
python3 -m http.server "$PORTA" --directory docs
