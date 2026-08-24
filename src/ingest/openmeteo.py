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
from src.storage_cache_openmeteo import CacheOpenMeteo

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
# `max_concorrentes=1`: confirmado por um mantenedor da Open-Meteo (issue
# open-meteo/open-meteo#1650, 22/08/2026) que a camada gratuita permite
# só 1 requisição EM VOO por IP — acima disso, a requisição fica na fila
# interna deles e, com mais de 5 na fila, vira erro "Too many concurrent
# requests". Testamos com `max_concorrentes=4` em produção e o resultado
# não melhorou sobre o baseline sem limiter algum — bate com esse limite
# real ser 1, não um número maior que dava pra tunar. `intervalo_minimo_
# segundos=0.15` continua útil para não haver duas concessões no mesmo
# instante quando o slot único libera.
LIMITER_PADRAO = RateLimiter(
    max_por_minuto=500, max_por_hora=4500,
    intervalo_minimo_segundos=0.15, max_concorrentes=1,
)

JANELA_SEMPRE_EXPIRA_HORAS = 3
DIAS_HISTORICO_MINIMO = 1


def _horas_no_intervalo(inicio: pd.Timestamp, fim: pd.Timestamp) -> list[str]:
    """Horas (ISO 8601, ex. "2026-08-10T00:00") de `inicio` até `fim`, exclusive no fim."""
    if fim <= inicio:
        return []
    return pd.date_range(inicio, fim, freq="h", inclusive="left").strftime("%Y-%m-%dT%H:%M").tolist()


def _dias_historico_efetivo(
    pontos: list[tuple[float, float]],
    variavel: str,
    dias_historico: int,
    cache: CacheOpenMeteo | None,
    agora: pd.Timestamp,
) -> int:
    """Quanto de `dias_historico` ainda precisa ser pedido à API, dado o que já
    está cacheado para `pontos`. Sem cache, ou sem nada cacheado, retorna
    `dias_historico` inalterado (comportamento de hoje).
    """
    if cache is None:
        return dias_historico
    corte = agora.floor("h") - pd.Timedelta(hours=JANELA_SEMPRE_EXPIRA_HORAS)
    inicio = agora.floor("h") - pd.Timedelta(days=dias_historico)
    horas_esperadas = _horas_no_intervalo(inicio, corte)
    if not horas_esperadas:
        return dias_historico
    faltantes = cache.horas_faltantes(pontos, variavel, horas_esperadas)
    if not faltantes:
        return DIAS_HISTORICO_MINIMO
    hora_mais_antiga = min(h for horas in faltantes.values() for h in horas)
    inicio_faltante = pd.Timestamp(hora_mais_antiga).tz_localize("UTC")
    # O teto é medido contra `agora`, não contra `corte`: a cobertura que a API
    # precisa entregar vai de `inicio_faltante` até agora, e `past_days` conta
    # a partir de agora. Medir contra `corte` (agora - 3h) deixa a janela ~3h
    # curta quando (corte - inicio_faltante) cai num múltiplo exato de dias.
    dias_necessarios = -(-(agora.floor("h") - inicio_faltante).total_seconds() // 86400)  # ceil
    return int(max(DIAS_HISTORICO_MINIMO, min(dias_historico, dias_necessarios)))


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


def _serie_do_gap(
    ponto: tuple[float, float],
    variavel_hourly: str,
    coluna_saida: str,
    dias_historico: int,
    dias_historico_lote: int,
    cache: CacheOpenMeteo | None,
    agora: pd.Timestamp,
) -> pd.DataFrame:
    """Horas que o POST (encolhido para `dias_historico_lote`) não cobriu, mas
    o chamador pediu (`dias_historico`), reconstruídas a partir do cache."""
    vazio = pd.DataFrame(columns=["data_hora", coluna_saida])
    if cache is None or dias_historico_lote >= dias_historico:
        return vazio
    corte = agora.floor("h") - pd.Timedelta(hours=JANELA_SEMPRE_EXPIRA_HORAS)
    inicio_completo = agora.floor("h") - pd.Timedelta(days=dias_historico)
    inicio_lote = agora.floor("h") - pd.Timedelta(days=dias_historico_lote)
    horas_gap = _horas_no_intervalo(inicio_completo, min(inicio_lote, corte))
    if not horas_gap:
        return vazio
    cacheado = cache.ler([ponto], variavel_hourly, horas_gap)
    linhas = cacheado.get(ponto, {})
    if not linhas:
        return vazio
    return pd.DataFrame({
        "data_hora": pd.to_datetime(list(linhas.keys()), utc=True),
        coluna_saida: list(linhas.values()),
    })


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
    cache: CacheOpenMeteo | None = None,
    agora: pd.Timestamp | None = None,
) -> list[pd.DataFrame]:
    """Busca uma variável horária da Open-Meteo para uma lista de pontos, em lotes.

    Usada por `fetch_precipitacao_batch` (variavel="precipitation"); campo
    pedido/lido da resposta é parametrizado por `variavel_hourly`.

    `cache`, se informado, encolhe o `past_days` de cada lote para só o que
    ainda falta (ver `_dias_historico_efetivo`) e reconstrói a série completa
    pedida mesclando a resposta da API com o que faltava vir do cache (ver
    `_serie_do_gap`) — quem chama sempre recebe a janela completa que pediu,
    igual a hoje, só que parte dela pode ter vindo do cache em vez da rede.
    `cache=None` (padrão) reproduz o comportamento de hoje: sem cache, sem
    encolhimento, série inteira sempre vem da API.

    Os lotes são disparados concorrentemente (thread pool), não um a um com
    pausa fixa: quem espaça as chamadas de verdade é `LIMITER_PADRAO`
    (compartilhado por todo o processo, inclusive entre UFs em
    `src/export/nacional.py`), não este laço.
    """
    if not pontos:
        return []

    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    sess = session or requests.Session()
    lotes = [pontos[inicio:inicio + tamanho_lote] for inicio in range(0, len(pontos), tamanho_lote)]

    def _buscar_lote(lote: list[tuple[float, float]]) -> list[tuple[tuple[float, float], dict, int]]:
        dias_historico_lote = _dias_historico_efetivo(lote, variavel_hourly, dias_historico, cache, agora)
        payload = _post_lote(
            lote, [variavel_hourly], dias_historico_lote, dias_previsao,
            timeout, max_retries, backoff_factor, sess,
        )
        if cache is not None:
            registros = [
                (ponto, hora, valor)
                for ponto, item in zip(lote, payload)
                for hora, valor in zip(
                    item.get("hourly", {}).get("time", []),
                    item.get("hourly", {}).get(variavel_hourly, []),
                )
            ]
            cache.gravar(registros, variavel_hourly, agora.isoformat())
        return [(ponto, item, dias_historico_lote) for ponto, item in zip(lote, payload)]

    with ThreadPoolExecutor(max_workers=max_workers_lote) as executor:
        resultados_lotes = list(executor.map(_buscar_lote, lotes))
    pares = [par for resultado_lote in resultados_lotes for par in resultado_lote]

    series = []
    for ponto, item, dias_historico_lote in pares:
        horario = item.get("hourly", {})
        df_api = pd.DataFrame({
            "data_hora": pd.to_datetime(horario.get("time", []), utc=True),
            coluna_saida: horario.get(variavel_hourly, []),
        })
        df_gap = _serie_do_gap(ponto, variavel_hourly, coluna_saida, dias_historico, dias_historico_lote, cache, agora)
        serie = pd.concat([df_gap, df_api], ignore_index=True) if not df_gap.empty else df_api
        # `past_days` da Open-Meteo é alinhado a dia corrido (GMT), não à hora
        # de `agora`, então a resposta da API pode se sobrepor às horas vindas
        # do cache. Sem deduplicar, essas horas entrariam duas vezes e
        # inflariam a chuva acumulada de 72h. `kind="stable"` + `keep="last"`
        # garante que, no empate, vence a linha da API (concatenada depois).
        series.append(
            serie.sort_values("data_hora", kind="stable")
            .drop_duplicates("data_hora", keep="last")
            .reset_index(drop=True)
        )
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
    cache: CacheOpenMeteo | None = None,
    agora: pd.Timestamp | None = None,
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
    `cache`, se informado, reduz o histórico de fato pedido à API (ver
    `_fetch_variavel_batch`); `agora` é parametrizável para testes
    determinísticos, em produção usa o instante atual.
    """
    return _fetch_variavel_batch(
        pontos, "precipitation", "chuva_mm", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, max_workers_lote,
        cache, agora,
    )
