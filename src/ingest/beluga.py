"""Leitura dos setores de risco publicados pelo BELUGA (contrato v1).

Substitui a ingestão direta da CPRM/SGB: o BELUGA coleta, normaliza e valida
a setorização federal junto com as fontes estaduais e municipais, e publica um
GeoJSON por UF com um `manifest.json` que carrega o sha256 e a contagem de
setores de cada arquivo. O contrato está em
https://github.com/hcristosm/BELUGA/blob/main/docs/contrato-dados.md

Toda falha aqui é alta e a UF afetada fica com o dado anterior: o GeoPackage só
é gravado depois que o arquivo recebido passa pelas quatro conferências
(contrato, sha256, contagem de feições e piso contra o publicado). Publicação
que encolhe é recusada, não aceita em silêncio.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

import geopandas as gpd
import requests

from src.config import (
    caminho_manifesto_beluga,
    caminho_setores_beluga,
    validar_uf,
)
from src.storage import salvar_setores

logger = logging.getLogger(__name__)

URL_BASE = "https://hcristosm.github.io/BELUGA/v1/"

CONTRATO_ESPERADO = "v1"

# O BELUGA publica as 27 UFs em todo run, mesmo as sem setor nenhum. Um
# manifest com menos é publicação parcial do lado de lá, e aí a conferência
# por UF abaixo não teria contra o que comparar as que faltam.
TOTAL_UFS_ESPERADO = 27

TIMEOUT_PADRAO = 120.0


class BelugaFetchError(RuntimeError):
    """Erro ao ler a publicação v1 do BELUGA."""


def _baixar(url: str, session: requests.Session, timeout: float) -> bytes:
    try:
        resposta = session.get(url, timeout=timeout)
        resposta.raise_for_status()
    except requests.RequestException as exc:
        raise BelugaFetchError(f"Falha ao baixar {url}: {exc}") from exc
    return resposta.content


def baixar_manifest(
    session: requests.Session | None = None, timeout: float = TIMEOUT_PADRAO
) -> dict:
    """Baixa e valida o `manifest.json` da publicação v1.

    Recusa contrato diferente de `v1` (mudança incompatível sai em `/v2/`, e
    ler v2 como se fosse v1 é o jeito de importar dado com outro significado) e
    recusa manifest que não traga as 27 UFs.
    """
    bruto = _baixar(f"{URL_BASE}manifest.json", session or requests.Session(), timeout)
    try:
        manifest = json.loads(bruto)
    except ValueError as exc:
        raise BelugaFetchError("manifest.json do BELUGA não é JSON válido") from exc
    if not isinstance(manifest, dict):
        raise BelugaFetchError("manifest.json do BELUGA não é um objeto JSON")

    contrato = manifest.get("contrato")
    if contrato != CONTRATO_ESPERADO:
        raise BelugaFetchError(
            f"Contrato do BELUGA é {contrato!r}, e este código lê "
            f"{CONTRATO_ESPERADO!r}. Nada foi baixado."
        )

    ufs = manifest.get("ufs")
    if not isinstance(ufs, dict) or len(ufs) != TOTAL_UFS_ESPERADO:
        total = len(ufs) if isinstance(ufs, dict) else "nenhuma"
        raise BelugaFetchError(
            f"manifest.json do BELUGA lista {total} UF(s), e o contrato promete "
            f"{TOTAL_UFS_ESPERADO}. Publicação parcial do BELUGA; nada foi baixado."
        )
    return manifest


def contagens_publicadas(dados_dir: Path) -> dict[str, int]:
    """`total_setores` de cada `meta_<uf>.json` já publicado, por UF.

    É o piso da guarda por UF. UF cujo meta não existe ou está ilegível fica
    sem piso (e avisa): uma UF não medível não pode travar as outras 26, e a
    guarda de contagem de UFs em `scripts/conferir_publicacao.py` e o piso de
    cobertura em `scripts/mesclar_publicado.py` continuam valendo para o
    conjunto.
    """
    contagens: dict[str, int] = {}
    if not dados_dir.is_dir():
        logger.warning("Sem %s; download do BELUGA sem piso por UF.", dados_dir)
        return contagens
    for caminho in sorted(dados_dir.glob("meta_*.json")):
        uf = caminho.stem.removeprefix("meta_").upper()
        try:
            meta = json.loads(caminho.read_text())
            total = meta["total_setores"]
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("%s ilegível; %s fica sem piso por UF.", caminho, uf)
            continue
        if isinstance(total, int) and not isinstance(total, bool):
            contagens[uf] = total
    return contagens


def baixar_uf(
    uf: str,
    manifest: Mapping,
    diretorio: Path,
    minimo: int | None = None,
    session: requests.Session | None = None,
    timeout: float = TIMEOUT_PADRAO,
) -> int:
    """Baixa o GeoJSON de uma UF, confere e grava `beluga_<uf>.gpkg`.

    Devolve quantos setores foram gravados. Levanta `BelugaFetchError` sem
    tocar no GeoPackage existente quando a UF não está no manifest, quando o
    sha256 do arquivo recebido não bate, quando o número de feições difere do
    declarado (GeoJSON truncado) ou quando a UF viria com menos setores que
    `minimo` (a publicação anterior do ORCA).
    """
    uf_norm = validar_uf(uf)
    chave = uf_norm.lower()
    entrada = manifest.get("ufs", {}).get(chave)
    if not isinstance(entrada, dict):
        raise BelugaFetchError(
            f"UF {chave} não está no manifest do BELUGA; {uf_norm} fica com o dado anterior."
        )

    arquivo = entrada.get("arquivo") or f"setores_{chave}.geojson"
    bruto = _baixar(f"{URL_BASE}{arquivo}", session or requests.Session(), timeout)

    sha_recebido = hashlib.sha256(bruto).hexdigest()
    sha_esperado = entrada.get("sha256")
    if sha_recebido != sha_esperado:
        raise BelugaFetchError(
            f"sha256 de {arquivo} não bate com o manifest "
            f"(recebido {sha_recebido}, esperado {sha_esperado}); arquivo descartado "
            f"e {uf_norm} fica com o dado anterior."
        )

    try:
        colecao = json.loads(bruto)
        feicoes = colecao["features"]
        if not isinstance(feicoes, list):
            raise TypeError("features não é uma lista")
    except (ValueError, KeyError, TypeError) as exc:
        raise BelugaFetchError(
            f"{arquivo} não é um GeoJSON legível ({exc}); {uf_norm} fica com o dado anterior."
        ) from exc

    declarado = entrada.get("setores")
    if len(feicoes) != declarado:
        raise BelugaFetchError(
            f"{arquivo} traz {len(feicoes)} feição(ões) e o manifest declara {declarado}: "
            f"GeoJSON truncado ou manifest desatualizado; {uf_norm} fica com o dado anterior."
        )

    if minimo is not None and len(feicoes) < minimo:
        raise BelugaFetchError(
            f"{uf_norm} viria com {len(feicoes)} setores, menos que os {minimo} já "
            "publicados pelo ORCA; publicação que encolhe é recusada e a UF fica com "
            "o dado anterior."
        )

    gdf = gpd.GeoDataFrame.from_features(feicoes, crs="EPSG:4326")
    destino = caminho_setores_beluga(uf_norm, diretorio)
    salvar_setores(gdf, destino)
    logger.info("%s: %d setores do BELUGA gravados em %s", uf_norm, len(gdf), destino)
    return len(gdf)


def baixar_setores(
    ufs: Sequence[str],
    diretorio: Path,
    anteriores: Mapping[str, int] | None = None,
    timeout: float = TIMEOUT_PADRAO,
) -> tuple[dict[str, int], dict[str, str]]:
    """Baixa os setores das UFs pedidas e devolve `({uf: setores}, {uf: motivo})`.

    O manifest é baixado uma vez e salvo em `caminho_manifesto_beluga`: é dele
    que o selo de atualização do dashboard tira a data da coleta e a lista de
    fontes de cada UF. Falha no manifest aborta tudo (`BelugaFetchError`) sem
    tocar em arquivo nenhum; falha de uma UF deixa aquela UF com o dado
    anterior e continua com as demais, e quem chama reprova o run mostrando o
    motivo de cada uma (o motivo é o que diz se foi sha256, truncamento ou
    piso; sem ele o operador fica só com "falhou").
    """
    sessao = requests.Session()
    manifest = baixar_manifest(sessao, timeout)
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho_manifesto_beluga(diretorio).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )

    piso = anteriores or {}
    baixadas: dict[str, int] = {}
    falhas: dict[str, str] = {}
    for uf in ufs:
        uf_norm = uf.strip().upper()
        try:
            baixadas[uf_norm] = baixar_uf(
                uf_norm, manifest, diretorio,
                minimo=piso.get(uf_norm), session=sessao, timeout=timeout,
            )
        except (BelugaFetchError, ValueError) as exc:
            logger.error("Falha no BELUGA (%s): %s", uf_norm, exc)
            falhas[uf_norm] = str(exc)
    return baixadas, falhas
