import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import responses
from shapely.geometry import Polygon

from src.config import caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError
from src.export.vento_data import exportar_vento
from src.ingest.openmeteo import FORECAST_URL
from src.storage import salvar_setores


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


@pytest.fixture
def setores():
    return gpd.GeoDataFrame(
        {
            "num_setor": ["S1", "S2"],
            "munic": ["CIDADE A", "CIDADE B"],
            "grau_risco": ["Alto", "Muito alto"],
        },
        geometry=[_quadrado(-46.60, -23.50), _quadrado(-47.00, -24.00)],
        crs="EPSG:4326",
    )


def _resposta(horas_iso: list[str], rajadas_por_ponto: list[list[float]]) -> list[dict]:
    return [
        {"latitude": 0.0, "longitude": 0.0, "hourly": {"time": horas_iso, "windgusts_10m": rajadas}}
        for rajadas in rajadas_por_ponto
    ]


def test_exportar_vento_descarta_municipio_sem_risco(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta = _resposta(horas_iso, [[70.0] * 24, [30.0] * 24])  # CIDADE A em atenção, CIDADE B sem risco

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        exportar_vento("SP", 2026, tmp_path, saida)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    assert list(gdf["munic"]) == ["CIDADE A"]
    assert gdf.iloc[0]["severidade"] == "atencao"
    assert gdf.iloc[0]["rajada_kmh_24h"] == pytest.approx(70.0)


def test_exportar_vento_classifica_severidades_diferentes(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta = _resposta(horas_iso, [[95.0] * 24, [130.0] * 24])

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        exportar_vento("SP", 2026, tmp_path, saida)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    severidades = dict(zip(gdf["munic"], gdf["severidade"]))
    assert severidades == {"CIDADE A": "perigo", "CIDADE B": "grande_perigo"}


def test_exportar_vento_atualiza_meta_existente_sem_apagar_outros_campos(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    saida = tmp_path / "export"
    saida.mkdir(parents=True)
    (saida / "meta_sp.json").write_text(json.dumps({"fonte": "openmeteo", "total_setores": 2}))

    horas = pd.date_range("2026-08-10 00:00", periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta = _resposta(horas_iso, [[70.0] * 24, [30.0] * 24])

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        resultado = exportar_vento("SP", 2026, tmp_path, saida)

    meta = json.loads((saida / "meta_sp.json").read_text())
    assert meta["fonte"] == "openmeteo"
    assert meta["total_setores"] == 2
    assert meta["vento"]["total_municipios_sinalizados"] == 1
    assert resultado["total_municipios_sinalizados"] == 1


def test_exportar_vento_levanta_erro_se_setores_nao_existem(tmp_path: Path):
    with pytest.raises(ExportacaoDashboardError):
        exportar_vento("SP", 2026, tmp_path, tmp_path / "export")


def test_exportar_vento_ignora_rajadas_futuras_na_janela_de_24h(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    agora = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    # 24h observadas (passado, até `agora`) com rajada baixa, seguidas de
    # horas futuras (previsão) com rajada altíssima (200.0 -> grande_perigo).
    horas = pd.date_range(agora - pd.Timedelta(hours=23), periods=48, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    rajadas = [30.0] * 24 + [200.0] * 24
    resposta = _resposta(horas_iso, [rajadas, rajadas])

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        resultado = exportar_vento("SP", 2026, tmp_path, saida, agora=agora)

    gdf = gpd.read_file(saida / "vento_sp.geojson")
    assert len(gdf) == 0
    assert resultado["total_municipios_sinalizados"] == 0
    assert resultado["referencia"] == agora.isoformat()
