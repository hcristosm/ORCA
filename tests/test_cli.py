import json
from pathlib import Path

import responses
from typer.testing import CliRunner

from src.cli import app
from src.config import caminho_setores
from src.ingest.cprm import FEATURE_LAYER_URL
from src.ingest.openmeteo import FORECAST_URL

runner = CliRunner()


def _feature(objectid: int, uf: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-47.61, -22.84], [-47.60, -22.84], [-47.60, -22.85], [-47.61, -22.84]]],
        },
        "properties": {
            "objectid": objectid, "uf": uf, "munic": "CIDADE X",
            "grau_risco": "Alto", "num_setor": f"{uf}_{objectid}", "data_setor": "2020-01-01",
        },
    }


def _resposta_openmeteo(n_pontos: int) -> list[dict]:
    import pandas as pd
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    return [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 61}}
        for _ in range(n_pontos)
    ]


@responses.activate
def test_atualizar_nacional_ingere_e_exporta_varias_ufs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saida = tmp_path / "docs" / "dashboard" / "data"

    for uf in ("SP", "RJ"):
        responses.add(
            responses.GET, FEATURE_LAYER_URL,
            match=[responses.matchers.query_param_matcher({"where": f"uf='{uf}'"}, strict_match=False)],
            json={"type": "FeatureCollection", "features": [_feature(1, uf)], "properties": {"exceededTransferLimit": False}},
            status=200,
        )
    # exportar_dashboard roda por UF (setores + série por município cada) --
    # 2 UFs = 4 POSTs, 1 ponto cada.
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP setores
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP município
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ setores
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ município

    resultado = runner.invoke(
        app, ["atualizar-nacional", "--ufs", "SP,RJ", "--ano", "2026",
              "--diretorio", str(tmp_path / "data"), "--saida", str(saida)],
    )

    assert resultado.exit_code == 0, resultado.output
    assert (saida / "ufs_disponiveis.json").exists()
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["RJ", "SP"]
