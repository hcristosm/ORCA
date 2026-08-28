"""Cliente de ingestão para a camada de Setorização de Risco Geológico da CPRM/SGB.

Fonte confirmada em 2026-08-05 via GetCapabilities/rest services (ver README):
https://geoportal.sgb.gov.br/server/rest/services/gestaoterritorial/risco/FeatureServer/0

A CPRM foi renomeada para SGB (Serviço Geológico do Brasil); os domínios antigos
(geoportal.cprm.gov.br, sace.cprm.gov.br) ainda respondem mas não hospedam mais
esta camada.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from src.config import caminho_manifesto_cprm, validar_uf as _validar_uf
from src.storage import ler_setores, salvar_setores

logger = logging.getLogger(__name__)

# Timeouts generosos de propósito: a ingestão roda uma vez por mês
# (.github/workflows/ingerir-setores.yml), então esperar minutos é barato,
# enquanto desistir cedo custa uma UF congelada até o mês seguinte. No run
# #29 (2026-08-23), 25 das 27 UFs morreram em `Read timed out` com
# timeout=30 e backoff de 1s/2s/4s -- sete segundos de espera total para um
# serviço brasileiro alcançado da rede do GitHub.
FEATURE_LAYER_URL = (
    "https://geoportal.sgb.gov.br/server/rest/services/"
    "gestaoterritorial/risco/FeatureServer/0/query"
)

PAGE_SIZE = 2000


class CPRMFetchError(RuntimeError):
    """Erro ao buscar dados da camada de risco da CPRM/SGB."""


def _query_pagina(
    where: str,
    offset: int,
    session: requests.Session,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
) -> dict:
    params = {
        "where": where,
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }

    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = session.get(FEATURE_LAYER_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            if "error" in payload:
                raise CPRMFetchError(f"API retornou erro: {payload['error']}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao buscar setores de risco (tentativa %d/%d): %s. "
                "Aguardando %.1fs antes de tentar novamente.",
                tentativa, max_retries, exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)

    raise CPRMFetchError(
        f"Não foi possível obter dados da CPRM/SGB após {max_retries} tentativas"
    ) from last_exc


def fetch_setores_risco(
    uf: str,
    timeout: float = 120.0,
    max_retries: int = 5,
    backoff_factor: float = 5.0,
    session: requests.Session | None = None,
    where_extra: str | None = None,
) -> gpd.GeoDataFrame:
    """Baixa os setores de risco geológico de uma UF via ArcGIS REST (GeoJSON).

    Pagina automaticamente usando resultOffset/resultRecordCount até esgotar
    os registros, seguindo exceededTransferLimit da resposta.

    `where_extra`, se informado, é combinado com `AND` ao filtro de UF (usado
    pela ingestão incremental para pedir só `objectid`/`data_setor` acima do
    marcador d'água salvo, ver `ingerir_uf`).
    """
    uf_norm = _validar_uf(uf)
    where = f"uf='{uf_norm}'"
    if where_extra:
        where = f"{where} AND ({where_extra})"
    sess = session or requests.Session()

    features: list[dict] = []
    offset = 0
    while True:
        payload = _query_pagina(where, offset, sess, timeout, max_retries, backoff_factor)
        pagina_features = payload.get("features", [])
        features.extend(pagina_features)

        exceeded = payload.get("properties", {}).get("exceededTransferLimit", False)
        if not exceeded or not pagina_features:
            break
        offset += len(pagina_features)

    if not features:
        logger.warning("Nenhum setor de risco encontrado para UF=%s (where_extra=%r)", uf_norm, where_extra)

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    return gdf


def _carregar_manifesto(caminho: Path) -> dict:
    if not caminho.exists():
        return {"last_objectid": None, "last_data_setor": None}
    try:
        return json.loads(caminho.read_text())
    except json.JSONDecodeError:
        logger.warning("Manifesto de marcador d'água corrompido em %s; tratando como inexistente.", caminho)
        return {"last_objectid": None, "last_data_setor": None}


def _salvar_manifesto(caminho: Path, manifesto: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False))


def _where_incremental(manifesto: dict) -> str | None:
    """Monta o filtro incremental a partir do marcador d'água salvo.

    Retorna `None` quando não há marcador (primeira ingestão da UF): nesse
    caso `fetch_setores_risco` busca a UF inteira, como hoje.
    """
    condicoes = []
    if manifesto.get("last_objectid") is not None:
        condicoes.append(f"objectid > {manifesto['last_objectid']}")
    if manifesto.get("last_data_setor"):
        condicoes.append(f"data_setor > TIMESTAMP '{manifesto['last_data_setor']} 00:00:00'")
    if not condicoes:
        return None
    return " OR ".join(condicoes)


def _mesclar_setores(existente: gpd.GeoDataFrame | None, novos: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Funde os setores recém-buscados com os já salvos, por `objectid`.

    Registros com o mesmo `objectid` são substituídos pela versão nova
    (edição/resurvey); os demais registros existentes são preservados.
    """
    if existente is None or existente.empty:
        return novos
    if novos.empty:
        return existente

    combinado = pd.concat([existente, novos], ignore_index=True)
    combinado = combinado.drop_duplicates(subset="objectid", keep="last")
    return gpd.GeoDataFrame(combinado, geometry="geometry", crs=existente.crs)


def _atualizar_marcador_dagua(manifesto: dict, setores: gpd.GeoDataFrame) -> dict:
    if setores.empty or "objectid" not in setores.columns:
        return manifesto
    novo = dict(manifesto)
    novo["last_objectid"] = int(setores["objectid"].max())
    if "data_setor" in setores.columns:
        datas = pd.to_datetime(setores["data_setor"], errors="coerce")
        if datas.notna().any():
            novo["last_data_setor"] = datas.max().strftime("%Y-%m-%d")
    return novo


def ingerir_uf(
    uf: str,
    output: Path,
    manifesto_path: Path | None = None,
    timeout: float = 120.0,
    max_retries: int = 5,
    backoff_factor: float = 5.0,
    permitir_cache: bool = True,
) -> gpd.GeoDataFrame:
    """Busca (incrementalmente) os setores de risco de uma UF e salva em GeoPackage.

    A partir da segunda execução, consulta só `objectid`/`data_setor` acima
    do marcador d'água salvo em `manifesto_path` (padrão:
    `caminho_manifesto_cprm(uf, output.parent)`), mescla com o GeoPackage
    existente e atualiza o marcador. Uma edição de atributo que não altera
    `data_setor` não é capturada por este filtro.

    Se a busca remota falhar e já existir um GeoPackage em cache local
    (`output`), usa o cache e avisa, em vez de quebrar a ingestão inteira.

    `permitir_cache=False` desliga esse fallback e relança o `CPRMFetchError`.
    O job mensal (`ingerir-setores`) extrai os GeoPackages de `dados-base`
    para o diretório de trabalho ANTES de ingerir, então `output` sempre
    existe a partir da 2a execução: com o fallback ligado, a SGB fora do ar
    viraria 27 quedas silenciosas e um run verde, com os setores congelados
    por mais um mês (o job mensal falha se qualquer UF falhar).
    O fallback continua ligado por padrão para o uso manual (`atualizar`),
    onde ficar com o dado do mês passado é melhor que ficar sem nada.
    """
    uf_norm = _validar_uf(uf)
    caminho_manifesto = manifesto_path or caminho_manifesto_cprm(uf_norm, output.parent)
    manifesto = _carregar_manifesto(caminho_manifesto)
    where_extra = _where_incremental(manifesto)

    existente = ler_setores(output) if output.exists() else None

    try:
        novos = fetch_setores_risco(
            uf, timeout=timeout, max_retries=max_retries,
            backoff_factor=backoff_factor, where_extra=where_extra,
        )
        gdf = _mesclar_setores(existente, novos)
        salvar_setores(gdf, output)
        _salvar_manifesto(caminho_manifesto, _atualizar_marcador_dagua(manifesto, novos))
        logger.info(
            "Salvos %d setores de risco de %s em %s (%d novos/atualizados)",
            len(gdf), uf, output, len(novos),
        )
        return gdf
    except CPRMFetchError:
        if permitir_cache and output.exists():
            logger.warning(
                "Fonte remota da CPRM/SGB indisponível; usando cache local em %s", output
            )
            return ler_setores(output)
        raise
