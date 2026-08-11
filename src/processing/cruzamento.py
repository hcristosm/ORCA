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


def centroides_metricos(setores: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Centroide de cada setor, projetado em `CRS_METRICO` (bom para distâncias/médias em metros)."""
    return setores.to_crs(CRS_METRICO).geometry.centroid


def centroides_4326(setores: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Centroide de cada setor em EPSG:4326 (lat/lon), pronto para geocodificação/APIs externas."""
    return centroides_metricos(setores).to_crs("EPSG:4326")


def _estacoes_para_pontos(chuva_df: pd.DataFrame) -> gpd.GeoDataFrame:
    estacoes = chuva_df.drop_duplicates("codigo_estacao")[
        ["codigo_estacao", "nome_estacao", "latitude", "longitude"]
    ]
    geometry = [Point(lon, lat) for lon, lat in zip(estacoes["longitude"], estacoes["latitude"])]
    return gpd.GeoDataFrame(estacoes, geometry=geometry, crs="EPSG:4326")


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


def encontrar_estacao_mais_proxima_combinada(
    setores: gpd.GeoDataFrame,
    chuva_inmet: pd.DataFrame,
    chuva_ana: pd.DataFrame | None,
    limiar_empate_m: float = 500.0,
) -> gpd.GeoDataFrame:
    """Para cada setor, acha a estação mais próxima entre INMET e ANA combinadas.

    Regra de prioridade (ver
    docs/superpowers/specs/2026-08-09-ingestao-ana-design.md): a distância
    manda — a estação mais próxima do centróide do setor vence, seja ela
    INMET ou ANA. O desempate por recência de leitura só entra em jogo
    quando as duas fontes têm uma estação a uma distância praticamente igual
    (diferença menor que `limiar_empate_m`, padrão 500m); nesse caso a
    estação com leitura mais recente vence. Na prática isso quase sempre
    favorece a ANA (granularidade de 15min) sobre o INMET (defasagem de
    dias) nesses empates — mas a regra não é hardcoded para nenhuma fonte
    específica, só para a leitura mais recente.
    """
    if chuva_ana is None or chuva_ana.empty:
        resultado = encontrar_estacao_mais_proxima(setores, chuva_inmet)
        resultado["fonte_estacao"] = "inmet"
        return resultado

    inmet_pareado = encontrar_estacao_mais_proxima(setores, chuva_inmet)
    ana_pareado = encontrar_estacao_mais_proxima(setores, chuva_ana)

    ultima_leitura_inmet = chuva_inmet.groupby("codigo_estacao")["data_hora"].max()
    ultima_leitura_ana = chuva_ana.groupby("codigo_estacao")["data_hora"].max()
    epoca = pd.Timestamp.min.tz_localize("UTC")

    codigos, nomes, distancias, fontes = [], [], [], []
    for i in range(len(setores)):
        dist_inmet = inmet_pareado["distancia_km"].iloc[i]
        dist_ana = ana_pareado["distancia_km"].iloc[i]

        if pd.isna(dist_ana):
            vencedor, fonte = inmet_pareado, "inmet"
        elif pd.isna(dist_inmet):
            vencedor, fonte = ana_pareado, "ana"
        elif abs(dist_inmet - dist_ana) * 1000 <= limiar_empate_m:
            cod_inmet = inmet_pareado["codigo_estacao"].iloc[i]
            cod_ana = ana_pareado["codigo_estacao"].iloc[i]
            leitura_inmet = ultima_leitura_inmet.get(cod_inmet, epoca)
            leitura_ana = ultima_leitura_ana.get(cod_ana, epoca)
            if leitura_ana >= leitura_inmet:
                vencedor, fonte = ana_pareado, "ana"
            else:
                vencedor, fonte = inmet_pareado, "inmet"
        elif dist_inmet < dist_ana:
            vencedor, fonte = inmet_pareado, "inmet"
        else:
            vencedor, fonte = ana_pareado, "ana"

        codigos.append(vencedor["codigo_estacao"].iloc[i])
        nomes.append(vencedor["nome_estacao"].iloc[i])
        distancias.append(vencedor["distancia_km"].iloc[i])
        fontes.append(fonte)

    resultado = setores.copy()
    resultado["codigo_estacao"] = codigos
    resultado["nome_estacao"] = nomes
    resultado["distancia_km"] = distancias
    resultado["fonte_estacao"] = fontes
    return resultado


def calcular_cruzamento(
    setores: gpd.GeoDataFrame,
    chuva_df: pd.DataFrame,
    chuva_ana: pd.DataFrame | None = None,
    referencia: pd.Timestamp | None = None,
    janelas: tuple[int, ...] = JANELAS_PADRAO,
) -> gpd.GeoDataFrame:
    """Cruza setores de risco com chuva: acha a estação mais próxima de cada setor
    (combinando INMET e, se fornecida, a ANA como fonte complementar — ver
    `encontrar_estacao_mais_proxima_combinada`) e calcula a chuva acumulada nas
    janelas de tempo pedidas (em horas).

    Se `referencia` for informada, é usada como fim da janela para todas as
    estações igualmente. Se não (caso padrão, usado pelo dashboard), cada
    estação usa sua própria leitura mais recente como referência — INMET e ANA
    têm granularidades e defasagens muito diferentes (leituras horárias com
    dias de atraso vs. 15min quase em tempo real), então uma referência global
    ancorada no INMET deixaria os setores atendidos pela ANA com janela de
    acumulado presa a uma data antiga do INMET, gerando NaN sempre que a
    defasagem do INMET ultrapassar os `dias_historico` mantidos pela ingestão
    da ANA (ver src/ingest/ana.py).
    """
    if chuva_df.empty:
        raise ValueError("chuva_df está vazio; nada para cruzar.")

    resultado = encontrar_estacao_mais_proxima_combinada(setores, chuva_df, chuva_ana)

    chuva_combinada = (
        chuva_df if chuva_ana is None or chuva_ana.empty
        else pd.concat([chuva_df, chuva_ana], ignore_index=True)
    )
    series_por_estacao = {
        codigo: grupo[["data_hora", "chuva_mm"]]
        for codigo, grupo in chuva_combinada.groupby("codigo_estacao")
    }

    if referencia is not None:
        referencias_por_estacao = {codigo: referencia for codigo in series_por_estacao}
        ref_geral = referencia
    else:
        referencias_por_estacao = {
            codigo: serie["data_hora"].max() for codigo, serie in series_por_estacao.items()
        }
        ref_geral = chuva_combinada["data_hora"].max()

    for horas in janelas:
        coluna = f"chuva_{horas}h"
        resultado[coluna] = [
            chuva_acumulada(series_por_estacao[codigo], referencias_por_estacao[codigo], horas)
            if codigo in series_por_estacao
            else float("nan")
            for codigo in resultado["codigo_estacao"]
        ]

    resultado.attrs["referencia"] = ref_geral
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
