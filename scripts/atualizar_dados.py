"""Atalho de linha de comando para `python -m src.cli atualizar`.

Mantido para compatibilidade com o cron/GitHub Action existente
(ver .github/workflows/atualizar-dados.yml).

Uso:
    python scripts/atualizar_dados.py --uf SP --ano 2026
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.cli import app

if __name__ == "__main__":
    app(["atualizar", *sys.argv[1:]])
