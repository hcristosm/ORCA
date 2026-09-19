"""CLI unificada do ORCA: ingestão de setores e exportação do dashboard.

Os dois comandos invocados pelos workflows:

    python -m src.cli ingerir-setores --diretorio data   # mensal (CPRM/SGB)
    python -m src.cli atualizar-nacional --ufs SP,RJ     # diário (Open-Meteo)

Comandos por UF, de uso manual/pontual:

    python -m src.cli ingest-cprm --uf SP
    python -m src.cli exportar-dashboard --uf SP
"""

from __future__ import annotations

from pathlib import Path

import typer

from src.config import DASHBOARD_DATA_DIR, DATA_DIR, UFS_VALIDAS, caminho_setores
from src.export.dashboard_data import exportar_dashboard
from src.export.nacional import ORCAMENTO_ALVO_PADRAO, exportar_nacional
from src.ingest.cprm import CPRMFetchError
from src.ingest.cprm import ingerir_uf as ingerir_cprm
from src.storage_cache_openmeteo import CacheOpenMeteo

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


@app.command("exportar-dashboard")
def exportar_dashboard_cmd(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    saida: Path = typer.Option(
        None, "--saida", help="Diretório de saída (padrão: docs/dashboard/data/)"
    ),
) -> None:
    """Pré-computa a chuva por setor e gera os arquivos estáticos do dashboard (GeoJSON/JSON)."""
    saida_dir = saida or DASHBOARD_DATA_DIR
    meta = exportar_dashboard(uf, diretorio, saida_dir, cache_openmeteo=CacheOpenMeteo())
    typer.echo(f"{meta['total_setores']} setores exportados para {saida_dir}")


@app.command("atualizar-nacional")
def atualizar_nacional_cmd(
    ufs: str = typer.Option(
        ",".join(sorted(UFS_VALIDAS)), "--ufs",
        help="Lista de UFs separada por vírgula, ex.: SP,RJ,MG. Padrão: todas as 27.",
    ),
    orcamento_alvo: int = typer.Option(
        ORCAMENTO_ALVO_PADRAO, "--orcamento-alvo",
        help=(
            "Teto de pontos de grade distintos para os setores "
            "(não inclui a série por município nem retries)"
        ),
    ),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    saida: Path = typer.Option(DASHBOARD_DATA_DIR, "--saida", help="Diretório de saída do dashboard"),
) -> None:
    """Exporta o dashboard para várias UFs de uma vez, compartilhando 1 grade
    espacial nacional para caber no rate limit da Open-Meteo.

    Não ingere os setores: eles devem ter sido ingeridos antes, pelo comando
    mensal `ingerir-setores` (a CPRM/SGB é instável e passou a rodar separada
    da atualização diária).

    `--orcamento-alvo` calibra só os pontos de grade dos setores; a série por
    município não entra nessa conta. As UFs são exportadas concorrentemente;
    quem garante não estourar os tetos de hora/minuto da Open-Meteo é o rate
    limiter compartilhado em `src/ingest/openmeteo.py`, não uma pausa fixa.
    """
    lista_ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]

    cache = CacheOpenMeteo()
    try:
        resultados = exportar_nacional(
            lista_ufs, diretorio, saida,
            orcamento_alvo=orcamento_alvo, cache_openmeteo=cache,
        )
    except ValueError as exc:
        typer.echo(f"FALHA na exportação nacional: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{len(resultados)}/{len(lista_ufs)} UF(s) exportada(s) para {saida}.")

    ufs_com_falha = [uf for uf in lista_ufs if uf not in resultados]
    if ufs_com_falha:
        typer.echo(f"Falha na exportação do dashboard: {', '.join(ufs_com_falha)}", err=True)
    if not resultados:
        raise typer.Exit(code=1)


@app.command("ingerir-setores")
def ingerir_setores_cmd(
    ufs: str = typer.Option(",".join(sorted(UFS_VALIDAS)), "--ufs", help="UFs separadas por vírgula. Padrão: todas as 27."),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    backoff_factor: float = typer.Option(5.0, "--backoff-factor", help="Fator de backoff entre tentativas (0 nos testes)"),
) -> None:
    """Ingere os setores de risco da CPRM/SGB para o branch `dados-base`.

    Roda mensalmente, separado da atualização diária: setor de risco é
    resultado de levantamento de campo e muda em escala de meses, então
    rebaixá-lo todo dia só expunha o dashboard à instabilidade da SGB.
    Sai com código 1 se qualquer UF falhar -- dado congelado por um mês é
    pior que uma notificação a mais.
    """
    lista_ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]
    falhas = []
    for uf in lista_ufs:
        try:
            # `permitir_cache=False`: o cache local aqui é o próprio
            # `dados-base` recém-extraído pelo workflow, então aceitá-lo
            # transformaria a SGB fora do ar em 27 sucessos silenciosos.
            ingerir_cprm(
                uf, caminho_setores(uf, diretorio),
                backoff_factor=backoff_factor, permitir_cache=False,
            )
        except (CPRMFetchError, ValueError) as exc:
            typer.echo(f"  FALHA na CPRM/SGB ({uf}): {exc}", err=True)
            falhas.append(uf)

    typer.echo(f"{len(lista_ufs) - len(falhas)}/{len(lista_ufs)} UF(s) ingerida(s).")
    if falhas:
        typer.echo(f"Falha na ingestão CPRM: {', '.join(falhas)}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
