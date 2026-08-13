"""Cliente de ingestão da malha municipal do IBGE, usado pela camada de vento.

Diferente do CPRM/SGB (setores de risco geológico) e da Open-Meteo (chuva/
vento por coordenada), o IBGE não tem conceito de "estação" nem de setor: a
malha municipal cobre todos os municípios de uma UF de uma vez, num único
GET, sem autenticação. Sem armazenamento local, cada chamada busca ao vivo
(mesmo espírito do cliente Open-Meteo, custo baixo por chamada), ver
.superpowers/specs/2026-08-12-choropleth-vento-municipios-design.md.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import shape

logger = logging.getLogger(__name__)

MALHAS_URL_TEMPLATE = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}"
LOCALIDADES_URL_TEMPLATE = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"


class IBGEFetchError(RuntimeError):
    """Erro ao buscar dados do IBGE (malha municipal ou lista de localidades)."""


def _get_json_com_retry(
    url: str,
    params: dict[str, Any],
    timeout: float,
    max_retries: int,
    backoff_factor: float,
    session: requests.Session,
) -> Any:
    """GET com retry/backoff exponencial, compartilhado por `fetch_municipios` e
    `fetch_nomes_municipios`, mesmas duas chamadas simples ao IBGE, mesma
    lógica de tentativa (mesmo padrão inline usado em `src/ingest/cprm.py`,
    só extraído aqui porque há dois pontos de chamada desde o início)."""
    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao consultar o IBGE (%s, tentativa %d/%d): %s. Aguardando %.1fs.",
                url, tentativa, max_retries, exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)

    raise IBGEFetchError(
        f"Não foi possível consultar {url} após {max_retries} tentativas"
    ) from last_exc


def fetch_municipios(
    uf: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
) -> gpd.GeoDataFrame:
    """Busca os polígonos de todos os municípios de uma UF na malha do IBGE.

    Retorna um `GeoDataFrame` com colunas `codarea` (código IBGE, string) e
    `geometry` (Polygon/MultiPolygon, EPSG:4326). A malha não traz nome de
    município, só código (ver `fetch_nomes_municipios` para o nome).
    `qualidade=minima` mantém o payload pequeno (~310KB para os 645
    municípios de SP), suficiente para desenho num mapa web, não para
    análise geométrica de precisão.
    """
    sess = session or requests.Session()
    payload = _get_json_com_retry(
        MALHAS_URL_TEMPLATE.format(uf=uf.strip().upper()),
        {"formato": "application/vnd.geo+json", "qualidade": "minima", "intrarregiao": "municipio"},
        timeout, max_retries, backoff_factor, sess,
    )
    features = payload.get("features", [])
    if not features:
        raise IBGEFetchError(
            f"Malha municipal do IBGE para UF={uf.strip().upper()} veio sem "
            "nenhuma feature (resposta 200 OK, mas 'features' vazio ou ausente)"
        )
    codareas = [str(f["properties"]["codarea"]) for f in features]
    geometrias = [shape(f["geometry"]) for f in features]
    return gpd.GeoDataFrame({"codarea": codareas}, geometry=geometrias, crs="EPSG:4326")


def fetch_nomes_municipios(
    uf: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Busca `{codarea: nome}` de todos os municípios de uma UF, via a API
    de localidades do IBGE (não traz geometria, só serve pra dar nome
    legível ao código da malha)."""
    sess = session or requests.Session()
    payload = _get_json_com_retry(
        LOCALIDADES_URL_TEMPLATE.format(uf=uf.strip().upper()),
        {}, timeout, max_retries, backoff_factor, sess,
    )
    try:
        return {str(item["id"]): item["nome"] for item in payload}
    except (TypeError, KeyError) as exc:
        raise IBGEFetchError(
            f"Resposta da API de localidades do IBGE para UF={uf.strip().upper()} "
            f"não tem o formato esperado (lista de objetos com 'id' e 'nome'): {exc}"
        ) from exc
