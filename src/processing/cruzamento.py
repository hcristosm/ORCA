"""Cruzamento espacial e temporal entre setores de risco geológico e chuva.

Para cada setor de risco (polígono da CPRM/SGB), encontra a estação
pluviométrica do INMET mais próxima e calcula a chuva acumulada nas últimas
24h e 72h *em relação à leitura mais recente disponível na série* — que, por
causa da defasagem do pacote histórico do INMET (ver src/ingest/inmet.py),
pode ser de alguns dias atrás, não necessariamente "agora".
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config import JANELAS_CHUVA as JANELAS_PADRAO
from src.config import LIMIAR_ATENCAO_MM_PADRAO

CRS_METRICO = "EPSG:5880"  # SIRGAS 2000 / Brasil Polícônica — boa para distâncias em todo o país


def _estacoes_para_pontos(chuva_df: pd.DataFrame) -> gpd.GeoDataFrame:
    estacoes = chuva_df.drop_duplicates("codigo_estacao")[
        ["codigo_estacao", "nome_estacao", "latitude", "longitude"]
    ]
    geometry = [Point(lon, lat) for lon, lat in zip(estacoes["longitude"], estacoes["latitude"])]
    return gpd.GeoDataFrame(estacoes, geometry=geometry, crs="EPSG:4326")


def _chuva_acumulada(
    serie_estacao: pd.DataFrame, referencia: pd.Timestamp, horas: int
) -> float:
    janela = serie_estacao[
        (serie_estacao["data_hora"] > referencia - pd.Timedelta(hours=horas))
        & (serie_estacao["data_hora"] <= referencia)
    ]
    if janela.empty or janela["chuva_mm"].isna().all():
        return float("nan")
    return float(janela["chuva_mm"].sum(skipna=True))


def encontrar_estacao_mais_proxima(
    setores: gpd.GeoDataFrame, chuva_df: pd.DataFrame
) -> gpd.GeoDataFrame:
    """Para cada setor, acha a estação pluviométrica mais próxima (distância em km)."""
    estacoes = _estacoes_para_pontos(chuva_df)

    centroides_m = setores.to_crs(CRS_METRICO)
    centroides_m = centroides_m.set_geometry(centroides_m.geometry.centroid)
    estacoes_m = estacoes.to_crs(CRS_METRICO)

    pareado = gpd.sjoin_nearest(
        centroides_m, estacoes_m, how="left", distance_col="distancia_m"
    )

    resultado = setores.copy()
    resultado["codigo_estacao"] = pareado["codigo_estacao"].values
    resultado["nome_estacao"] = pareado["nome_estacao"].values
    resultado["distancia_km"] = (pareado["distancia_m"] / 1000).round(2).values
    return resultado


def calcular_cruzamento(
    setores: gpd.GeoDataFrame,
    chuva_df: pd.DataFrame,
    referencia: pd.Timestamp | None = None,
    janelas: tuple[int, ...] = JANELAS_PADRAO,
) -> gpd.GeoDataFrame:
    """Cruza setores de risco com chuva: acha a estação mais próxima de cada setor
    e calcula a chuva acumulada nas janelas de tempo pedidas (em horas), terminando
    na leitura mais recente disponível na série (`referencia`).
    """
    if chuva_df.empty:
        raise ValueError("chuva_df está vazio; nada para cruzar.")

    ref = referencia or chuva_df["data_hora"].max()

    resultado = encontrar_estacao_mais_proxima(setores, chuva_df)

    series_por_estacao = {
        codigo: grupo[["data_hora", "chuva_mm"]]
        for codigo, grupo in chuva_df.groupby("codigo_estacao")
    }

    for horas in janelas:
        coluna = f"chuva_{horas}h"
        resultado[coluna] = [
            _chuva_acumulada(series_por_estacao[codigo], ref, horas)
            if codigo in series_por_estacao
            else float("nan")
            for codigo in resultado["codigo_estacao"]
        ]

    resultado.attrs["referencia"] = ref
    return resultado


def sinalizar_atencao(
    setores_cruzados: gpd.GeoDataFrame,
    limiar_mm: float = LIMIAR_ATENCAO_MM_PADRAO,
    coluna_chuva: str = "chuva_72h",
) -> gpd.GeoDataFrame:
    """Marca setores cuja chuva acumulada na coluna dada ultrapassa o limiar.

    O valor padrão (100mm/72h) é uma referência ilustrativa comum na literatura de
    risco de deslizamento, não um limiar oficial calibrado para os setores da
    CPRM/SGB — ajuste conforme a fonte técnica disponível para cada região.
    """
    resultado = setores_cruzados.copy()
    resultado["em_atencao"] = resultado[coluna_chuva] >= limiar_mm
    return resultado
