import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src.config import caminho_chuva, caminho_chuva_ana, caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError, exportar_dashboard
from src.storage import salvar_chuva, salvar_setores


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


def _serie_horaria(codigo: str, lat: float, lon: float, nome: str, valores: dict, inicio: str) -> pd.DataFrame:
    horas = pd.date_range(inicio, periods=len(valores), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "data_hora": horas,
            "chuva_mm": list(valores.values()),
            "codigo_estacao": codigo,
            "nome_estacao": nome,
            "uf": "SP",
            "latitude": lat,
            "longitude": lon,
        }
    )


def test_exportar_dashboard_gera_geojson_series_e_meta_so_com_inmet(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva = pd.concat(
        [
            _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {i: 1.0 for i in range(40)}, "2026-08-01 00:00"),
            _serie_horaria("A736", -24.001, -47.001, "PERTO DE S2", {i: 0.0 for i in range(40)}, "2026-08-01 00:00"),
        ],
        ignore_index=True,
    )
    salvar_chuva(chuva, caminho_chuva("SP", 2026, tmp_path))

    saida = tmp_path / "export"
    meta = exportar_dashboard("SP", 2026, tmp_path, saida)

    geojson_path = saida / "setores_sp.geojson"
    assert geojson_path.exists()
    gdf = gpd.read_file(geojson_path)
    assert len(gdf) == 2
    assert set(gdf["fonte_estacao"]) == {"inmet"}
    assert "chuva_24h" in gdf.columns

    series = json.loads((saida / "series_sp.json").read_text())
    assert set(series.keys()) == {"A701", "A736"}
    assert series["A701"]["fonte"] == "inmet"

    assert meta["total_setores"] == 2
    assert meta["total_estacoes_inmet"] == 2
    assert meta["total_estacoes_ana"] == 0


def test_exportar_dashboard_combina_ana_quando_disponivel(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva_inmet = _serie_horaria("A701", -23.55, -46.65, "INMET LONGE", {0: 1.0}, "2026-08-01 00:00")
    salvar_chuva(chuva_inmet, caminho_chuva("SP", 2026, tmp_path))
    chuva_ana = _serie_horaria("ANA01", -23.5005, -46.6005, "ANA PERTO", {0: 2.0}, "2026-08-01 00:00")
    salvar_chuva(chuva_ana, caminho_chuva_ana("SP", tmp_path))

    saida = tmp_path / "export"
    meta = exportar_dashboard("SP", 2026, tmp_path, saida)

    gdf = gpd.read_file(saida / "setores_sp.geojson")
    s1 = gdf[gdf["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "ana"
    assert s1["codigo_estacao"] == "ANA01"

    series = json.loads((saida / "series_sp.json").read_text())
    assert series["ANA01"]["fonte"] == "ana"
    assert meta["total_estacoes_ana"] == 1


def test_exportar_dashboard_recorta_serie_aos_ultimos_30_dias(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva = pd.concat(
        [
            _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {0: 1.0}, "2026-01-01 00:00"),
            _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {0: 2.0}, "2026-08-05 00:00"),
            _serie_horaria("A736", -24.001, -47.001, "PERTO DE S2", {0: 0.0}, "2026-08-05 00:00"),
        ],
        ignore_index=True,
    )
    salvar_chuva(chuva, caminho_chuva("SP", 2026, tmp_path))

    saida = tmp_path / "export"
    exportar_dashboard("SP", 2026, tmp_path, saida)

    series = json.loads((saida / "series_sp.json").read_text())
    assert len(series["A701"]["serie"]) == 1
    assert series["A701"]["serie"][0][1] == 2.0


def test_exportar_dashboard_levanta_erro_se_setores_nao_existem(tmp_path: Path):
    with pytest.raises(ExportacaoDashboardError):
        exportar_dashboard("SP", 2026, tmp_path, tmp_path / "export")


def test_exportar_dashboard_levanta_erro_se_chuva_inmet_nao_existe(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    with pytest.raises(ExportacaoDashboardError):
        exportar_dashboard("SP", 2026, tmp_path, tmp_path / "export")
