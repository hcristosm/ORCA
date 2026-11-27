"""CLI unificada do ORCA: download dos setores e exportação do dashboard.

Os dois comandos invocados pelo workflow diário:

    python -m src.cli baixar-beluga --diretorio data     # setores (BELUGA v1)
    python -m src.cli atualizar-nacional --ufs SP,RJ     # chuva (Open-Meteo)

Comando por UF, de uso manual/pontual:

    python -m src.cli exportar-dashboard --uf SP
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from src.config import (
    DASHBOARD_DATA_DIR,
    DATA_DIR,
    UFS_VALIDAS,
    caminho_cache_openmeteo,
)
from src.export.dashboard_data import exportar_dashboard
from src.export.indice_setores import gerar_indice_setores
from src.export.nacional import ORCAMENTO_ALVO_PADRAO, exportar_nacional
from src.ingest.beluga import BelugaFetchError, baixar_setores, contagens_publicadas
from src.storage_cache_openmeteo import CacheOpenMeteo

app = typer.Typer(add_completion=False)


@app.command("baixar-beluga")
def baixar_beluga_cmd(
    ufs: str = typer.Option(
        ",".join(sorted(UFS_VALIDAS)), "--ufs",
        help="UFs separadas por vírgula. Padrão: todas as 27.",
    ),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    publicado: Path = typer.Option(
        None, "--publicado",
        help=(
            "Diretório com os meta_<uf>.json já publicados (gh-pages), de onde sai "
            "o piso de setores por UF. Sem ele, não há piso por UF."
        ),
    ),
    timeout: float = typer.Option(120.0, "--timeout", help="Timeout por requisição, em segundos"),
) -> None:
    """Baixa os setores de risco da publicação v1 do BELUGA.

    Confere o contrato, as 27 UFs, o sha256 e a contagem de feições de cada
    arquivo, e recusa UF que venha com menos setores que a publicação anterior
    do ORCA. Sai com 1 se qualquer UF falhar: a UF afetada fica com o dado
    anterior e o run tem de ficar vermelho, porque setor congelado em silêncio
    é o jeito de a coleta parar por meses sem ninguém ver.
    """
    lista_ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]
    anteriores = contagens_publicadas(publicado) if publicado else {}

    try:
        baixadas, falhas = baixar_setores(
            lista_ufs, diretorio, anteriores=anteriores, timeout=timeout,
        )
    except BelugaFetchError as exc:
        # Falha no manifest: nenhuma UF foi tocada, todas ficam com o dado anterior.
        typer.echo(f"FALHA no manifest do BELUGA: {exc}", err=True)
        raise typer.Exit(code=1)

    total = sum(baixadas.values())
    typer.echo(f"{len(baixadas)}/{len(lista_ufs)} UF(s) baixada(s) do BELUGA, {total} setores.")
    if falhas:
        # O motivo vai para o log do run, não só o nome da UF: o CONTRIBUTING
        # manda medir o resultado nos logs, e "falhou" não distingue sha256 de
        # arquivo truncado nem de publicação que encolheu.
        for uf_falha, motivo in falhas.items():
            typer.echo(f"  FALHA no BELUGA ({uf_falha}): {motivo}", err=True)
        typer.echo(
            f"Falha no BELUGA: {', '.join(falhas)} (ficam com o dado anterior)", err=True
        )
        raise typer.Exit(code=1)


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
    cache = CacheOpenMeteo(caminho_cache_openmeteo(diretorio))
    meta = exportar_dashboard(uf, diretorio, saida_dir, cache_openmeteo=cache)
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

    Não baixa os setores: eles devem ter sido baixados antes, pelo comando
    `baixar-beluga`, que roda no mesmo workflow mas num passo próprio e fatal.

    `--orcamento-alvo` calibra só os pontos de grade dos setores; a série por
    município não entra nessa conta. As UFs são exportadas concorrentemente;
    quem garante não estourar os tetos de hora/minuto da Open-Meteo é o rate
    limiter compartilhado em `src/ingest/openmeteo.py`, não uma pausa fixa.
    """
    lista_ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]

    cache = CacheOpenMeteo(caminho_cache_openmeteo(diretorio))
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


@app.command("indexar-setores")
def indexar_setores_cmd(
    dados: Path = typer.Option(
        DASHBOARD_DATA_DIR, "--dados", help="Diretório de dados do dashboard (docs/dashboard/data)"
    ),
) -> None:
    """Gera o índice nacional leve de setores para a tela "Perto de mim" do celular.

    Roda depois da mescla com o gh-pages. Sai com 1 quando não há
    `ufs_disponiveis.json` legível: o workflow marca o passo com
    `continue-on-error`, então a falha fica visível sem bloquear a publicação.
    """
    total = gerar_indice_setores(dados)
    if total is None:
        typer.echo(f"Índice de setores não gerado: sem ufs_disponiveis.json legível em {dados}.", err=True)
        raise typer.Exit(code=1)
    n_ufs = len(json.loads((dados / "ufs_disponiveis.json").read_text()))
    typer.echo(f"Índice de setores: {total} setores de {n_ufs} UF(s).")


if __name__ == "__main__":
    app()
