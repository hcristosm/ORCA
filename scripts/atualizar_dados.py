"""Atalho de linha de comando para `python -m src.cli atualizar-nacional`.

Mantido para compatibilidade com o cron/GitHub Action existente
(ver .github/workflows/atualizar-dados.yml).

Uso:
    python scripts/atualizar_dados.py --ufs SP,RJ --ano 2026
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.cli import app


def _construir_argumentos(argv: list[str]) -> list[str]:
    """Repassa os argumentos recebidos para `atualizar-nacional`.

    Quando `--ufs` é passado com valor vazio (significando "todas as UFs"),
    a flag é omitida por completo para que o próprio comando `atualizar-nacional`
    aplique seu padrão (todas as UFs de `UFS_VALIDAS`), em vez de repassar
    `--ufs ""`.
    """
    argumentos = ["atualizar-nacional"]
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--ufs" and i + 1 < len(argv):
            valor = argv[i + 1]
            if valor:
                argumentos.extend(["--ufs", valor])
            i += 2
            continue
        argumentos.append(arg)
        i += 1
    return argumentos


if __name__ == "__main__":
    app(_construir_argumentos(sys.argv[1:]))
