"""Script de atualização periódica dos dados do ORCA.

Baixa os setores de risco da CPRM/SGB e a chuva horária do INMET para uma UF,
pensado para ser chamado manualmente, via cron, ou por uma GitHub Action
(ver .github/workflows/atualizar-dados.yml).

Uso:
    python scripts/atualizar_dados.py --uf SP --ano 2026
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

import typer

from src.ingest.cprm import ingerir_uf as ingerir_cprm
from src.ingest.inmet import INMETFetchError, ingerir_uf as ingerir_inmet
from src.ingest.cprm import CPRMFetchError

DATA_DIR = RAIZ_PROJETO / "data"

app = typer.Typer(add_completion=False)


@app.command()
def atualizar(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(..., "--ano", help="Ano dos dados históricos do INMET"),
) -> None:
    """Atualiza os dados locais de setores de risco (CPRM/SGB) e chuva (INMET)."""
    uf_norm = uf.strip().upper()
    falhas = []

    typer.echo(f"[{datetime.now(timezone.utc).isoformat()}] Atualizando setores de risco ({uf_norm})...")
    try:
        setores = ingerir_cprm(uf_norm, DATA_DIR / f"risco_{uf_norm.lower()}.gpkg")
        typer.echo(f"  {len(setores)} setores de risco salvos.")
    except (CPRMFetchError, ValueError) as exc:
        typer.echo(f"  FALHA na CPRM/SGB: {exc}", err=True)
        falhas.append("cprm")

    typer.echo(f"[{datetime.now(timezone.utc).isoformat()}] Atualizando chuva do INMET ({uf_norm}/{ano})...")
    try:
        chuva = ingerir_inmet(uf_norm, ano, DATA_DIR)
        typer.echo(f"  {len(chuva)} leituras horárias salvas.")
    except (INMETFetchError, ValueError) as exc:
        typer.echo(f"  FALHA no INMET: {exc}", err=True)
        falhas.append("inmet")

    marcador = DATA_DIR / "ultima_atualizacao.txt"
    marcador.write_text(
        f"uf={uf_norm}\nano={ano}\natualizado_em={datetime.now(timezone.utc).isoformat()}\n"
        f"falhas={','.join(falhas) if falhas else 'nenhuma'}\n"
    )

    if falhas:
        typer.echo(f"Atualização concluída com falhas em: {', '.join(falhas)}", err=True)
        raise typer.Exit(code=1)

    typer.echo("Atualização concluída com sucesso.")


if __name__ == "__main__":
    app()
