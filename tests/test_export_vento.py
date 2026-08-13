import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import responses
from shapely.geometry import Polygon

from src.export.dashboard_data import ExportacaoDashboardError
from src.export.vento_data import exportar_vento
from src.ingest.ibge import LOCALIDADES_URL_TEMPLATE, MALHAS_URL_TEMPLATE
from src.ingest.openmeteo import FORECAST_URL


def _malha_resposta() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "3500105"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-46.61, -23.51], [-46.59, -23.51], [-46.59, -23.49], [-46.61, -23.49], [-46.61, -23.51]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"codarea": "3500204"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-47.01, -24.01], [-46.99, -24.01], [-46.99, -23.99], [-47.01, -23.99], [-47.01, -24.01]]],
                },
            },
        ],
    }


def _nomes_resposta() -> list[dict]:
    return [
        {"id": 3500105, "nome": "CIDADE A"},
        {"id": 3500204, "nome": "CIDADE B"},
    ]


def _resposta_vento(horas_iso: list[str], rajadas_por_ponto: list[list[float]]) -> list[dict]:
    return [
        {"latitude": 0.0, "longitude": 0.0, "hourly": {"time": horas_iso, "windgusts_10m": rajadas}}
        for rajadas in rajadas_por_ponto
    ]


def _mockar_ibge(rsps: responses.RequestsMock) -> None:
    rsps.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), json=_malha_resposta(), status=200)
    rsps.add(responses.GET, LOCALIDADES_URL_TEMPLATE.format(uf="SP"), json=_nomes_resposta(), status=200)


def test_exportar_vento_descarta_municipio_sem_risco(tmp_path: Path):
    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta_vento = _resposta_vento(horas_iso, [[70.0] * 24, [30.0] * 24])  # CIDADE A em atenção, CIDADE B sem risco

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        _mockar_ibge(rsps)
        rsps.add(responses.POST, FORECAST_URL, json=resposta_vento, status=200)
        exportar_vento("SP", 2026, tmp_path, saida)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    assert list(gdf["munic"]) == ["CIDADE A"]
    assert list(gdf["codarea"]) == ["3500105"]
    assert gdf.iloc[0]["severidade"] == "atencao"
    assert gdf.iloc[0]["rajada_kmh_24h"] == pytest.approx(70.0)


def test_exportar_vento_classifica_severidades_diferentes(tmp_path: Path):
    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta_vento = _resposta_vento(horas_iso, [[95.0] * 24, [130.0] * 24])

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        _mockar_ibge(rsps)
        rsps.add(responses.POST, FORECAST_URL, json=resposta_vento, status=200)
        exportar_vento("SP", 2026, tmp_path, saida)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    severidades = dict(zip(gdf["codarea"], gdf["severidade"]))
    assert severidades == {"3500105": "perigo", "3500204": "grande_perigo"}


def test_exportar_vento_atualiza_meta_existente_sem_apagar_outros_campos(tmp_path: Path):
    saida = tmp_path / "export"
    saida.mkdir(parents=True)
    (saida / "meta_sp.json").write_text(json.dumps({"fonte": "openmeteo", "total_setores": 2}))

    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta_vento = _resposta_vento(horas_iso, [[70.0] * 24, [30.0] * 24])

    with responses.RequestsMock() as rsps:
        _mockar_ibge(rsps)
        rsps.add(responses.POST, FORECAST_URL, json=resposta_vento, status=200)
        resultado = exportar_vento("SP", 2026, tmp_path, saida)

    meta = json.loads((saida / "meta_sp.json").read_text())
    assert meta["fonte"] == "openmeteo"
    assert meta["total_setores"] == 2
    assert meta["vento"]["total_municipios_sinalizados"] == 1
    assert resultado["total_municipios_sinalizados"] == 1


def test_exportar_vento_usa_nome_do_codarea_quando_localidade_nao_encontrada(tmp_path: Path):
    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta_vento = _resposta_vento(horas_iso, [[70.0] * 24, [30.0] * 24])

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), json=_malha_resposta(), status=200)
        rsps.add(responses.GET, LOCALIDADES_URL_TEMPLATE.format(uf="SP"), json=[], status=200)  # sem nomes
        rsps.add(responses.POST, FORECAST_URL, json=resposta_vento, status=200)
        exportar_vento("SP", 2026, tmp_path, saida)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    assert gdf.iloc[0]["munic"] == "3500105"  # cai pro próprio código quando não há nome


def test_exportar_vento_levanta_erro_se_ibge_falha(tmp_path: Path):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, MALHAS_URL_TEMPLATE.format(uf="SP"), status=500)
        with pytest.raises(ExportacaoDashboardError):
            exportar_vento("SP", 2026, tmp_path, tmp_path / "export")


def test_exportar_vento_ignora_rajadas_futuras_na_janela_de_24h(tmp_path: Path):
    agora = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    horas = pd.date_range(agora - pd.Timedelta(hours=23), periods=48, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    rajadas = [30.0] * 24 + [200.0] * 24
    resposta_vento = _resposta_vento(horas_iso, [rajadas, rajadas])

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        _mockar_ibge(rsps)
        rsps.add(responses.POST, FORECAST_URL, json=resposta_vento, status=200)
        resultado = exportar_vento("SP", 2026, tmp_path, saida, agora=agora)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    assert len(gdf) == 0
    assert resultado["total_municipios_sinalizados"] == 0
    assert resultado["referencia"] == agora.isoformat()
