"""Exportação da camada de vento (rajada por município) do dashboard estático.

Módulo irmão de `dashboard_data.py`, deliberadamente desacoplado dele;
vento não é cruzado com os setores geológicos. Cobre todos os municípios de
uma UF via a malha do IBGE (não só os que têm setor de risco CPRM
registrado, ver `src/ingest/ibge.py`), grava `vento_<uf>.geojson` (um ponto
por município sinalizado, chaveado por `codarea`) e atualiza o
`meta_<uf>.json` já gerado por `exportar_dashboard`, em vez de criar um
terceiro arquivo de metadados. Ver
.superpowers/specs/2026-08-12-choropleth-vento-municipios-design.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.export.dashboard_data import ExportacaoDashboardError
from src.ingest.ibge import IBGEFetchError, fetch_municipios, fetch_nomes_municipios
from src.ingest.openmeteo import OpenMeteoFetchError, fetch_vento_batch
from src.processing.cruzamento import centroides_ibge
from src.processing.vento import classificar_severidade, rajada_max
from src.storage_cache_openmeteo import CacheOpenMeteo

logger = logging.getLogger(__name__)

JANELA_RAJADA_HORAS = 24


def exportar_vento(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    agora: pd.Timestamp | None = None,
    cache_openmeteo: CacheOpenMeteo | None = None,
) -> dict:
    """Consulta a rajada de vento recente por município (todos os da malha do
    IBGE, não só os com setor CPRM) e grava `vento_<uf>.geojson`.

    Só municípios com severidade acionável (`classificar_severidade` != `None`)
    entram no GeoJSON. `ano` e `diretorio_dados` não são usados hoje,
    mantidos só por simetria de assinatura com `exportar_dashboard`. `agora`
    é parametrizável para tornar testes determinísticos e para excluir as
    horas de previsão (a série inclui `dias_previsao=1`) da janela de
    "últimas 24h observadas"; em produção usa o instante atual.
    `cache_openmeteo`, se informado, reduz o histórico de fato pedido à
    Open-Meteo (ver `src/storage_cache_openmeteo.py`).
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    uf_norm = uf.strip().upper()
    saida_dir.mkdir(parents=True, exist_ok=True)

    try:
        municipios_gdf = fetch_municipios(uf_norm)
        nomes = fetch_nomes_municipios(uf_norm)
    except IBGEFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar a malha municipal do IBGE: {exc}") from exc

    codareas, pontos = centroides_ibge(municipios_gdf)
    try:
        series = fetch_vento_batch(
            pontos, dias_historico=4, dias_previsao=1, cache=cache_openmeteo, agora=agora
        )
    except OpenMeteoFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar vento na Open-Meteo: {exc}") from exc

    partes_validas = [
        s[(s["data_hora"] <= agora) & s["vento_rajada_kmh"].notna()] for s in series if not s.empty
    ]
    validas = pd.concat(partes_validas, ignore_index=True) if partes_validas else pd.DataFrame(
        columns=["data_hora", "vento_rajada_kmh"]
    )
    referencia = validas["data_hora"].max() if not validas.empty else agora

    registros = []
    for codarea, (lat, lon), serie in zip(codareas, pontos, series):
        rajada = rajada_max(serie, referencia, JANELA_RAJADA_HORAS)
        severidade = classificar_severidade(rajada)
        if severidade is None:
            continue
        registros.append({
            "codarea": codarea,
            "munic": nomes.get(codarea, codarea),
            "rajada_kmh_24h": round(float(rajada), 1),
            "severidade": severidade,
            "geometry": Point(lon, lat),
        })

    gdf = gpd.GeoDataFrame(
        registros if registros else [],
        columns=["codarea", "munic", "rajada_kmh_24h", "severidade", "geometry"],
        geometry="geometry",
        crs="EPSG:4326",
    )
    caminho_geojson = saida_dir / f"vento_{uf_norm.lower()}.geojson"
    if caminho_geojson.exists():
        caminho_geojson.unlink()
    gdf.to_file(caminho_geojson, driver="GeoJSON")

    caminho_meta = saida_dir / f"meta_{uf_norm.lower()}.json"
    meta = json.loads(caminho_meta.read_text()) if caminho_meta.exists() else {}
    meta["vento"] = {
        "referencia": referencia.isoformat(),
        "total_municipios_sinalizados": len(registros),
    }
    caminho_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    logger.info(
        "Exportada camada de vento para %s: %d município(s) sinalizado(s)", uf_norm, len(registros)
    )
    return meta["vento"]
