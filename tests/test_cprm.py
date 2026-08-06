from pathlib import Path

import pytest
import responses
from responses import matchers

from src.ingest.cprm import (
    FEATURE_LAYER_URL,
    CPRMFetchError,
    fetch_setores_risco,
    ingerir_uf,
)
from src.storage import salvar_setores


def _feature(objectid: int, grau_risco: str = "Alto") -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-47.61, -22.84], [-47.60, -22.84], [-47.60, -22.85], [-47.61, -22.84]]],
        },
        "properties": {
            "objectid": objectid,
            "uf": "SP",
            "munic": "RIO DAS PEDRAS",
            "grau_risco": grau_risco,
            "num_setor": f"SP_TEST_{objectid}",
        },
    }


@responses.activate
def test_fetch_setores_risco_parses_geojson():
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1), _feature(2)],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )

    gdf = fetch_setores_risco("sp")

    assert len(gdf) == 2
    assert set(gdf["grau_risco"]) == {"Alto"}
    assert gdf.crs.to_epsg() == 4326


@responses.activate
def test_fetch_setores_risco_paginates_until_exhausted():
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        match=[matchers.query_param_matcher({"resultOffset": "0"}, strict_match=False)],
        json={
            "type": "FeatureCollection",
            "features": [_feature(1)],
            "properties": {"exceededTransferLimit": True},
        },
        status=200,
    )
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        match=[matchers.query_param_matcher({"resultOffset": "1"}, strict_match=False)],
        json={
            "type": "FeatureCollection",
            "features": [_feature(2)],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )

    gdf = fetch_setores_risco("SP")

    assert len(gdf) == 2


def test_uf_invalida_levanta_erro():
    with pytest.raises(ValueError):
        fetch_setores_risco("XX")


@responses.activate
def test_retry_recupera_apos_falha_transitoria():
    responses.add(responses.GET, FEATURE_LAYER_URL, status=500)
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1)],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )

    gdf = fetch_setores_risco("SP", max_retries=2, backoff_factor=0.01)

    assert len(gdf) == 1


@responses.activate
def test_falha_persistente_levanta_erro_sem_cache():
    responses.add(responses.GET, FEATURE_LAYER_URL, status=500)

    with pytest.raises(CPRMFetchError):
        fetch_setores_risco("SP", max_retries=2, backoff_factor=0.01)


@responses.activate
def test_ingerir_uf_usa_cache_local_quando_fonte_remota_falha(tmp_path: Path):
    output = tmp_path / "risco_sp.gpkg"

    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1), _feature(2)],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )
    gdf_original = fetch_setores_risco("SP")
    salvar_setores(gdf_original, output)

    responses.reset()
    responses.add(responses.GET, FEATURE_LAYER_URL, status=500)

    gdf_cache = ingerir_uf("SP", output, max_retries=1, backoff_factor=0.01)

    assert len(gdf_cache) == 2
