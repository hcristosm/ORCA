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
import typer

logger = logging.getLogger(__name__)

FEATURE_LAYER_URL = (
    "https://geoportal.sgb.gov.br/server/rest/services/"
    "gestaoterritorial/risco/FeatureServer/0/query"
)

UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

PAGE_SIZE = 2000


class CPRMFetchError(RuntimeError):
    """Erro ao buscar dados da camada de risco da CPRM/SGB."""


def _validar_uf(uf: str) -> str:
    uf_norm = uf.strip().upper()
    if uf_norm not in UFS_VALIDAS:
        raise ValueError(f"UF inválida: {uf!r}. Use uma sigla de 2 letras, ex.: SP.")
    return uf_norm


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


def salvar_geopackage(gdf: gpd.GeoDataFrame, caminho: Path, camada: str = "setores_risco") -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(caminho, layer=camada, driver="GPKG")


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
        salvar_geopackage(gdf, output)
        logger.info("Salvos %d setores de risco de %s em %s", len(gdf), uf, output)
        return gdf
    except CPRMFetchError:
        if output.exists():
            logger.warning(
                "Fonte remota da CPRM/SGB indisponível; usando cache local em %s", output
            )
            return gpd.read_file(output, layer="setores_risco")
        raise


app = typer.Typer(add_completion=False)


@app.command()
def ingest(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    output: Path = typer.Option(
        None, "--output", help="Caminho do GeoPackage de saída (padrão: data/risco_<uf>.gpkg)"
    ),
    timeout: float = typer.Option(30.0, help="Timeout por requisição, em segundos"),
    max_retries: int = typer.Option(3, help="Número máximo de tentativas por página"),
) -> None:
    """Baixa os setores de risco geológico da CPRM/SGB para uma UF."""
    out = output or Path("data") / f"risco_{uf.lower()}.gpkg"
    gdf = ingerir_uf(uf, out, timeout=timeout, max_retries=max_retries)
    typer.echo(f"{len(gdf)} setores de risco salvos em {out}")


if __name__ == "__main__":
    app()
