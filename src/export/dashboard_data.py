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

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config import caminho_chuva, caminho_chuva_ana, caminho_setores
from src.ingest.openmeteo import OpenMeteoFetchError, fetch_precipitacao_batch
from src.processing.cruzamento import CRS_METRICO, _chuva_acumulada, calcular_cruzamento
from src.storage import chuva_existe, ler_chuva, ler_setores

logger = logging.getLogger(__name__)

JANELA_SERIE_DIAS = 30

# A chuva acumulada por setor (mapa/tabela) só precisa de ~72h + folga — pedir
# 30 dias de histórico para todos os ~900 setores de uma vez esbarrou em
# HTTP 429 (rate limit) na Open-Meteo em testes reais (ver
# src/ingest/openmeteo.py). O gráfico por município (bem menos pontos) ainda
# usa JANELA_SERIE_DIAS.
DIAS_HISTORICO_CRUZAMENTO = 4

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


def _calcular_chuva_openmeteo(
    setores: gpd.GeoDataFrame,
    janelas: tuple[int, ...] = (24, 72),
    dias_historico: int = DIAS_HISTORICO_CRUZAMENTO,
    agora: pd.Timestamp | None = None,
) -> gpd.GeoDataFrame:
    """Consulta a Open-Meteo direto no centroide de cada setor e calcula a chuva acumulada.

    Sem estação: `distancia_km` é sempre 0.0; `codigo_estacao`/`nome_estacao`
    identificam a fonte, não uma estação real. `agora` é parametrizável para
    tornar testes determinísticos — em produção usa o instante atual.
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")

    centroides_4326 = setores.to_crs(CRS_METRICO).geometry.centroid.to_crs("EPSG:4326")
    pontos = [(pt.y, pt.x) for pt in centroides_4326]

    series = fetch_precipitacao_batch(pontos, dias_historico=dias_historico)

    validas = pd.concat(
        [s[(s["data_hora"] <= agora) & s["chuva_mm"].notna()] for s in series],
        ignore_index=True,
    )
    referencia = validas["data_hora"].max() if not validas.empty else agora

    resultado = setores.copy()
    resultado["distancia_km"] = 0.0
    resultado["codigo_estacao"] = "openmeteo"
    resultado["nome_estacao"] = "Open-Meteo (centro do setor)"
    resultado["fonte_estacao"] = "openmeteo"

    for horas in janelas:
        resultado[f"chuva_{horas}h"] = [
            _chuva_acumulada(serie, referencia, horas) for serie in series
        ]

    resultado.attrs["referencia"] = referencia
    return resultado


def _series_openmeteo_por_municipio(
    setores: gpd.GeoDataFrame,
    dias_historico: int = JANELA_SERIE_DIAS,
    agora: pd.Timestamp | None = None,
) -> dict:
    """Um ponto por município (média dos centroides dos setores daquele município)."""
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")

    centroides = setores.to_crs(CRS_METRICO).geometry.centroid
    df_centroides = pd.DataFrame({
        "munic": setores["munic"].values,
        "x": centroides.x.values,
        "y": centroides.y.values,
    })
    medios = df_centroides.groupby("munic")[["x", "y"]].mean()
    municipios = list(medios.index)

    pontos_metricos = gpd.GeoSeries(
        [Point(linha.x, linha.y) for linha in medios.itertuples()], crs=CRS_METRICO
    )
    pontos_4326 = pontos_metricos.to_crs("EPSG:4326")
    pontos = [(pt.y, pt.x) for pt in pontos_4326]

    series_brutas = fetch_precipitacao_batch(pontos, dias_historico=dias_historico)

    limite = agora - timedelta(days=JANELA_SERIE_DIAS)
    series = {}
    for municipio, serie in zip(municipios, series_brutas):
        recente = serie[(serie["data_hora"] >= limite) & (serie["data_hora"] <= agora)]
        series[municipio] = {
            "nome": municipio,
            "fonte": "openmeteo",
            "serie": [
                [ts.isoformat(), (None if pd.isna(mm) else round(float(mm), 2))]
                for ts, mm in zip(recente["data_hora"], recente["chuva_mm"])
            ],
        }
    return series


def exportar_dashboard(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    fonte: str = "openmeteo",
) -> dict:
    """Pré-computa a chuva por setor e grava os arquivos estáticos do dashboard.

    `fonte="openmeteo"` (padrão): consulta a Open-Meteo direto no centroide
    de cada setor (sem estação, sem depender de INMET/ANA terem sido
    ingeridos) — só precisa dos setores (CPRM). `fonte="inmet"`: comportamento
    idêntico ao anterior a este parâmetro — cruzamento por estação mais
    próxima combinando INMET e, se existir localmente, ANA.

    Grava em `saida_dir`: `setores_<uf>.geojson`, `series_<uf>.json`
    (por estação com `fonte="inmet"`, por município com `fonte="openmeteo"`)
    e `meta_<uf>.json`. Retorna o conteúdo de `meta_<uf>.json`.
    """
    if fonte not in ("openmeteo", "inmet"):
        raise ValueError(f"fonte inválida: {fonte!r}. Use 'openmeteo' ou 'inmet'.")

    uf_norm = uf.strip().upper()
    caminho_setores_path = caminho_setores(uf_norm, diretorio_dados)
    if not caminho_setores_path.exists():
        raise ExportacaoDashboardError(
            f"Setores de risco não encontrados em {caminho_setores_path}; "
            f"rode `ingest-cprm --uf {uf_norm}` primeiro."
        )
    setores = ler_setores(caminho_setores_path)
    saida_dir.mkdir(parents=True, exist_ok=True)

    if fonte == "openmeteo":
        try:
            cruzado = _calcular_chuva_openmeteo(setores, janelas=(24, 72))
            series = _series_openmeteo_por_municipio(setores)
        except OpenMeteoFetchError as exc:
            raise ExportacaoDashboardError(f"Falha ao consultar a Open-Meteo: {exc}") from exc
        referencia = cruzado.attrs["referencia"]

        meta = {
            "fonte": "openmeteo",
            "gerado_em": datetime.now(timezone.utc).isoformat(),
            "referencia": referencia.isoformat(),
            "total_setores": int(len(cruzado)),
            "total_municipios": len(series),
        }
    else:
        caminho_chuva_path = caminho_chuva(uf_norm, ano, diretorio_dados)
        if not caminho_chuva_path.exists():
            raise ExportacaoDashboardError(
                f"Chuva do INMET não encontrada em {caminho_chuva_path}; "
                f"rode `ingest-inmet --uf {uf_norm} --ano {ano}` primeiro."
            )
        chuva_inmet = ler_chuva(caminho_chuva_path)
        caminho_ana = caminho_chuva_ana(uf_norm, diretorio_dados)
        chuva_ana = ler_chuva(caminho_ana) if chuva_existe(caminho_ana) else None

        cruzado = calcular_cruzamento(setores, chuva_inmet, chuva_ana=chuva_ana, janelas=(24, 72))
        referencia = cruzado.attrs["referencia"]

        chuva_combinada_partes = [chuva_inmet.assign(fonte="inmet")]
        if chuva_ana is not None and not chuva_ana.empty:
            chuva_combinada_partes.append(chuva_ana.assign(fonte="ana"))
        chuva_combinada = pd.concat(chuva_combinada_partes, ignore_index=True)
        series = _recortar_series(chuva_combinada, referencia)

        meta = {
            "fonte": "inmet",
            "gerado_em": datetime.now(timezone.utc).isoformat(),
            "referencia": referencia.isoformat(),
            "total_setores": int(len(cruzado)),
            "total_estacoes_inmet": int(chuva_inmet["codigo_estacao"].nunique()),
            "total_estacoes_ana": int(chuva_ana["codigo_estacao"].nunique()) if chuva_ana is not None else 0,
        }

    _exportar_setores(cruzado, saida_dir / f"setores_{uf_norm.lower()}.geojson")
    (saida_dir / f"series_{uf_norm.lower()}.json").write_text(
        json.dumps(series, ensure_ascii=False, indent=2)
    )
    (saida_dir / f"meta_{uf_norm.lower()}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )

    logger.info("Exportados dados do dashboard (fonte=%s) para %s: %s", fonte, uf_norm, meta)
    return meta
