"""Camada de persistência local: leitura e gravação dos dados de setores de risco e chuva.

Centraliza o formato de arquivo (GeoPackage para setores, CSV para chuva) para que
ingest e dashboard não dupliquem a lógica de I/O.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.config import CAMADA_SETORES


def setores_existem(caminho: Path) -> bool:
    return caminho.exists()


def ler_setores(caminho: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(caminho, layer=CAMADA_SETORES)


def salvar_setores(gdf: gpd.GeoDataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(caminho, layer=CAMADA_SETORES, driver="GPKG")


def chuva_existe(caminho: Path) -> bool:
    return caminho.exists()


def ler_chuva(caminho: Path) -> pd.DataFrame:
    return pd.read_csv(caminho, parse_dates=["data_hora"])


def salvar_chuva(df: pd.DataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False)
