"""Geometria dos setores de risco e acumulação temporal de chuva.

Centroides dos setores (por setor e por município) e chuva acumulada numa
janela de horas *em relação à leitura mais recente disponível na série*,
que pode ser de algumas horas atrás, não necessariamente "agora".
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

CRS_METRICO = "EPSG:5880"  # SIRGAS 2000 / Brasil Polícônica, boa para distâncias em todo o país


def centroides_metricos(setores: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Centroide de cada setor, projetado em `CRS_METRICO` (bom para distâncias/médias em metros)."""
    return setores.to_crs(CRS_METRICO).geometry.centroid


def centroides_4326(setores: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Centroide de cada setor em EPSG:4326 (lat/lon), pronto para geocodificação/APIs externas."""
    return centroides_metricos(setores).to_crs("EPSG:4326")


def centroides_municipio(setores: gpd.GeoDataFrame) -> tuple[list[str], list[tuple[float, float]]]:
    """Um ponto representativo por município: centroide médio (métrico) dos setores daquele município.

    Não é dissolve de geometria, a média dos centroides dos setores já é
    suficiente para escolher um ponto de consulta razoável para APIs por
    coordenada (Open-Meteo). Retorna `(municipios, pontos)` em
    correspondência posicional, `pontos` já em `(lat, lon)`.
    """
    centroides = centroides_metricos(setores)
    df_centroides = pd.DataFrame({
        "munic": setores["munic"].values,
        "x": centroides.x.values,
        "y": centroides.y.values,
    })
    medios = df_centroides.groupby("munic")[["x", "y"]].mean()
    municipios = list(medios.index)

    pontos_metricos = gpd.GeoSeries(
        [Point(linha.x, linha.y) for linha in medios.itertuples()], crs=centroides.crs
    )
    pontos_4326 = pontos_metricos.to_crs("EPSG:4326")
    pontos = [(pt.y, pt.x) for pt in pontos_4326]
    return municipios, pontos


def chuva_acumulada(
    serie_estacao: pd.DataFrame, referencia: pd.Timestamp, horas: int
) -> float:
    janela = serie_estacao[
        (serie_estacao["data_hora"] > referencia - pd.Timedelta(hours=horas))
        & (serie_estacao["data_hora"] <= referencia)
    ]
    if janela.empty or janela["chuva_mm"].isna().all():
        return float("nan")
    return float(janela["chuva_mm"].sum(skipna=True))
