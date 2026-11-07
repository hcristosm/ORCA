"""Índice nacional leve de setores (`setores_pontos.json`) para "Perto de mim".

A tela do celular precisa achar os setores perto do aparelho sem baixar os
`setores_<uf>.geojson` (49 MB somados; SC sozinho tem 10 MB). Este índice
guarda só o essencial de cada setor: identificação, grau, centroide, caixa
delimitadora e a chuva publicada.

Roda DEPOIS da mescla com o gh-pages (`scripts/mesclar_publicado.py`), a
partir do que está em `docs/dashboard/data/`: assim cobre também as UFs
preservadas da véspera. Gerado dentro de `exportar_nacional`, ficaria parcial
em dia de falha, e a mescla não o copiaria.

Nada aqui pode derrubar a publicação: GeoJSON ilegível pula a UF, feição sem
geometria pula a feição, e sem `ufs_disponiveis.json` não grava nada. O front
trata índice ausente.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.errors import GEOSException
from shapely.geometry import shape

from src.config import caminho_indice_setores

logger = logging.getLogger(__name__)

VERSAO_INDICE = 1
CASAS_DECIMAIS = 5
CAMPOS = [
    "num_setor", "uf", "munic", "grau_risco", "lat", "lon",
    "oeste", "sul", "leste", "norte", "chuva_24h", "chuva_72h",
]


def _ler_ufs_disponiveis(dados_dir: Path) -> list[str] | None:
    caminho = dados_dir / "ufs_disponiveis.json"
    try:
        ufs = json.loads(caminho.read_text())
    except (OSError, ValueError):
        logger.warning("Sem %s legível; índice de setores não gerado.", caminho)
        return None
    if not isinstance(ufs, list) or not all(isinstance(u, str) for u in ufs):
        logger.warning("%s não é uma lista de UFs; índice de setores não gerado.", caminho)
        return None
    return [u.lower() for u in ufs]


def _referencia(dados_dir: Path, uf: str) -> str | None:
    try:
        meta = json.loads((dados_dir / f"meta_{uf}.json").read_text())
    except (OSError, ValueError):
        return None
    referencia = meta.get("referencia") if isinstance(meta, dict) else None
    return referencia if isinstance(referencia, str) else None


def _registro(uf: str, feicao: dict[str, Any]) -> list[Any] | None:
    props = feicao.get("properties") or {}
    geometria = feicao.get("geometry")
    if not geometria:
        logger.warning("Setor %s (%s) sem geometria; fora do índice.", props.get("num_setor"), uf)
        return None
    try:
        forma = shape(geometria)
        centro = forma.centroid
        oeste, sul, leste, norte = forma.bounds
    except (GEOSException, ValueError, TypeError, AttributeError, KeyError, IndexError):
        logger.warning("Setor %s (%s) com geometria ilegível; fora do índice.", props.get("num_setor"), uf)
        return None
    if forma.is_empty:
        logger.warning("Setor %s (%s) com geometria vazia; fora do índice.", props.get("num_setor"), uf)
        return None

    def r(v: float) -> float:
        return round(float(v), CASAS_DECIMAIS)

    return [
        props.get("num_setor"), uf, props.get("munic"), props.get("grau_risco"),
        r(centro.y), r(centro.x), r(oeste), r(sul), r(leste), r(norte),
        props.get("chuva_24h"), props.get("chuva_72h"),
    ]


def gerar_indice_setores(dados_dir: Path) -> int | None:
    """Grava `setores_pontos.json` em `dados_dir` e devolve quantos setores entraram.

    Devolve `None` (sem gravar) quando `ufs_disponiveis.json` falta, é
    inválido ou lista zero UFs.
    """
    ufs = _ler_ufs_disponiveis(dados_dir)
    if not ufs:
        return None

    setores: list[list[Any]] = []
    referencia_por_uf: dict[str, str] = {}
    for uf in ufs:
        caminho = dados_dir / f"setores_{uf}.geojson"
        try:
            colecao = json.loads(caminho.read_text())
            feicoes = colecao["features"]
        except Exception:
            # Uma UF ilegível não pode tirar as outras do índice.
            logger.exception("Setores de %s ilegíveis em %s; UF fora do índice.", uf, caminho)
            continue
        for feicao in feicoes:
            registro = _registro(uf, feicao)
            if registro is not None:
                setores.append(registro)
        referencia = _referencia(dados_dir, uf)
        if referencia:
            referencia_por_uf[uf] = referencia

    indice = {
        "versao": VERSAO_INDICE,
        "gerado_em": datetime.now(UTC).isoformat(),
        "referencia_por_uf": referencia_por_uf,
        "campos": CAMPOS,
        "setores": setores,
    }
    destino = caminho_indice_setores(dados_dir)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_text(json.dumps(indice, ensure_ascii=False, separators=(",", ":")))
    os.replace(temporario, destino)
    return len(setores)
