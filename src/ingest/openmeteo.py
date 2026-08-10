"""Cliente da API Open-Meteo — chuva horária por coordenada, quase em tempo real.

Diferente do INMET (ZIP anual, dias de defasagem) e da ANA (rede de estações
telemétricas, cobertura parcial), a Open-Meteo (https://open-meteo.com/) não
tem o conceito de estação: qualquer coordenada pode ser consultada
diretamente. Isso permite computar a chuva acumulada no próprio centro de
cada setor de risco, sem precisar de "estação mais próxima" (ver
src/export/dashboard_data.py).

Investigação em 10/08/2026 (requisições reais): a API aceita todas as ~900
coordenadas de um estado numa única requisição POST (testado com os 904
setores de SP: ~2s, sem paginar). GET com muitas coordenadas na query string
esbarra em HTTP 414 (URI Too Long) bem antes disso — por isso este cliente
usa POST. O parâmetro `timezone` não pode ser enviado como string simples
nesse modo (a API exige um array, um valor por coordenada); omiti-lo faz a
API responder em GMT, equivalente a UTC para os fins deste projeto.

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


class OpenMeteoFetchError(RuntimeError):
    """Erro ao buscar dados de chuva da Open-Meteo."""


def fetch_precipitacao_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 30,
    timeout: float = 60.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
) -> list[pd.DataFrame]:
    """Busca chuva horária para uma lista de pontos `(lat, lon)`, numa única requisição.

    Retorna uma lista de DataFrames (`data_hora, chuva_mm`), um por ponto, na
    mesma ordem de `pontos`. `dias_historico` controla quantos dias para trás
    são pedidos (a API aceita até 92); `forecast_days=1` garante que a hora
    mais recente disponível entra na resposta — filtrar por "não é futuro" é
    responsabilidade de quem consome o DataFrame, não deste cliente.
    """
    if not pontos:
        return []

    sess = session or requests.Session()
    corpo = {
        "latitude": [lat for lat, _ in pontos],
        "longitude": [lon for _, lon in pontos],
        "hourly": ["precipitation"],
        "past_days": dias_historico,
        "forecast_days": 1,
    }

    resposta_ok = None
    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = sess.post(FORECAST_URL, json=corpo, timeout=timeout)
            resp.raise_for_status()
            resposta_ok = resp
            break
        except requests.RequestException as exc:
            last_exc = exc
            espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao consultar a Open-Meteo (tentativa %d/%d): %s. Aguardando %.1fs.",
                tentativa, max_retries, exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)

    if resposta_ok is None:
        raise OpenMeteoFetchError(
            f"Não foi possível consultar a Open-Meteo após {max_retries} tentativas"
        ) from last_exc

    dados = resposta_ok.json()
    series = []
    for item in dados:
        horario = item.get("hourly", {})
        horas = horario.get("time", [])
        precipitacoes = horario.get("precipitation", [])
        df = pd.DataFrame(
            {
                "data_hora": pd.to_datetime(horas, utc=True),
                "chuva_mm": precipitacoes,
            }
        )
        series.append(df)
    return series
