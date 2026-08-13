import pytest
import responses

from src.ingest.ibge import (
    LOCALIDADES_URL_TEMPLATE,
    MALHAS_URL_TEMPLATE,
    IBGEFetchError,
    fetch_municipios,
    fetch_nomes_municipios,
)


def _malha_resposta() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "3500105"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-51.0, -21.0], [-51.1, -21.0], [-51.1, -21.1], [-51.0, -21.1], [-51.0, -21.0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"codarea": "3500204"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-49.5, -21.2], [-49.6, -21.2], [-49.6, -21.3], [-49.5, -21.3], [-49.5, -21.2]]],
                },
            },
        ],
    }


@responses.activate
def test_fetch_municipios_parseia_codarea_e_geometria():
    responses.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), json=_malha_resposta(), status=200)

    gdf = fetch_municipios("SP")

    assert list(gdf["codarea"]) == ["3500105", "3500204"]
    assert gdf.crs.to_epsg() == 4326
    assert len(gdf) == 2


@responses.activate
def test_fetch_municipios_normaliza_uf_minuscula():
    responses.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), json=_malha_resposta(), status=200)

    gdf = fetch_municipios("sp")

    assert len(gdf) == 2


@responses.activate
def test_fetch_municipios_retry_recupera_apos_falha_transitoria():
    responses.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), status=500)
    responses.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), json=_malha_resposta(), status=200)

    gdf = fetch_municipios("SP", max_retries=2, backoff_factor=0.01)

    assert len(gdf) == 2


@responses.activate
def test_fetch_municipios_falha_persistente_levanta_erro():
    responses.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), status=500)

    with pytest.raises(IBGEFetchError):
        fetch_municipios("SP", max_retries=2, backoff_factor=0.01)


@responses.activate
def test_fetch_nomes_municipios_parseia_id_e_nome():
    responses.add(
        responses.GET,
        LOCALIDADES_URL_TEMPLATE.format(uf="SP"),
        json=[{"id": 3500105, "nome": "Adamantina"}, {"id": 3500204, "nome": "Adolfo"}],
        status=200,
    )

    nomes = fetch_nomes_municipios("SP")

    assert nomes == {"3500105": "Adamantina", "3500204": "Adolfo"}


@responses.activate
def test_fetch_nomes_municipios_falha_persistente_levanta_erro():
    responses.add(responses.GET, LOCALIDADES_URL_TEMPLATE.format(uf="SP"), status=500)

    with pytest.raises(IBGEFetchError):
        fetch_nomes_municipios("SP", max_retries=2, backoff_factor=0.01)


@responses.activate
def test_fetch_municipios_features_vazio_levanta_erro():
    responses.add(
        responses.GET,
        MALHAS_URL_TEMPLATE.format(uf="SP"),
        json={"type": "FeatureCollection", "features": []},
        status=200,
    )

    with pytest.raises(IBGEFetchError):
        fetch_municipios("SP")


@responses.activate
def test_fetch_nomes_municipios_formato_inesperado_levanta_ibge_fetch_error():
    responses.add(
        responses.GET,
        LOCALIDADES_URL_TEMPLATE.format(uf="SP"),
        json={"error": "something went wrong"},
        status=200,
    )

    with pytest.raises(IBGEFetchError):
        fetch_nomes_municipios("SP")
