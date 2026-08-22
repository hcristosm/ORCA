"""Exportação dos dados do dashboard estático a partir do cruzamento.

O dashboard (`docs/dashboard/`) é um site estático em HTML/CSS/JS puro, sem
backend, este módulo pré-computa o que ele precisa como arquivos estáticos:
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
from src.processing.cruzamento import (
    CRS_METRICO,
    calcular_cruzamento,
    centroides_4326,
    centroides_municipio,
    chuva_acumulada,
)
from src.processing.previsao import (
    DIAS_PREVISAO_ALERTA,
    HORIZONTE_PREVISAO_HORAS,
    trajetoria_chuva_72h,
)
from src.storage import chuva_existe, ler_chuva, ler_setores
from src.storage_cache_openmeteo import CacheOpenMeteo

logger = logging.getLogger(__name__)

JANELA_SERIE_DIAS = 30

# A chuva acumulada por setor (mapa/tabela) só precisa de ~72h + folga; pedir
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

    Recortado aos últimos `JANELA_SERIE_DIAS` dias a partir de `referencia`,
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


def _distancias_km(
    centroides: gpd.GeoSeries, pontos: list[tuple[float, float]]
) -> list[float]:
    """Distância (km) entre cada centroide de setor e o ponto `(lat, lon)` consultado.

    Correspondência posicional (mesmo tamanho nas duas listas). Reprojeta os
    dois lados para `CRS_METRICO` e divide por 1000, mesma convenção de
    `src.processing.cruzamento.encontrar_estacao_mais_proxima`.
    """
    consultados = gpd.GeoSeries(
        [Point(lon, lat) for lat, lon in pontos], crs="EPSG:4326"
    ).to_crs(CRS_METRICO)
    origem = centroides.to_crs(CRS_METRICO)
    distancias_m = origem.reset_index(drop=True).distance(consultados.reset_index(drop=True))
    return [round(float(d) / 1000, 2) for d in distancias_m]


def _calcular_chuva_openmeteo(
    setores: gpd.GeoDataFrame,
    janelas: tuple[int, ...] = (24, 72),
    dias_historico: int = DIAS_HISTORICO_CRUZAMENTO,
    dias_previsao: int = DIAS_PREVISAO_ALERTA,
    agora: pd.Timestamp | None = None,
    pontos: list[tuple[float, float]] | None = None,
    cache: CacheOpenMeteo | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Consulta a Open-Meteo e calcula a chuva acumulada por setor.

    `pontos`, se informado, é usado no lugar do centroide de cada setor
    (uma tupla `(lat, lon)` por setor, mesma ordem) — é como a grade
    espacial nacional (`src/processing/grade_espacial.py`) injeta pontos
    compartilhados entre setores próximos. Pontos repetidos (mesma tupla)
    são deduplicados antes da chamada à Open-Meteo e a série resultante é
    reaproveitada por todos os setores que compartilham o ponto, o que é o
    mecanismo real de economia de chamadas da grade.

    Sem estação: `codigo_estacao`/`nome_estacao` identificam a fonte, não uma
    estação real. Sem `pontos` (consulta no próprio centroide do setor),
    `distancia_km` é 0.0 por construção. Com `pontos` (modo grade), o ponto
    consultado pode estar a quilômetros do centroide real do setor, então
    `distancia_km` traz a distância real centroide-do-setor → ponto de grade
    e `nome_estacao` deixa claro que a leitura veio de uma célula de grade.
    `agora` é parametrizável para tornar testes determinísticos, em produção
    usa o instante atual.

    Retorna `(resultado, previsao)`: `resultado` é o GeoDataFrame de sempre
    (chuva observada em `janelas`); `previsao` é
    `{num_setor: [[iso, mm], ...]}`, a trajetória do acumulado de 72h nas
    próximas horas (ver `src.processing.previsao.trajetoria_chuva_72h`), calculada a partir da
    mesma série já buscada, sem uma segunda consulta à API.
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")

    modo_grade = pontos is not None
    centroides = centroides_4326(setores)
    pontos = pontos if modo_grade else [(pt.y, pt.x) for pt in centroides]

    if len(pontos) != len(setores):
        raise ValueError(
            f"pontos tem {len(pontos)} itens, mas setores tem {len(setores)}; "
            "devem ter o mesmo tamanho."
        )

    pontos_unicos = list(dict.fromkeys(pontos))
    indice_por_ponto = {ponto: i for i, ponto in enumerate(pontos_unicos)}
    series_unicas = fetch_precipitacao_batch(
        pontos_unicos, dias_historico=dias_historico, dias_previsao=dias_previsao,
        cache=cache, agora=agora,
    )
    series = [series_unicas[indice_por_ponto[ponto]] for ponto in pontos]

    validas = pd.concat(
        [s[(s["data_hora"] <= agora) & s["chuva_mm"].notna()] for s in series],
        ignore_index=True,
    )
    referencia = validas["data_hora"].max() if not validas.empty else agora

    resultado = setores.copy()
    if modo_grade:
        resultado["distancia_km"] = _distancias_km(centroides, pontos)
        resultado["nome_estacao"] = "Open-Meteo (célula de grade)"
    else:
        resultado["distancia_km"] = 0.0
        resultado["nome_estacao"] = "Open-Meteo (centro do setor)"
    resultado["codigo_estacao"] = "openmeteo"
    resultado["fonte_estacao"] = "openmeteo"

    for horas in janelas:
        resultado[f"chuva_{horas}h"] = [
            chuva_acumulada(serie, referencia, horas) for serie in series
        ]

    previsao = {
        num_setor: trajetoria_chuva_72h(serie, referencia)
        for num_setor, serie in zip(setores["num_setor"], series)
    }

    resultado.attrs["referencia"] = referencia
    return resultado, previsao


def _series_openmeteo_por_municipio(
    setores: gpd.GeoDataFrame,
    dias_historico: int = JANELA_SERIE_DIAS,
    agora: pd.Timestamp | None = None,
    cache: CacheOpenMeteo | None = None,
) -> dict:
    """Um ponto por município (média dos centroides dos setores daquele município)."""
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")

    municipios, pontos = centroides_municipio(setores)
    series_brutas = fetch_precipitacao_batch(pontos, dias_historico=dias_historico, cache=cache, agora=agora)

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


def _exportar_openmeteo(
    setores: gpd.GeoDataFrame,
    pontos: list[tuple[float, float]] | None = None,
    cache: CacheOpenMeteo | None = None,
) -> tuple[pd.DataFrame, dict, dict, dict]:
    """Estratégia `fonte="openmeteo"`: consulta direto no centroide de cada setor
    (ou nos pontos de grade compartilhados, se `pontos` for informado).

    Retorna `(cruzado, series, previsao, meta)` prontos para gravação;
    `meta` já traz todos os campos específicos desta fonte, exceto
    `gerado_em` (adicionado por `exportar_dashboard`, comum às duas fontes).
    """
    try:
        cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), pontos=pontos, cache=cache)
        series = _series_openmeteo_por_municipio(setores, cache=cache)
    except OpenMeteoFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar a Open-Meteo: {exc}") from exc
    referencia = cruzado.attrs["referencia"]

    meta = {
        "fonte": "openmeteo",
        "referencia": referencia.isoformat(),
        "total_setores": int(len(cruzado)),
        "total_municipios": len(series),
        "horizonte_previsao_horas": HORIZONTE_PREVISAO_HORAS,
    }
    return cruzado, series, previsao, meta


def _exportar_inmet(
    setores: gpd.GeoDataFrame, uf_norm: str, ano: int, diretorio_dados: Path
) -> tuple[pd.DataFrame, dict, None, dict]:
    """Estratégia `fonte="inmet"`: cruzamento por estação mais próxima (INMET + ANA).

    Retorna `(cruzado, series, previsao, meta)`. `previsao` é sempre `None`
    (INMET não tem previsão), mantido na tupla só para simetria com
    `_exportar_openmeteo`.
    """
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
        "referencia": referencia.isoformat(),
        "total_setores": int(len(cruzado)),
        "total_estacoes_inmet": int(chuva_inmet["codigo_estacao"].nunique()),
        "total_estacoes_ana": int(chuva_ana["codigo_estacao"].nunique()) if chuva_ana is not None else 0,
    }
    return cruzado, series, None, meta


def exportar_dashboard(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    fonte: str = "openmeteo",
    pontos_grade: list[tuple[float, float]] | None = None,
    cache_openmeteo: CacheOpenMeteo | None = None,
) -> dict:
    """Pré-computa a chuva por setor e grava os arquivos estáticos do dashboard.

    `fonte="openmeteo"` (padrão): consulta a Open-Meteo direto no centroide
    de cada setor (sem estação, sem depender de INMET/ANA terem sido
    ingeridos), só precisa dos setores (CPRM). `fonte="inmet"`: comportamento
    idêntico ao anterior a este parâmetro, cruzamento por estação mais
    próxima combinando INMET e, se existir localmente, ANA.

    `pontos_grade`, se informado, substitui o centroide de cada setor pelo
    ponto de grade compartilhado (ver `src/processing/grade_espacial.py` e
    `src/export/nacional.py`); só é válido com `fonte="openmeteo"`.

    `cache_openmeteo`, se informado, é repassado para as buscas na Open-Meteo
    (só relevante com fonte="openmeteo"; ver src/storage_cache_openmeteo.py).

    Grava em `saida_dir`: `setores_<uf>.geojson`, `series_<uf>.json`
    (por estação com `fonte="inmet"`, por município com `fonte="openmeteo"`)
    e `meta_<uf>.json`. Retorna o conteúdo de `meta_<uf>.json`.
    """
    if fonte not in ("openmeteo", "inmet"):
        raise ValueError(f"fonte inválida: {fonte!r}. Use 'openmeteo' ou 'inmet'.")
    if pontos_grade is not None and fonte != "openmeteo":
        raise ValueError("pontos_grade só é válido com fonte='openmeteo'.")

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
        cruzado, series, previsao, meta = _exportar_openmeteo(setores, pontos=pontos_grade, cache=cache_openmeteo)
    else:
        cruzado, series, previsao, meta = _exportar_inmet(setores, uf_norm, ano, diretorio_dados)
    meta["gerado_em"] = datetime.now(timezone.utc).isoformat()

    _exportar_setores(cruzado, saida_dir / f"setores_{uf_norm.lower()}.geojson")
    (saida_dir / f"series_{uf_norm.lower()}.json").write_text(
        json.dumps(series, ensure_ascii=False, indent=2)
    )
    if previsao is not None:
        (saida_dir / f"previsao_{uf_norm.lower()}.json").write_text(
            json.dumps(previsao, ensure_ascii=False, separators=(",", ":"))
        )
    caminho_meta = saida_dir / f"meta_{uf_norm.lower()}.json"
    meta_existente = json.loads(caminho_meta.read_text()) if caminho_meta.exists() else {}
    meta_existente.update(meta)
    caminho_meta.write_text(json.dumps(meta_existente, ensure_ascii=False, indent=2))

    logger.info("Exportados dados do dashboard (fonte=%s) para %s: %s", fonte, uf_norm, meta)
    return meta
