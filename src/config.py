"""Constantes e convenções de caminho compartilhadas entre ingest, processing e dashboard."""

from __future__ import annotations

from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ_PROJETO / "data"
DASHBOARD_DATA_DIR = RAIZ_PROJETO / "docs" / "dashboard" / "data"

UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

CAMADA_SETORES = "setores_risco"

LIMIAR_ATENCAO_MM_PADRAO = 100.0


def validar_uf(uf: str) -> str:
    uf_norm = uf.strip().upper()
    if uf_norm not in UFS_VALIDAS:
        raise ValueError(f"UF inválida: {uf!r}. Use uma sigla de 2 letras, ex.: SP.")
    return uf_norm


def caminho_setores_beluga(uf: str, data_dir: Path = DATA_DIR) -> Path:
    """Setores de uma UF baixados do BELUGA.

    Nome próprio (`beluga_<uf>.gpkg`, não `risco_<uf>.gpkg`): é exigência do
    contrato de dados do BELUGA, e impede que um GeoPackage antigo da
    ingestão direta da CPRM/SGB, ainda no disco de alguém, seja lido como se
    fosse o novo.
    """
    return data_dir / f"beluga_{uf.lower()}.gpkg"


def caminho_manifesto_beluga(data_dir: Path = DATA_DIR) -> Path:
    """Cópia local do `manifest.json` do BELUGA (nacional, uma por download).

    É de onde o selo de atualização do dashboard tira a data da coleta e as
    fontes de cada UF: sem ele o selo mostraria "data indisponível" para
    sempre, sem avisar ninguém.
    """
    return data_dir / "beluga_manifest.json"


def caminho_cache_openmeteo(data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "cache" / "openmeteo.sqlite"


def caminho_indice_setores(dashboard_dir: Path = DASHBOARD_DATA_DIR) -> Path:
    """Índice nacional leve de setores, usado pela tela "Perto de mim" do celular."""
    return dashboard_dir / "setores_pontos.json"
