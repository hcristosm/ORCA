"""CLI unificada do ORCA: ingestão de dados e atualização periódica.

Uso:
    python -m src.cli ingest-cprm --uf SP
    python -m src.cli ingest-inmet --uf SP --ano 2026
    python -m src.cli atualizar --uf SP --ano 2026
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from src.config import DATA_DIR, caminho_setores
from src.ingest.cprm import CPRMFetchError, ingerir_uf as ingerir_cprm
from src.ingest.inmet import INMETFetchError, ingerir_uf as ingerir_inmet

app = typer.Typer(add_completion=False)


@app.command("ingest-cprm")
def ingest_cprm(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    output: Path = typer.Option(
        None, "--output", help="Caminho do GeoPackage de saída (padrão: data/risco_<uf>.gpkg)"
    ),
    timeout: float = typer.Option(30.0, help="Timeout por requisição, em segundos"),
    max_retries: int = typer.Option(3, help="Número máximo de tentativas por página"),
) -> None:
    """Baixa os setores de risco geológico da CPRM/SGB para uma UF."""
    out = output or caminho_setores(uf, DATA_DIR)
    gdf = ingerir_cprm(uf, out, timeout=timeout, max_retries=max_retries)
    typer.echo(f"{len(gdf)} setores de risco salvos em {out}")


@app.command("ingest-inmet")
def ingest_inmet(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(..., "--ano", help="Ano dos dados históricos, ex.: 2026"),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
) -> None:
    """Baixa dados pluviométricos horários do INMET para uma UF/ano."""
    df = ingerir_inmet(uf, ano, diretorio)
    typer.echo(f"{len(df)} leituras horárias salvas em {diretorio}/chuva_{uf.lower()}_{ano}.csv")


@app.command()
def atualizar(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(..., "--ano", help="Ano dos dados históricos do INMET"),
) -> None:
    """Atualiza os dados locais de setores de risco (CPRM/SGB) e chuva (INMET).

    Pensado para ser chamado manualmente, via cron, ou por uma GitHub Action
    (ver .github/workflows/atualizar-dados.yml).
    """
    uf_norm = uf.strip().upper()
    falhas = []

    typer.echo(f"[{datetime.now(timezone.utc).isoformat()}] Atualizando setores de risco ({uf_norm})...")
    try:
        setores = ingerir_cprm(uf_norm, caminho_setores(uf_norm, DATA_DIR))
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
