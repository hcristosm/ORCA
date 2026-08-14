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

JANELAS_CHUVA = (24, 72)
LIMIAR_ATENCAO_MM_PADRAO = 100.0


def validar_uf(uf: str) -> str:
    uf_norm = uf.strip().upper()
    if uf_norm not in UFS_VALIDAS:
        raise ValueError(f"UF inválida: {uf!r}. Use uma sigla de 2 letras, ex.: SP.")
    return uf_norm


def caminho_setores(uf: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"risco_{uf.lower()}.gpkg"


def caminho_chuva(uf: str, ano: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"chuva_{uf.lower()}_{ano}.csv"


def caminho_chuva_ana(uf: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"chuva_ana_{uf.lower()}.csv"


def caminho_zip_inmet(ano: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"inmet_{ano}.zip"


def caminho_manifesto_inmet(uf: str, ano: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"inmet_manifest_{uf.lower()}_{ano}.json"


def caminho_manifesto_cprm(uf: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"cprm_manifest_{uf.lower()}.json"
