"""Cliente de ingestão para a camada de Setorização de Risco Geológico da CPRM/SGB.

Fonte confirmada em 2026-08-05 via GetCapabilities/rest services (ver README):
https://geoportal.sgb.gov.br/server/rest/services/gestaoterritorial/risco/FeatureServer/0

A CPRM foi renomeada para SGB (Serviço Geológico do Brasil); os domínios antigos
(geoportal.cprm.gov.br, sace.cprm.gov.br) ainda respondem mas não hospedam mais
esta camada.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import geopandas as gpd
import requests

from src.config import validar_uf as _validar_uf
from src.storage import ler_setores, salvar_setores

logger = logging.getLogger(__name__)

FEATURE_LAYER_URL = (
    "https://geoportal.sgb.gov.br/server/rest/services/"
    "gestaoterritorial/risco/FeatureServer/0/query"
)

PAGE_SIZE = 2000


class CPRMFetchError(RuntimeError):
    """Erro ao buscar dados da camada de risco da CPRM/SGB."""


def _query_pagina(
    uf: str,
    offset: int,
    session: requests.Session,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
) -> dict:
    params = {
        "where": f"uf='{uf}'",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }

    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = session.get(FEATURE_LAYER_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            if "error" in payload:
                raise CPRMFetchError(f"API retornou erro: {payload['error']}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao buscar setores de risco (tentativa %d/%d): %s. "
                "Aguardando %.1fs antes de tentar novamente.",
                tentativa, max_retries, exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)

    raise CPRMFetchError(
        f"Não foi possível obter dados da CPRM/SGB após {max_retries} tentativas"
    ) from last_exc


def fetch_setores_risco(
    uf: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    session: requests.Session | None = None,
) -> gpd.GeoDataFrame:
    """Baixa os setores de risco geológico de uma UF via ArcGIS REST (GeoJSON).

    Pagina automaticamente usando resultOffset/resultRecordCount até esgotar
    os registros, seguindo exceededTransferLimit da resposta.
    """
    uf_norm = _validar_uf(uf)
    sess = session or requests.Session()

    features: list[dict] = []
    offset = 0
    while True:
        payload = _query_pagina(uf_norm, offset, sess, timeout, max_retries, backoff_factor)
        pagina_features = payload.get("features", [])
        features.extend(pagina_features)

        exceeded = payload.get("properties", {}).get("exceededTransferLimit", False)
        if not exceeded or not pagina_features:
            break
        offset += len(pagina_features)

    if not features:
        logger.warning("Nenhum setor de risco encontrado para UF=%s", uf_norm)

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    return gdf


def ingerir_uf(
    uf: str,
    output: Path,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
) -> gpd.GeoDataFrame:
    """Busca os setores de risco de uma UF e salva em GeoPackage.

    Se a busca remota falhar e já existir um GeoPackage em cache local (`output`),
    usa o cache e avisa, em vez de quebrar a ingestão inteira.
    """
    try:
        gdf = fetch_setores_risco(
            uf, timeout=timeout, max_retries=max_retries, backoff_factor=backoff_factor
        )
        salvar_setores(gdf, output)
        logger.info("Salvos %d setores de risco de %s em %s", len(gdf), uf, output)
        return gdf
    except CPRMFetchError:
        if output.exists():
            logger.warning(
                "Fonte remota da CPRM/SGB indisponível; usando cache local em %s", output
            )
            return ler_setores(output)
        raise
