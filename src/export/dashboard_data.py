"""Exportação dos dados do dashboard estático a partir do cruzamento.

O dashboard (`docs/dashboard/`) é um site estático em HTML/CSS/JS puro, sem
backend — este módulo pré-computa o que ele precisa como arquivos estáticos:
setores com a estação mais próxima (INMET+ANA combinados, via
`calcular_cruzamento`) e chuva acumulada em GeoJSON, série temporal recente
por estação em JSON, e metadados de geração. Ver
docs/superpowers/specs/2026-08-09-dashboard-estatico-design.md.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.config import caminho_chuva, caminho_chuva_ana, caminho_setores
from src.processing.cruzamento import calcular_cruzamento
from src.storage import chuva_existe, ler_chuva, ler_setores

logger = logging.getLogger(__name__)

JANELA_SERIE_DIAS = 30

PROPRIEDADES_SETOR = [
    "num_setor", "munic", "grau_risco", "distancia_km",
    "chuva_24h", "chuva_72h", "fonte_estacao", "codigo_estacao", "nome_estacao",
]


class ExportacaoDashboardError(RuntimeError):
    """Erro ao exportar os dados do dashboard estático."""


def _exportar_setores(cruzado: pd.DataFrame, caminho: Path) -> None:
    colunas = [c for c in PROPRIEDADES_SETOR if c in cruzado.columns] + ["geometry"]
    reduzido = cruzado[colunas].copy()
    for coluna in ("chuva_24h", "chuva_72h", "distancia_km"):
        if coluna in reduzido.columns:
            reduzido[coluna] = reduzido[coluna].round(2)
    if caminho.exists():
        caminho.unlink()
    reduzido.to_file(caminho, driver="GeoJSON")


def _recortar_series(chuva_df: pd.DataFrame, referencia: pd.Timestamp) -> dict:
    """Monta `{codigo_estacao: {nome, fonte, serie: [[iso, mm], ...]}}`.

    Recortado aos últimos `JANELA_SERIE_DIAS` dias a partir de `referencia` —
    sem isso o payload cresceria sem limite agora que o INMET acumula o ano
    inteiro (ingestão incremental, ver src/ingest/inmet.py).
    """
    limite = referencia - timedelta(days=JANELA_SERIE_DIAS)
    recente = chuva_df[chuva_df["data_hora"] >= limite]

    series = {}
    for codigo, grupo in recente.groupby("codigo_estacao"):
        grupo_ordenado = grupo.sort_values("data_hora")
        series[str(codigo)] = {
            "nome": grupo_ordenado["nome_estacao"].iloc[0],
            "fonte": grupo_ordenado["fonte"].iloc[0],
            "serie": [
                [ts.isoformat(), (None if pd.isna(mm) else round(float(mm), 2))]
                for ts, mm in zip(grupo_ordenado["data_hora"], grupo_ordenado["chuva_mm"])
            ],
        }
    return series


def exportar_dashboard(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
) -> dict:
    """Pré-computa o cruzamento e grava os arquivos estáticos do dashboard.

    Grava em `saida_dir`: `setores_<uf>.geojson` (setores com a estação mais
    próxima combinada INMET+ANA e chuva 24h/72h), `series_<uf>.json` (série
    temporal por estação, recortada aos últimos 30 dias) e `meta_<uf>.json`
    (timestamp de geração, referência de chuva, contagens). Retorna o
    conteúdo de `meta_<uf>.json`.
    """
    uf_norm = uf.strip().upper()

    caminho_setores_path = caminho_setores(uf_norm, diretorio_dados)
    caminho_chuva_path = caminho_chuva(uf_norm, ano, diretorio_dados)
    if not caminho_setores_path.exists():
        raise ExportacaoDashboardError(
            f"Setores de risco não encontrados em {caminho_setores_path}; "
            f"rode `ingest-cprm --uf {uf_norm}` primeiro."
        )
    if not caminho_chuva_path.exists():
        raise ExportacaoDashboardError(
            f"Chuva do INMET não encontrada em {caminho_chuva_path}; "
            f"rode `ingest-inmet --uf {uf_norm} --ano {ano}` primeiro."
        )

    setores = ler_setores(caminho_setores_path)
    chuva_inmet = ler_chuva(caminho_chuva_path)

    caminho_ana = caminho_chuva_ana(uf_norm, diretorio_dados)
    chuva_ana = ler_chuva(caminho_ana) if chuva_existe(caminho_ana) else None

    cruzado = calcular_cruzamento(setores, chuva_inmet, chuva_ana=chuva_ana, janelas=(24, 72))
    referencia = cruzado.attrs["referencia"]

    saida_dir.mkdir(parents=True, exist_ok=True)
    _exportar_setores(cruzado, saida_dir / f"setores_{uf_norm.lower()}.geojson")

    chuva_combinada_partes = [chuva_inmet.assign(fonte="inmet")]
    if chuva_ana is not None and not chuva_ana.empty:
        chuva_combinada_partes.append(chuva_ana.assign(fonte="ana"))
    chuva_combinada = pd.concat(chuva_combinada_partes, ignore_index=True)

    series = _recortar_series(chuva_combinada, referencia)
    (saida_dir / f"series_{uf_norm.lower()}.json").write_text(
        json.dumps(series, ensure_ascii=False, indent=2)
    )

    meta = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "referencia": referencia.isoformat(),
        "total_setores": int(len(cruzado)),
        "total_estacoes_inmet": int(chuva_inmet["codigo_estacao"].nunique()),
        "total_estacoes_ana": int(chuva_ana["codigo_estacao"].nunique()) if chuva_ana is not None else 0,
    }
    (saida_dir / f"meta_{uf_norm.lower()}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )

    logger.info(
        "Exportados dados do dashboard para %s: %d setores, %d estações INMET, %d estações ANA em %s",
        uf_norm, meta["total_setores"], meta["total_estacoes_inmet"], meta["total_estacoes_ana"], saida_dir,
    )
    return meta
