import hashlib
import json
from pathlib import Path

import responses
from typer.testing import CliRunner

from src.cli import app
from src.config import caminho_setores_beluga
from src.ingest.beluga import URL_BASE
from src.ingest.openmeteo import FORECAST_URL

runner = CliRunner()


def _geojson(uf: str) -> str:
    return json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-47.61, -22.84], [-47.60, -22.84], [-47.60, -22.85], [-47.61, -22.84],
                ]],
            },
            "properties": {
                "num_setor": f"{uf}_1_CPRM", "uf": uf, "munic": "CIDADE X",
                "grau_risco": "Alto", "data_setor": "2026-10-01",
                "bl_fonte": "br-sgb-setorizacao", "bl_produto": "setorizacao_risco",
            },
        }],
    })


def _manifest(corpos: dict[str, str]) -> dict:
    return {
        "contrato": "v1",
        "gerado_em": "2026-11-27T03:03:37+00:00",
        "ufs": {
            uf.lower(): {
                "arquivo": f"setores_{uf.lower()}.geojson",
                "setores": 1,
                "sha256": hashlib.sha256(corpo.encode()).hexdigest(),
                "por_fonte": {"br-sgb-setorizacao": 1},
            }
            for uf, corpo in corpos.items()
        },
        "fontes": [{"id": "br-sgb-setorizacao", "nome": "CPRM/SGB", "orgao": "SGB"}],
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
def test_atualizar_nacional_exporta_varias_ufs_sem_tocar_no_beluga(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saida = tmp_path / "docs" / "dashboard" / "data"
    corpos = {"SP": _geojson("SP"), "RJ": _geojson("RJ")}

    # O manifest tem de listar as 27 UFs; as 25 que não são pedidas não são
    # baixadas, então o corpo delas não importa aqui.
    todas = dict(corpos)
    for uf in ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
               "MG", "PA", "PB", "PR", "PE", "PI", "RN", "RS", "RO", "RR", "SC", "SE", "TO"):
        todas[uf] = _geojson(uf)
    responses.add(responses.GET, f"{URL_BASE}manifest.json", json=_manifest(todas), status=200)
    for uf, corpo in corpos.items():
        responses.add(responses.GET, f"{URL_BASE}setores_{uf.lower()}.geojson", body=corpo, status=200)

    download = runner.invoke(
        app, ["baixar-beluga", "--ufs", "SP,RJ", "--diretorio", str(tmp_path / "data")],
    )
    assert download.exit_code == 0, download.output

    # exportar_dashboard roda por UF (setores + série por município cada) --
    # 2 UFs = 4 POSTs, 1 ponto cada.
    for _ in range(4):
        responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)

    # Guarda da fronteira: `atualizar-nacional` não pode voltar a buscar os
    # setores na rede. `responses` não exige que todos os mocks sejam
    # disparados, então sem esta contagem uma reintrodução do download no
    # caminho da chuva passaria despercebida pela suíte.
    chamadas_beluga_antes = sum(1 for c in responses.calls if URL_BASE in c.request.url)

    resultado = runner.invoke(
        app, ["atualizar-nacional", "--ufs", "SP,RJ",
              "--diretorio", str(tmp_path / "data"), "--saida", str(saida)],
    )

    chamadas_beluga_depois = sum(1 for c in responses.calls if URL_BASE in c.request.url)
    assert chamadas_beluga_depois == chamadas_beluga_antes, (
        "atualizar-nacional voltou a requisitar os setores do BELUGA no caminho diário"
    )

    assert resultado.exit_code == 0, resultado.output
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["RJ", "SP"]


@responses.activate
def test_baixar_beluga_falha_se_alguma_uf_falhar(tmp_path: Path):
    """O download deve gritar quando uma UF não vem: setor congelado em
    silêncio é o jeito de a coleta parar por meses sem ninguém ver."""
    corpos = {uf: _geojson(uf) for uf in sorted(
        ["SP", "RJ", "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
         "MG", "PA", "PB", "PR", "PE", "PI", "RN", "RS", "RO", "RR", "SC", "SE", "TO"]
    )}
    responses.add(responses.GET, f"{URL_BASE}manifest.json", json=_manifest(corpos), status=200)
    responses.add(responses.GET, f"{URL_BASE}setores_sp.geojson", body=corpos["SP"], status=200)
    responses.add(responses.GET, f"{URL_BASE}setores_rj.geojson", status=500)

    resultado = runner.invoke(
        app, ["baixar-beluga", "--ufs", "SP,RJ", "--diretorio", str(tmp_path)],
    )

    assert resultado.exit_code == 1
    assert "RJ" in resultado.output
    assert "1/2 UF(s) baixada(s)" in resultado.output
    # Sair com 1 não pode significar jogar fora o que veio: a UF boa tem de
    # estar gravada, ou a falha de uma UF viraria falha de todas.
    assert caminho_setores_beluga("SP", tmp_path).exists()
    assert not caminho_setores_beluga("RJ", tmp_path).exists()
