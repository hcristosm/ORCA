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

from src.config import DASHBOARD_DATA_DIR, DATA_DIR, caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError, exportar_dashboard
from src.ingest.cprm import CPRMFetchError, ingerir_uf as ingerir_cprm
from src.ingest.inmet import INMETFetchError, ingerir_uf as ingerir_inmet
from src.ingest.ana import ANAFetchError, ingerir_uf as ingerir_ana

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


@app.command("ingest-ana")
def ingest_ana(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    janela_horas: int = typer.Option(
        48, help="Janela de recência (h) para considerar uma estação com dado vivo"
    ),
    max_workers: int = typer.Option(5, help="Requisições em paralelo"),
) -> None:
    """Baixa chuva das estações telemétricas da ANA com dado vivo para uma UF."""
    df = ingerir_ana(uf, diretorio, janela_horas=janela_horas, max_workers=max_workers)
    typer.echo(f"{len(df)} leituras da ANA salvas em {diretorio}/chuva_ana_{uf.lower()}.csv")


@app.command("exportar-dashboard")
def exportar_dashboard_cmd(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(
        datetime.now(timezone.utc).year, "--ano", help="Ano dos dados do INMET a exportar"
    ),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    saida: Path = typer.Option(
        None, "--saida", help="Diretório de saída (padrão: docs/dashboard/data/)"
    ),
) -> None:
    """Pré-computa o cruzamento e gera os arquivos estáticos do dashboard (GeoJSON/JSON)."""
    saida_dir = saida or DASHBOARD_DATA_DIR
    meta = exportar_dashboard(uf, ano, diretorio, saida_dir)
    typer.echo(
        f"{meta['total_setores']} setores exportados para {saida_dir} "
        f"({meta['total_estacoes_inmet']} estações INMET, {meta['total_estacoes_ana']} estações ANA)"
    )


@app.command()
def atualizar(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(..., "--ano", help="Ano dos dados históricos do INMET"),
) -> None:
    """Atualiza os dados locais de setores de risco (CPRM/SGB) e chuva (INMET e, como fonte complementar, ANA).

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

    typer.echo(f"[{datetime.now(timezone.utc).isoformat()}] Atualizando chuva da ANA ({uf_norm})...")
    try:
        chuva_ana = ingerir_ana(uf_norm, DATA_DIR)
        typer.echo(f"  {len(chuva_ana)} leituras da ANA salvas.")
    except (ANAFetchError, ValueError) as exc:
        typer.echo(f"  FALHA na ANA: {exc}", err=True)
        falhas.append("ana")

    typer.echo(f"[{datetime.now(timezone.utc).isoformat()}] Exportando dados do dashboard ({uf_norm})...")
    try:
        meta = exportar_dashboard(uf_norm, ano, DATA_DIR, DASHBOARD_DATA_DIR)
        typer.echo(f"  {meta['total_setores']} setores exportados para {DASHBOARD_DATA_DIR}.")
    except (ExportacaoDashboardError, ValueError) as exc:
        typer.echo(f"  FALHA na exportação do dashboard: {exc}", err=True)
        falhas.append("dashboard")

    falhas_criticas = [f for f in falhas if f not in ("ana", "dashboard")]

    marcador = DATA_DIR / "ultima_atualizacao.txt"
    marcador.write_text(
        f"uf={uf_norm}\nano={ano}\natualizado_em={datetime.now(timezone.utc).isoformat()}\n"
        f"falhas={','.join(falhas) if falhas else 'nenhuma'}\n"
    )

    if falhas_criticas:
        typer.echo(f"Atualização concluída com falhas em: {', '.join(falhas_criticas)}", err=True)
        raise typer.Exit(code=1)

    if falhas:
        typer.echo(
            f"Atualização concluída com sucesso (fonte complementar com falha: {', '.join(falhas)})."
        )
    else:
        typer.echo("Atualização concluída com sucesso.")


if __name__ == "__main__":
    app()
