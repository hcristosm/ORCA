import json
from pathlib import Path

import responses
from responses import matchers
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
def test_atualizar_nacional_exporta_varias_ufs_sem_tocar_na_cprm(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saida = tmp_path / "docs" / "dashboard" / "data"

    for uf in ("SP", "RJ"):
        responses.add(
            responses.GET, FEATURE_LAYER_URL,
            match=[matchers.query_param_matcher({"where": f"uf='{uf}'"}, strict_match=False)],
            json={"type": "FeatureCollection", "features": [_feature(1, uf)], "properties": {"exceededTransferLimit": False}},
            status=200,
        )

    # `atualizar-nacional` não ingere mais CPRM (ver ingerir-setores): os
    # setores precisam já estar no diretório local antes de invocá-lo.
    resultado_ingestao = runner.invoke(
        app, ["ingerir-setores", "--ufs", "SP,RJ", "--diretorio", str(tmp_path / "data"),
              "--backoff-factor", "0"],
    )
    assert resultado_ingestao.exit_code == 0, resultado_ingestao.output

    # exportar_dashboard roda por UF (setores + série por município cada) --
    # 2 UFs = 4 POSTs, 1 ponto cada.
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP setores
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP município
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ setores
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ município

    # Guarda da fronteira que esta branch inteira defende: `atualizar-nacional`
    # não pode voltar a chamar a CPRM/SGB. `responses` não exige que todos os
    # mocks sejam disparados, então sem esta contagem uma reintrodução da
    # ingestão no caminho diário passaria despercebida pela suíte.
    chamadas_cprm_antes = sum(1 for c in responses.calls if FEATURE_LAYER_URL in c.request.url)

    resultado = runner.invoke(
        app, ["atualizar-nacional", "--ufs", "SP,RJ", "--ano", "2026",
              "--diretorio", str(tmp_path / "data"), "--saida", str(saida)],
    )

    chamadas_cprm_depois = sum(1 for c in responses.calls if FEATURE_LAYER_URL in c.request.url)
    assert chamadas_cprm_depois == chamadas_cprm_antes, (
        "atualizar-nacional voltou a requisitar a CPRM/SGB no caminho diário"
    )

    assert resultado.exit_code == 0, resultado.output
    assert (saida / "ufs_disponiveis.json").exists()
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["RJ", "SP"]


@responses.activate
def test_ingerir_setores_falha_se_alguma_uf_falhar(tmp_path: Path):
    """O job mensal deve gritar quando uma UF não vem: dado congelado por um
    mês é pior que uma notificação a mais.

    O diretório é semeado com uma execução bem-sucedida antes: sem isso o
    teste afirmava um comportamento que não pode ocorrer em produção (o
    workflow mensal extrai os `.gpkg` de `dados-base` para `data/` antes de
    ingerir, então o cache local sempre existe a partir da 2a execução).
    """
    # Semeadura: as duas UFs respondem e ficam no diretório.
    for uf in ("AP", "BA"):
        responses.add(
            responses.GET, FEATURE_LAYER_URL,
            json={"type": "FeatureCollection", "features": [_feature(1, uf)]},
            status=200,
            match=[matchers.query_param_matcher({"where": f"uf='{uf}'"}, strict_match=False)],
        )
    semeadura = runner.invoke(
        app,
        ["ingerir-setores", "--ufs", "AP,BA", "--diretorio", str(tmp_path),
         "--backoff-factor", "0"],
    )
    assert semeadura.exit_code == 0, semeadura.output
    assert caminho_setores("BA", tmp_path).exists()

    # Execução real: AP responde, BA cai. As respostas são consumidas na
    # ordem de registro (AP faz 1 requisição; BA repete a última, 500).
    responses.reset()
    responses.add(
        responses.GET, FEATURE_LAYER_URL,
        json={"type": "FeatureCollection", "features": []},
        status=200,
    )
    responses.add(responses.GET, FEATURE_LAYER_URL, status=500)

    resultado = runner.invoke(
        app,
        ["ingerir-setores", "--ufs", "AP,BA", "--diretorio", str(tmp_path),
         "--backoff-factor", "0"],
    )

    assert resultado.exit_code == 1
    assert "BA" in resultado.output
    assert caminho_setores("AP", tmp_path).exists()


@responses.activate
def test_ingerir_setores_falha_mesmo_com_geopackage_ja_no_diretorio(tmp_path: Path):
    """A condição real de produção: o workflow mensal extrai os `.gpkg` de
    `dados-base` para `data/` ANTES de ingerir, então o cache local sempre
    existe a partir da 2a execução. Com a SGB fora do ar, o fallback de
    cache de `ingerir_uf` fazia o comando mensal ver sucesso em toda UF e
    fechar verde -- setores congelados por mais um mês, sem notificação.

    Ver spec §4.7: mensal falha se qualquer UF falhar após os retries.
    """
    # 1a execução: a SGB responde e o GeoPackage de AP fica no diretório.
    responses.add(
        responses.GET, FEATURE_LAYER_URL,
        json={"type": "FeatureCollection", "features": [_feature(1, "AP")]},
        status=200,
        match=[matchers.query_param_matcher({"where": "uf='AP'"}, strict_match=False)],
    )
    primeira = runner.invoke(
        app,
        ["ingerir-setores", "--ufs", "AP", "--diretorio", str(tmp_path), "--backoff-factor", "0"],
    )
    assert primeira.exit_code == 0, primeira.output
    assert caminho_setores("AP", tmp_path).exists()

    # 2a execução: SGB inteiramente fora do ar, cache local presente.
    responses.reset()
    responses.add(responses.GET, FEATURE_LAYER_URL, status=500)

    segunda = runner.invoke(
        app,
        ["ingerir-setores", "--ufs", "AP", "--diretorio", str(tmp_path), "--backoff-factor", "0"],
    )

    assert segunda.exit_code == 1, segunda.output
    assert "AP" in segunda.output
    assert "0/1" in segunda.output
