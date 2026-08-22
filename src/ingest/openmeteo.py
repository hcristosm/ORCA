"""Cliente da API Open-Meteo, chuva horária por coordenada, quase em tempo real.

Diferente do INMET (ZIP anual, dias de defasagem) e da ANA (rede de estações
telemétricas, cobertura parcial), a Open-Meteo (https://open-meteo.com/) não
tem o conceito de estação: qualquer coordenada pode ser consultada
diretamente. Isso permite computar a chuva acumulada no próprio centro de
cada setor de risco, sem precisar de "estação mais próxima" (ver
src/export/dashboard_data.py).

Investigação em 10/08/2026 (requisições reais): `POST` com `latitude`/
`longitude` como arrays no corpo é obrigatório; `GET` com muitas
coordenadas na query string esbarra em `HTTP 414 URI Too Long` bem antes de
chegar a centenas de pontos. O parâmetro `timezone` não pode ser enviado
como string simples nesse modo (a API exige um array, um valor por
coordenada); omiti-lo faz a API responder em GMT, equivalente a UTC para os
fins deste projeto.

Um único `POST` com as ~900 coordenadas dos setores de SP chegou a responder
em ~2s numa primeira tentativa isolada, mas testes seguintes (e uma
exportação real) esbarraram em `HTTP 429 Minutely API request limit
exceeded` de forma consistente, mesmo aguardando um minuto inteiro. O
limite prático parece ser sobre o *tamanho* do lote, não só sobre a
frequência de chamadas. Testado e confirmado estável: lotes de até 100
pontos, inclusive em sequência rápida (1s de intervalo). Por isso este
cliente divide `pontos` em lotes de `tamanho_lote` (padrão 100) e faz uma
chamada por lote, com uma pequena pausa entre elas.

Sem cache/armazenamento local: cada exportação consulta a API ao vivo, o que
é viável porque o custo por chamada é baixo; não há aqui o problema de
"baixar o ano inteiro de novo" que motivou a ingestão incremental do INMET.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from src.ingest.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TAMANHO_LOTE_PADRAO = 50
LOTE_WORKERS_PADRAO = 5

# Tetos documentados da Open-Meteo são 600/min e 5.000/hora; ficamos abaixo
# disso de propósito porque o cliente já observou 429 mesmo em cadência
# conservadora (ver docstring do módulo). O limiter é compartilhado por todo
# o processo, então cobre tanto a concorrência entre lotes de uma UF quanto
# entre UFs (ver `src/export/nacional.py`).
#
# `intervalo_minimo_segundos=0.15` (~6,7 req/s) evita que várias threads
# liberadas pela janela de contagem disparem a requisição no mesmo instante.
# Isso sozinho não bastou em produção: uma requisição pode ficar em voo por
# vários segundos (ou até 60s esperando um 429), então dezenas continuam
# abertas ao mesmo tempo mesmo começando escalonadas. `max_concorrentes=4`
# põe um teto real em quantas ficam simultaneamente em voo — ver
# `src/ingest/rate_limiter.py` e `_post_lote` abaixo (que faz acquire/release
# por tentativa, não só uma vez por lote).
LIMITER_PADRAO = RateLimiter(
    max_por_minuto=500, max_por_hora=4500,
    intervalo_minimo_segundos=0.15, max_concorrentes=4,
)


class OpenMeteoFetchError(RuntimeError):
    """Erro ao buscar dados de chuva da Open-Meteo."""


def _post_lote(
    pontos: list[tuple[float, float]],
    variaveis_hourly: list[str],
    dias_historico: int,
    dias_previsao: int,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
    session: requests.Session,
    limiter: RateLimiter = LIMITER_PADRAO,
) -> list[dict]:
    """Um único POST para um lote de pontos. Retorna a lista de objetos da resposta (um por ponto)."""
    corpo = {
        "latitude": [lat for lat, _ in pontos],
        "longitude": [lon for _, lon in pontos],
        "hourly": variaveis_hourly,
        "past_days": dias_historico,
        "forecast_days": dias_previsao,
    }

    resposta_ok = None
    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        limiter.acquire()
        try:
            resp = session.post(FORECAST_URL, json=corpo, timeout=timeout)
            resp.raise_for_status()
            resposta_ok = resp
            break
        except requests.RequestException as exc:
            last_exc = exc
            # HTTP 429 da Open-Meteo é "Minutely API request limit exceeded"; a
            # própria API pede pra tentar de novo em um minuto; o backoff
            # exponencial normal (poucos segundos) não é suficiente para isso.
            if exc.response is not None and exc.response.status_code == 429:
                espera = 60.0
            else:
                espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao consultar a Open-Meteo (tentativa %d/%d, lote de %d pontos): %s. "
                "Aguardando %.1fs.",
                tentativa, max_retries, len(pontos), exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)
        finally:
            # Libera o slot de concorrência assim que a resposta (ou erro)
            # desta tentativa chega — não durante a espera de backoff acima,
            # que não ocupa uma conexão.
            limiter.release()

    if resposta_ok is None:
        raise OpenMeteoFetchError(
            f"Não foi possível consultar a Open-Meteo após {max_retries} tentativas "
            f"(lote de {len(pontos)} pontos)"
        ) from last_exc

    payload = resposta_ok.json()
    # A API devolve um objeto único (não uma lista) quando o lote tem só 1
    # coordenada, diferente do array que devolve para lotes maiores; sem
    # normalizar aqui, `_fetch_variavel_batch` (que sempre espera uma lista
    # de objetos) quebra iterando as chaves do dict como se fossem itens.
    return payload if isinstance(payload, list) else [payload]


def _fetch_variavel_batch(
    pontos: list[tuple[float, float]],
    variavel_hourly: str,
    coluna_saida: str,
    dias_historico: int,
    dias_previsao: int,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
    session: requests.Session | None,
    tamanho_lote: int,
    max_workers_lote: int = LOTE_WORKERS_PADRAO,
) -> list[pd.DataFrame]:
    """Busca uma variável horária da Open-Meteo para uma lista de pontos, em lotes.

    Compartilhada por `fetch_precipitacao_batch` (variavel="precipitation") e
    `fetch_vento_batch` (variavel="windgusts_10m"), mesma paginação, retry e
    tratamento de 429, só muda qual campo é pedido/lido da resposta.

    Os lotes são disparados concorrentemente (thread pool), não um a um com
    pausa fixa: quem espaça as chamadas de verdade é `LIMITER_PADRAO`
    (compartilhado por todo o processo, inclusive entre UFs em
    `src/export/nacional.py`), não este laço.
    """
    if not pontos:
        return []

    sess = session or requests.Session()
    lotes = [pontos[inicio:inicio + tamanho_lote] for inicio in range(0, len(pontos), tamanho_lote)]

    with ThreadPoolExecutor(max_workers=max_workers_lote) as executor:
        resultados = list(executor.map(
            lambda lote: _post_lote(
                lote, [variavel_hourly], dias_historico, dias_previsao,
                timeout, max_retries, backoff_factor, sess,
            ),
            lotes,
        ))
    dados: list[dict] = [item for resultado_lote in resultados for item in resultado_lote]

    series = []
    for item in dados:
        horario = item.get("hourly", {})
        horas = horario.get("time", [])
        valores = horario.get(variavel_hourly, [])
        series.append(pd.DataFrame({
            "data_hora": pd.to_datetime(horas, utc=True),
            coluna_saida: valores,
        }))
    return series


def fetch_precipitacao_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 30,
    dias_previsao: int = 1,
    timeout: float = 60.0,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    max_workers_lote: int = LOTE_WORKERS_PADRAO,
) -> list[pd.DataFrame]:
    """Busca chuva horária para uma lista de pontos `(lat, lon)`.

    Retorna uma lista de DataFrames (`data_hora, chuva_mm`), um por ponto, na
    mesma ordem de `pontos`. `dias_historico` controla quantos dias para trás
    são pedidos e `dias_previsao` quantos dias de previsão para frente (a
    API aceita até 92 e 16 respectivamente); filtrar por "é passado" ou
    "é futuro" é responsabilidade de quem consome o DataFrame, não deste
    cliente.

    Internamente, `pontos` é dividido em lotes de `tamanho_lote` (padrão 100,
    ver docstring do módulo sobre o limite prático da API), buscados em
    paralelo (`max_workers_lote` threads) e pautados por `LIMITER_PADRAO`.
    """
    return _fetch_variavel_batch(
        pontos, "precipitation", "chuva_mm", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, max_workers_lote,
    )


def fetch_vento_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 4,
    dias_previsao: int = 1,
    timeout: float = 60.0,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    max_workers_lote: int = LOTE_WORKERS_PADRAO,
) -> list[pd.DataFrame]:
    """Busca rajada de vento (`windgusts_10m`) horária para uma lista de pontos `(lat, lon)`.

    Mesmo cliente/lote/retry de `fetch_precipitacao_batch`, reaproveita
    `_fetch_variavel_batch`. Retorna uma lista de DataFrames
    (`data_hora, vento_rajada_kmh`), um por ponto, na mesma ordem de `pontos`.
    """
    return _fetch_variavel_batch(
        pontos, "windgusts_10m", "vento_rajada_kmh", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, max_workers_lote,
    )
