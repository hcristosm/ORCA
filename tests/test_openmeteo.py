import json as json_module
import time

import pandas as pd
import pytest
import responses

import src.ingest.openmeteo as openmeteo
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
def test_fetch_precipitacao_batch_lote_de_1_ponto_resposta_e_objeto_nao_lista():
    # A Open-Meteo devolve um objeto único (não envolto em lista) quando o
    # POST tem só 1 coordenada, diferente do array que devolve para lotes
    # maiores (ver test_fetch_precipitacao_batch_parseia_lista_na_ordem_dos_pontos).
    # Reproduzido em produção: lote de 1 ponto (sobra de divisão de lote, ou
    # UF com só 1 município/setor) quebrava com
    # "AttributeError: 'str' object has no attribute 'get'" porque
    # `dados.extend(dict)` iterava as chaves do dict como strings.
    horas = ["2026-08-10T00:00", "2026-08-10T01:00"]
    resposta_objeto = {
        "latitude": -23.5, "longitude": -46.6,
        "hourly": {"time": horas, "precipitation": [0.0, 1.2]},
    }
    responses.add(responses.POST, FORECAST_URL, json=resposta_objeto, status=200)

    series = fetch_precipitacao_batch([(-23.5, -46.6)])

    assert len(series) == 1
    assert list(series[0]["chuva_mm"]) == [0.0, 1.2]


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
    # Os 2 lotes são disparados concorrentemente, então a resposta de cada um
    # precisa depender do CONTEÚDO do request (quantos pontos pediu), não da
    # ordem de chegada — daí o callback, em vez de `responses.add()` em fila.
    horas = ["2026-08-10T00:00"]
    pontos = [(-23.0 - i * 0.01, -46.0) for i in range(5)]

    def callback(request):
        corpo = json_module.loads(request.body)
        n = len(corpo["latitude"])
        valores = [1.0, 2.0, 3.0] if n == 3 else [4.0, 5.0]
        return (200, {}, json_module.dumps(_resposta(horas, [[v] for v in valores])))

    responses.add_callback(responses.POST, FORECAST_URL, callback=callback, content_type="application/json")

    series = fetch_precipitacao_batch(pontos, tamanho_lote=3)

    assert len(responses.calls) == 2
    assert [s["chuva_mm"].iloc[0] for s in series] == [1.0, 2.0, 3.0, 4.0, 5.0]


@responses.activate
def test_fetch_precipitacao_batch_busca_lotes_concorrentemente(monkeypatch):
    """Os lotes são disparados em paralelo (thread pool), não um a um com pausa.

    Cada resposta simulada demora 0.1s pra "chegar"; se os 4 lotes fossem
    buscados um a um, o total seria >= 0.4s. Concorrente, fica bem abaixo. O
    espaçamento mínimo entre requisições do `LIMITER_PADRAO` (ver
    `test_rate_limiter.py`) é neutralizado aqui para isolar só a concorrência
    do thread pool.
    """
    monkeypatch.setattr(openmeteo.LIMITER_PADRAO, "acquire", lambda: None)
    monkeypatch.setattr(openmeteo.LIMITER_PADRAO, "release", lambda: None)
    horas = ["2026-08-10T00:00"]
    pontos = [(-23.0 - i * 0.01, -46.0) for i in range(4)]

    def callback(request):
        time.sleep(0.1)
        return (200, {}, json_module.dumps(_resposta(horas, [[1.0]])[0]))

    for _ in range(4):
        responses.add_callback(responses.POST, FORECAST_URL, callback=callback, content_type="application/json")

    inicio = time.monotonic()
    fetch_precipitacao_batch(pontos, tamanho_lote=1)
    decorrido = time.monotonic() - inicio

    assert decorrido < 0.35


@responses.activate
def test_fetch_precipitacao_batch_usa_rate_limiter_compartilhado(monkeypatch):
    chamadas = []
    monkeypatch.setattr(openmeteo.LIMITER_PADRAO, "acquire", lambda: chamadas.append(1))
    monkeypatch.setattr(openmeteo.LIMITER_PADRAO, "release", lambda: None)

    horas = ["2026-08-10T00:00"]
    pontos = [(-23.0 - i * 0.01, -46.0) for i in range(3)]
    for valor in [[1.0], [2.0], [3.0]]:
        responses.add(responses.POST, FORECAST_URL, json=_resposta(horas, [valor]), status=200)

    fetch_precipitacao_batch(pontos, tamanho_lote=1)

    assert len(chamadas) == 3


@responses.activate
def test_fetch_precipitacao_batch_usa_dias_previsao_no_corpo():
    import json as json_module

    resposta = _resposta(["2026-08-10T00:00"], [[1.0]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    fetch_precipitacao_batch([(-23.5, -46.6)], dias_previsao=3)

    corpo_enviado = json_module.loads(responses.calls[0].request.body)
    assert corpo_enviado["forecast_days"] == 3


def test_fetch_vento_batch_parseia_windgusts_na_ordem_dos_pontos():
    from src.ingest.openmeteo import fetch_vento_batch

    horas = ["2026-08-10T00:00", "2026-08-10T01:00"]
    resposta = [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "windgusts_10m": [40.0, 90.0]}},
        {"latitude": -24.0, "longitude": -47.0, "hourly": {"time": horas, "windgusts_10m": [10.0, 15.0]}},
    ]

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        series = fetch_vento_batch([(-23.5, -46.6), (-24.0, -47.0)])

    assert len(series) == 2
    assert list(series[0]["vento_rajada_kmh"]) == [40.0, 90.0]
    assert list(series[1]["vento_rajada_kmh"]) == [10.0, 15.0]


def test_fetch_vento_batch_envia_windgusts_no_corpo():
    import json as json_module

    from src.ingest.openmeteo import fetch_vento_batch

    horas = ["2026-08-10T00:00"]
    resposta = [{"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "windgusts_10m": [40.0]}}]

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        fetch_vento_batch([(-23.5, -46.6)])
        corpo_enviado = json_module.loads(rsps.calls[0].request.body)
        assert corpo_enviado["hourly"] == ["windgusts_10m"]
