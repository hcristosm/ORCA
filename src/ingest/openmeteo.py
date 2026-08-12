"""Cliente da API Open-Meteo — chuva horária por coordenada, quase em tempo real.

Diferente do INMET (ZIP anual, dias de defasagem) e da ANA (rede de estações
telemétricas, cobertura parcial), a Open-Meteo (https://open-meteo.com/) não
tem o conceito de estação: qualquer coordenada pode ser consultada
diretamente. Isso permite computar a chuva acumulada no próprio centro de
cada setor de risco, sem precisar de "estação mais próxima" (ver
src/export/dashboard_data.py).

Investigação em 10/08/2026 (requisições reais): `POST` com `latitude`/
`longitude` como arrays no corpo é obrigatório — `GET` com muitas
coordenadas na query string esbarra em `HTTP 414 URI Too Long` bem antes de
chegar a centenas de pontos. O parâmetro `timezone` não pode ser enviado
como string simples nesse modo (a API exige um array, um valor por
coordenada); omiti-lo faz a API responder em GMT, equivalente a UTC para os
fins deste projeto.

Um único `POST` com as ~900 coordenadas dos setores de SP chegou a responder
em ~2s numa primeira tentativa isolada, mas testes seguintes (e uma
exportação real) esbarraram em `HTTP 429 Minutely API request limit
exceeded` de forma consistente, mesmo aguardando um minuto inteiro — o
limite prático parece ser sobre o *tamanho* do lote, não só sobre a
frequência de chamadas. Testado e confirmado estável: lotes de até 100
pontos, inclusive em sequência rápida (1s de intervalo). Por isso este
cliente divide `pontos` em lotes de `tamanho_lote` (padrão 100) e faz uma
chamada por lote, com uma pequena pausa entre elas.

Sem cache/armazenamento local: cada exportação consulta a API ao vivo, o que
é viável porque o custo por chamada é baixo — não há aqui o problema de
"baixar o ano inteiro de novo" que motivou a ingestão incremental do INMET.
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TAMANHO_LOTE_PADRAO = 50
PAUSA_ENTRE_LOTES_PADRAO = 2.0


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
        try:
            resp = session.post(FORECAST_URL, json=corpo, timeout=timeout)
            resp.raise_for_status()
            resposta_ok = resp
            break
        except requests.RequestException as exc:
            last_exc = exc
            # HTTP 429 da Open-Meteo é "Minutely API request limit exceeded" — a
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

    if resposta_ok is None:
        raise OpenMeteoFetchError(
            f"Não foi possível consultar a Open-Meteo após {max_retries} tentativas "
            f"(lote de {len(pontos)} pontos)"
        ) from last_exc

    return resposta_ok.json()


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
    pausa_entre_lotes: float,
) -> list[pd.DataFrame]:
    """Busca uma variável horária da Open-Meteo para uma lista de pontos, em lotes.

    Compartilhada por `fetch_precipitacao_batch` (variavel="precipitation") e
    `fetch_vento_batch` (variavel="windgusts_10m") — mesma paginação, retry e
    tratamento de 429, só muda qual campo é pedido/lido da resposta.
    """
    if not pontos:
        return []

    sess = session or requests.Session()
    dados: list[dict] = []
    for inicio in range(0, len(pontos), tamanho_lote):
        lote = pontos[inicio:inicio + tamanho_lote]
        dados.extend(
            _post_lote(
                lote, [variavel_hourly], dias_historico, dias_previsao,
                timeout, max_retries, backoff_factor, sess,
            )
        )
        if inicio + tamanho_lote < len(pontos):
            time.sleep(pausa_entre_lotes)

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
    pausa_entre_lotes: float = PAUSA_ENTRE_LOTES_PADRAO,
) -> list[pd.DataFrame]:
    """Busca chuva horária para uma lista de pontos `(lat, lon)`.

    Retorna uma lista de DataFrames (`data_hora, chuva_mm`), um por ponto, na
    mesma ordem de `pontos`. `dias_historico` controla quantos dias para trás
    são pedidos e `dias_previsao` quantos dias de previsão para frente (a
    API aceita até 92 e 16 respectivamente) — filtrar por "é passado" ou
    "é futuro" é responsabilidade de quem consome o DataFrame, não deste
    cliente.

    Internamente, `pontos` é dividido em lotes de `tamanho_lote` (padrão 100,
    ver docstring do módulo sobre o limite prático da API), com uma pausa de
    `pausa_entre_lotes` segundos entre as chamadas.
    """
    return _fetch_variavel_batch(
        pontos, "precipitation", "chuva_mm", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, pausa_entre_lotes,
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
    pausa_entre_lotes: float = PAUSA_ENTRE_LOTES_PADRAO,
) -> list[pd.DataFrame]:
    """Busca rajada de vento (`windgusts_10m`) horária para uma lista de pontos `(lat, lon)`.

    Mesmo cliente/lote/retry de `fetch_precipitacao_batch` — reaproveita
    `_fetch_variavel_batch`. Retorna uma lista de DataFrames
    (`data_hora, vento_rajada_kmh`), um por ponto, na mesma ordem de `pontos`.
    """
    return _fetch_variavel_batch(
        pontos, "windgusts_10m", "vento_rajada_kmh", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, pausa_entre_lotes,
    )
