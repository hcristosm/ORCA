import pandas as pd
import pytest
import responses

from src.ingest.openmeteo import FORECAST_URL, OpenMeteoFetchError, fetch_precipitacao_batch


def _resposta(horas: list[str], series_chuva: list[list]) -> list[dict]:
    return [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "precipitation": chuva}}
        for chuva in series_chuva
    ]


@responses.activate
def test_fetch_precipitacao_batch_parseia_lista_na_ordem_dos_pontos():
    horas = ["2026-08-10T00:00", "2026-08-10T01:00"]
    resposta = _resposta(horas, [[0.0, 1.2], [0.5, None]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    series = fetch_precipitacao_batch([(-23.5, -46.6), (-22.9, -43.2)])

    assert len(series) == 2
    assert list(series[0]["chuva_mm"]) == [0.0, 1.2]
    assert series[1]["chuva_mm"].isna().iloc[1]
    assert series[0]["data_hora"].dt.tz is not None


def test_fetch_precipitacao_batch_lista_vazia_retorna_vazio():
    assert fetch_precipitacao_batch([]) == []


@responses.activate
def test_fetch_precipitacao_batch_retry_recupera_apos_falha_transitoria():
    responses.add(responses.POST, FORECAST_URL, status=500)
    resposta = _resposta(["2026-08-10T00:00"], [[3.0]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    series = fetch_precipitacao_batch([(-23.5, -46.6)], max_retries=2, backoff_factor=0.01)

    assert len(series) == 1
    assert series[0]["chuva_mm"].iloc[0] == 3.0


@responses.activate
def test_fetch_precipitacao_batch_falha_persistente_levanta_erro():
    responses.add(responses.POST, FORECAST_URL, status=500)

    with pytest.raises(OpenMeteoFetchError):
        fetch_precipitacao_batch([(-23.5, -46.6)], max_retries=2, backoff_factor=0.01)


@responses.activate
def test_fetch_precipitacao_batch_divide_em_lotes_e_preserva_ordem():
    horas = ["2026-08-10T00:00"]
    pontos = [(-23.0 - i * 0.01, -46.0) for i in range(5)]

    responses.add(responses.POST, FORECAST_URL, json=_resposta(horas, [[1.0], [2.0], [3.0]]), status=200)
    responses.add(responses.POST, FORECAST_URL, json=_resposta(horas, [[4.0], [5.0]]), status=200)

    series = fetch_precipitacao_batch(pontos, tamanho_lote=3, pausa_entre_lotes=0)

    assert len(responses.calls) == 2
    assert [s["chuva_mm"].iloc[0] for s in series] == [1.0, 2.0, 3.0, 4.0, 5.0]


@responses.activate
def test_fetch_precipitacao_batch_usa_dias_previsao_no_corpo():
    import json as json_module

    resposta = _resposta(["2026-08-10T00:00"], [[1.0]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    fetch_precipitacao_batch([(-23.5, -46.6)], dias_previsao=3)

    corpo_enviado = json_module.loads(responses.calls[0].request.body)
    assert corpo_enviado["forecast_days"] == 3
