"""Camada de persistência local dos setores de risco.

Centraliza o formato de arquivo (GeoPackage, camada `setores_risco`) para
que ingest e export não dupliquem a lógica de I/O.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from src.config import CAMADA_SETORES


def ler_setores(caminho: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(caminho, layer=CAMADA_SETORES)


def salvar_setores(gdf: gpd.GeoDataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(caminho, layer=CAMADA_SETORES, driver="GPKG")
