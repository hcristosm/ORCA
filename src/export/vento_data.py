"""Exportação da camada de vento (rajada por município) do dashboard estático.

Módulo irmão de `dashboard_data.py`, deliberadamente desacoplado dele —
vento não é cruzado com os setores geológicos (ver
.superpowers/specs/2026-08-12-camada-vento-design.md). Grava
`vento_<uf>.geojson` (um ponto por município sinalizado) e atualiza o
`meta_<uf>.json` já gerado por `exportar_dashboard`, em vez de criar um
terceiro arquivo de metadados.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config import caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError
from src.ingest.openmeteo import OpenMeteoFetchError, fetch_vento_batch
from src.processing.cruzamento import centroides_municipio
from src.processing.vento import classificar_severidade, rajada_max
from src.storage import ler_setores

logger = logging.getLogger(__name__)

JANELA_RAJADA_HORAS = 24


def exportar_vento(uf: str, ano: int, diretorio_dados: Path, saida_dir: Path) -> dict:
    """Consulta a rajada de vento recente por município e grava `vento_<uf>.geojson`.

    Só municípios com severidade acionável (`classificar_severidade` != `None`)
    entram no GeoJSON. `ano` não é usado hoje — mantido só por simetria de
    assinatura com `exportar_dashboard`, caso uma fonte futura de vento
    precise de um parâmetro de período.
    """
    uf_norm = uf.strip().upper()
    caminho_setores_path = caminho_setores(uf_norm, diretorio_dados)
    if not caminho_setores_path.exists():
        raise ExportacaoDashboardError(
            f"Setores de risco não encontrados em {caminho_setores_path}; "
            f"rode `ingest-cprm --uf {uf_norm}` primeiro."
        )
    setores = ler_setores(caminho_setores_path)
    saida_dir.mkdir(parents=True, exist_ok=True)

    municipios, pontos = centroides_municipio(setores)
    try:
        series = fetch_vento_batch(pontos, dias_historico=4, dias_previsao=1)
    except OpenMeteoFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar vento na Open-Meteo: {exc}") from exc

    partes_validas = [s[s["vento_rajada_kmh"].notna()] for s in series if not s.empty]
    validas = pd.concat(partes_validas, ignore_index=True) if partes_validas else pd.DataFrame(
        columns=["data_hora", "vento_rajada_kmh"]
    )
    referencia = validas["data_hora"].max() if not validas.empty else pd.Timestamp.now(tz="UTC")

    registros = []
    for municipio, (lat, lon), serie in zip(municipios, pontos, series):
        rajada = rajada_max(serie, referencia, JANELA_RAJADA_HORAS)
        severidade = classificar_severidade(rajada)
        if severidade is None:
            continue
        registros.append({
            "munic": municipio,
            "rajada_kmh_24h": round(float(rajada), 1),
            "severidade": severidade,
            "geometry": Point(lon, lat),
        })

    gdf = gpd.GeoDataFrame(
        registros if registros else [],
        columns=["munic", "rajada_kmh_24h", "severidade", "geometry"],
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
