import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import responses
from shapely.geometry import Polygon

from src.config import caminho_setores
from src.export.nacional import exportar_nacional
from src.ingest.openmeteo import FORECAST_URL
from src.storage import salvar_setores


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


def _setores_uf(uf: str, num_setor: str, cx: float, cy: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"num_setor": [num_setor], "munic": ["CIDADE X"], "grau_risco": ["Alto"]},
        geometry=[_quadrado(cx, cy)],
        crs="EPSG:4326",
    )


def _resposta_openmeteo(n_pontos: int) -> list[dict]:
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    return [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 61}}
        for _ in range(n_pontos)
    ]


def test_exportar_nacional_gera_arquivos_por_uf_e_manifesto(tmp_path: Path):
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    salvar_setores(_setores_uf("RJ", "RJ1", -43.20, -22.90), caminho_setores("RJ", tmp_path))

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        # a grade é calibrada uma vez sobre as 2 UFs, mas a busca à Open-Meteo
        # ainda acontece por UF dentro do loop de export (`exportar_dashboard`
        # continua fazendo 1 chamada de setores + 1 de série por município por
        # UF) -- 2 UFs = 4 POSTs, 1 ponto cada (setores de teste bem
        # espalhados, cada um isolado na própria célula).
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP setores
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP município
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ setores
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ município
        resultados = exportar_nacional(["SP", "RJ"], 2026, tmp_path, saida, orcamento_alvo=1000)

    assert set(resultados.keys()) == {"SP", "RJ"}
    assert (saida / "setores_sp.geojson").exists()
    assert (saida / "setores_rj.geojson").exists()

    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["RJ", "SP"]

    for meta in resultados.values():
        assert "tamanho_celula_grade_graus" in meta
        assert "total_celulas_grade" in meta


def test_exportar_nacional_pula_uf_sem_setores_ingeridos(tmp_path: Path):
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        resultados = exportar_nacional(["SP", "RJ"], 2026, tmp_path, saida, orcamento_alvo=1000)

    assert set(resultados.keys()) == {"SP"}
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["SP"]


def test_exportar_nacional_nenhuma_uf_ingerida_levanta_erro(tmp_path: Path):
    with pytest.raises(ValueError):
        exportar_nacional(["SP", "RJ"], 2026, tmp_path, tmp_path / "export")
