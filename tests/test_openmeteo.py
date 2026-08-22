import json as json_module
import time

import pandas as pd
import pytest
import responses

import src.ingest.openmeteo as openmeteo
from src.ingest.openmeteo import FORECAST_URL, OpenMeteoFetchError, fetch_precipitacao_batch
from src.storage_cache_openmeteo import CacheOpenMeteo


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


def test_horas_no_intervalo_gera_uma_por_hora_exclusive_no_fim():
    from src.ingest.openmeteo import _horas_no_intervalo

    inicio = pd.Timestamp("2026-08-10T00:00", tz="UTC")
    fim = pd.Timestamp("2026-08-10T03:00", tz="UTC")
    assert _horas_no_intervalo(inicio, fim) == [
        "2026-08-10T00:00", "2026-08-10T01:00", "2026-08-10T02:00",
    ]


def test_horas_no_intervalo_fim_antes_do_inicio_retorna_vazio():
    from src.ingest.openmeteo import _horas_no_intervalo

    inicio = pd.Timestamp("2026-08-10T03:00", tz="UTC")
    fim = pd.Timestamp("2026-08-10T00:00", tz="UTC")
    assert _horas_no_intervalo(inicio, fim) == []


def test_dias_historico_efetivo_sem_cache_retorna_original():
    from src.ingest.openmeteo import _dias_historico_efetivo

    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    resultado = _dias_historico_efetivo([(-23.5, -46.6)], "chuva_mm", 30, None, agora)
    assert resultado == 30


def test_dias_historico_efetivo_cache_vazio_retorna_original(tmp_path):
    from src.ingest.openmeteo import _dias_historico_efetivo
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    resultado = _dias_historico_efetivo([(-23.5, -46.6)], "chuva_mm", 30, cache, agora)
    assert resultado == 30


def test_dias_historico_efetivo_tudo_cacheado_retorna_minimo(tmp_path):
    from src.ingest.openmeteo import DIAS_HISTORICO_MINIMO, _dias_historico_efetivo, _horas_no_intervalo
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    horas = _horas_no_intervalo(
        agora.floor("h") - pd.Timedelta(days=30),
        agora.floor("h") - pd.Timedelta(hours=3),
    )
    cache.gravar([(ponto, h, 1.0) for h in horas], "chuva_mm", agora.isoformat())

    resultado = _dias_historico_efetivo([ponto], "chuva_mm", 30, cache, agora)

    assert resultado == DIAS_HISTORICO_MINIMO


def test_dias_historico_efetivo_so_ultimo_dia_faltando(tmp_path):
    from src.ingest.openmeteo import _dias_historico_efetivo, _horas_no_intervalo
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    # Cacheia tudo exceto o último dia antes da janela "sempre expira".
    horas_cacheadas = _horas_no_intervalo(
        agora.floor("h") - pd.Timedelta(days=30),
        agora.floor("h") - pd.Timedelta(days=1),
    )
    cache.gravar([(ponto, h, 1.0) for h in horas_cacheadas], "chuva_mm", agora.isoformat())

    resultado = _dias_historico_efetivo([ponto], "chuva_mm", 30, cache, agora)

    assert resultado <= 2  # só falta ~1 dia + a janela sempre-expira, não os 30 originais
    assert resultado >= 1


def test_dias_historico_efetivo_ponto_nunca_visto_retorna_original(tmp_path):
    from src.ingest.openmeteo import _dias_historico_efetivo
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    resultado = _dias_historico_efetivo([(-23.5, -46.6)], "chuva_mm", 30, cache, agora)
    assert resultado == 30


def test_dias_historico_efetivo_pior_caso_entre_varios_pontos_domina(tmp_path):
    from src.ingest.openmeteo import _dias_historico_efetivo, _horas_no_intervalo
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto_cacheado = (-23.5, -46.6)
    ponto_novo = (-22.9, -43.2)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    horas = _horas_no_intervalo(
        agora.floor("h") - pd.Timedelta(days=30),
        agora.floor("h") - pd.Timedelta(hours=3),
    )
    cache.gravar([(ponto_cacheado, h, 1.0) for h in horas], "chuva_mm", agora.isoformat())

    resultado = _dias_historico_efetivo([ponto_cacheado, ponto_novo], "chuva_mm", 30, cache, agora)

    assert resultado == 30  # ponto_novo nunca foi cacheado, domina o pior caso


@responses.activate
def test_fetch_variavel_batch_usa_cache_para_encolher_past_days(tmp_path):
    from src.ingest.openmeteo import _fetch_variavel_batch
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")

    # Pré-popula o cache com 29 dos 30 dias de histórico pedidos.
    horas_cacheadas = [
        h for h in pd.date_range(
            agora.floor("h") - pd.Timedelta(days=30), agora.floor("h") - pd.Timedelta(days=1), freq="h",
        ).strftime("%Y-%m-%dT%H:%M")
    ]
    cache.gravar([(ponto, h, 1.0) for h in horas_cacheadas], "precipitation", agora.isoformat())

    corpos_recebidos = []

    def callback(request):
        corpo = json_module.loads(request.body)
        corpos_recebidos.append(corpo)
        horas = ["2026-08-10T10:00", "2026-08-10T11:00"]
        return (200, {}, json_module.dumps({
            "latitude": ponto[0], "longitude": ponto[1],
            "hourly": {"time": horas, "precipitation": [5.0, 6.0]},
        }))

    responses.add_callback(responses.POST, FORECAST_URL, callback=callback, content_type="application/json")

    series = _fetch_variavel_batch(
        [ponto], "precipitation", "chuva_mm",
        dias_historico=30, dias_previsao=1, timeout=60.0, max_retries=1, backoff_factor=0.01,
        session=None, tamanho_lote=50, cache=cache, agora=agora,
    )

    assert corpos_recebidos[0]["past_days"] <= 2  # bem menor que os 30 originais
    total_horas = len(series[0])
    # ~29 dias cacheados (696h) + as horas novas da API, série completa preservada.
    # Nota: o cache foi populado com exatamente 697 horas e a API mockada
    # devolve só 2 horas novas (não sobrepostas), então o máximo teórico é
    # 699 — o limiar original do brief (>700) era inatingível por qualquer
    # implementação; ver task-3-report.md.
    assert total_horas > 690


@responses.activate
def test_fetch_variavel_batch_grava_resposta_no_cache(tmp_path):
    from src.ingest.openmeteo import _fetch_variavel_batch
    from src.storage_cache_openmeteo import CacheOpenMeteo

    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    horas = ["2026-08-10T09:00", "2026-08-10T10:00"]
    responses.add(
        responses.POST, FORECAST_URL, status=200,
        json={"latitude": ponto[0], "longitude": ponto[1], "hourly": {"time": horas, "precipitation": [1.0, 2.0]}},
    )

    _fetch_variavel_batch(
        [ponto], "precipitation", "chuva_mm",
        dias_historico=1, dias_previsao=1, timeout=60.0, max_retries=1, backoff_factor=0.01,
        session=None, tamanho_lote=50, cache=cache, agora=agora,
    )

    lido = cache.ler([ponto], "precipitation", horas)
    assert lido == {ponto: {"2026-08-10T09:00": 1.0, "2026-08-10T10:00": 2.0}}


@responses.activate
def test_fetch_variavel_batch_sem_cache_comportamento_identico_a_hoje():
    from src.ingest.openmeteo import _fetch_variavel_batch

    horas = ["2026-08-10T00:00"]
    responses.add(
        responses.POST, FORECAST_URL, status=200,
        json={"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "precipitation": [1.0]}},
    )

    series = _fetch_variavel_batch(
        [(-23.5, -46.6)], "precipitation", "chuva_mm",
        dias_historico=30, dias_previsao=1, timeout=60.0, max_retries=1, backoff_factor=0.01,
        session=None, tamanho_lote=50,
    )

    assert len(series) == 1
    assert list(series[0]["chuva_mm"]) == [1.0]


@responses.activate
def test_fetch_precipitacao_batch_aceita_cache_e_agora(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    horas = ["2026-08-10T00:00"]
    responses.add(
        responses.POST, FORECAST_URL, status=200,
        json={"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "precipitation": [1.0]}},
    )

    series = fetch_precipitacao_batch(
        [(-23.5, -46.6)], cache=cache, agora=pd.Timestamp("2026-08-10T05:00", tz="UTC"),
    )

    assert list(series[0]["chuva_mm"]) == [1.0]
    assert cache.ler([(-23.5, -46.6)], "precipitation", horas) != {}
