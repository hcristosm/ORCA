"""Exportação dos dados do dashboard estático a partir do cruzamento.

O dashboard (`docs/dashboard/`) é um site estático em HTML/CSS/JS puro, sem
backend, este módulo pré-computa o que ele precisa como arquivos estáticos:
setores com a chuva acumulada da Open-Meteo em GeoJSON, série temporal
recente por município em JSON, previsão de 72h e metadados de geração.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config import (
    LIMIAR_ATENCAO_MM_PADRAO,
    caminho_manifesto_beluga,
    caminho_setores_beluga,
)
from src.ingest.openmeteo import OpenMeteoFetchError, fetch_precipitacao_batch
from src.processing.cruzamento import (
    CRS_METRICO,
    centroides_4326,
    centroides_municipio,
    chuva_acumulada,
)
from src.processing.previsao import (
    DIAS_PREVISAO_ALERTA,
    HORIZONTE_PREVISAO_HORAS,
    trajetoria_chuva_72h,
)
from src.storage import ler_setores
from src.storage_cache_openmeteo import CacheOpenMeteo

logger = logging.getLogger(__name__)

JANELA_SERIE_DIAS = 30

# A chuva acumulada por setor (mapa/tabela) só precisa de ~72h + folga; pedir
# 30 dias de histórico para todos os ~900 setores de uma vez esbarrou em
# HTTP 429 (rate limit) na Open-Meteo em testes reais (ver
# src/ingest/openmeteo.py). O gráfico por município (bem menos pontos) ainda
# usa JANELA_SERIE_DIAS.
DIAS_HISTORICO_CRUZAMENTO = 4

# Contrato com o front-end: estes nomes, nesta ordem. Os `bl_*` e o
# `orgao_exec` vêm do GeoPackage do BELUGA (docs/esquema-setores.md dele) e são
# o que deixa o dashboard dizer de onde veio cada setor, com qual licença, e
# se ele repete área já mapeada pela CPRM (`bl_cp_frac`, ver
# LIMIAR_SETOR_REPETIDO em src/config.py).
PROPRIEDADES_SETOR = [
    "num_setor", "munic", "grau_risco",
    "chuva_24h", "chuva_72h", "distancia_km", "fonte_estacao", "codigo_estacao",
    "bl_fonte", "bl_produto", "bl_licenca", "orgao_exec", "bl_sob_cp", "bl_cp_frac",
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


def _pontos_serie(data_hora: pd.Series, chuva_mm: pd.Series) -> list[list]:
    """Série de chuva como `[[iso, mm], ...]`, com `NaN` virando `None` (JSON `null`)."""
    return [
        [ts.isoformat(), (None if pd.isna(mm) else round(float(mm), 2))]
        for ts, mm in zip(data_hora, chuva_mm)
    ]


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

    Sem estação: `codigo_estacao` identifica a fonte, não uma estação real.
    Sem `pontos` (consulta no próprio centroide do setor), `distancia_km` é
    0.0 por construção. Com `pontos` (modo grade), o ponto consultado pode
    estar a quilômetros do centroide real do setor, e `distancia_km` traz a
    distância real centroide-do-setor → ponto de grade.
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
    pontos = pontos if pontos is not None else [(pt.y, pt.x) for pt in centroides]

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
    else:
        resultado["distancia_km"] = 0.0
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


def _municipios_com_chuva_relevante(
    setores: gpd.GeoDataFrame, previsao: dict, limiar_mm: float = LIMIAR_ATENCAO_MM_PADRAO,
) -> set[str]:
    """Municípios com ao menos um setor cuja trajetória de 72h prevista
    (`previsao`, ver `_calcular_chuva_openmeteo`) ultrapassa `limiar_mm` em
    algum ponto futuro -- usado por `_series_openmeteo_por_municipio` para
    decidir quem pede JANELA_SERIE_DIAS completos vs. DIAS_HISTORICO_CRUZAMENTO.
    """
    relevantes: set[str] = set()
    for num_setor, munic in zip(setores["num_setor"], setores["munic"]):
        trajetoria = previsao.get(num_setor, [])
        valores = [mm for _, mm in trajetoria if mm is not None]
        if valores and max(valores) >= limiar_mm:
            relevantes.add(munic)
    return relevantes


def _series_openmeteo_por_municipio(
    setores: gpd.GeoDataFrame,
    municipios_dias_completos: set[str] | None = None,
    agora: pd.Timestamp | None = None,
    cache: CacheOpenMeteo | None = None,
) -> dict:
    """Um ponto por município (média dos centroides dos setores daquele município).

    `municipios_dias_completos`, se informado, restringe quais municípios
    pedem `JANELA_SERIE_DIAS` (30) dias de histórico; os demais pedem só
    `DIAS_HISTORICO_CRUZAMENTO` (4).
    `None` (padrão) mantém o comportamento anterior: todos pedem 30 dias.
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    municipios, pontos = centroides_municipio(setores)

    # `None` = todos os municípios pedem a série completa.
    completos = set(municipios) if municipios_dias_completos is None else municipios_dias_completos
    idx_completos = [i for i, m in enumerate(municipios) if m in completos]
    idx_reduzidos = [i for i, m in enumerate(municipios) if m not in completos]

    grupos = [
        ([municipios[i] for i in indices], [pontos[i] for i in indices], dias)
        for indices, dias in (
            (idx_completos, JANELA_SERIE_DIAS),
            (idx_reduzidos, DIAS_HISTORICO_CRUZAMENTO),
        )
        if indices
    ]

    limite = agora - timedelta(days=JANELA_SERIE_DIAS)
    series = {}
    for municipios_grupo, pontos_grupo, dias_historico_grupo in grupos:
        series_brutas = fetch_precipitacao_batch(
            pontos_grupo, dias_historico=dias_historico_grupo, cache=cache, agora=agora,
        )
        for municipio, serie in zip(municipios_grupo, series_brutas):
            recente = serie[(serie["data_hora"] >= limite) & (serie["data_hora"] <= agora)]
            series[municipio] = {
                "nome": municipio,
                "fonte": "openmeteo",
                "serie": _pontos_serie(recente["data_hora"], recente["chuva_mm"]),
            }
    return series


def _exportar_openmeteo(
    setores: gpd.GeoDataFrame,
    pontos: list[tuple[float, float]] | None = None,
    cache: CacheOpenMeteo | None = None,
) -> tuple[pd.DataFrame, dict, dict, dict]:
    """Consulta a Open-Meteo direto no centroide de cada setor (ou nos
    pontos de grade compartilhados, se `pontos` for informado).

    Retorna `(cruzado, series, previsao, meta)` prontos para gravação;
    `meta` já traz todos os campos da exportação, exceto `gerado_em`
    (adicionado por `exportar_dashboard`).
    """
    try:
        cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), pontos=pontos, cache=cache)
        municipios_dias_completos = _municipios_com_chuva_relevante(setores, previsao)
        logger.info(
            "Triagem por chuva prevista: %d de %d municípios com série completa",
            len(municipios_dias_completos), setores["munic"].nunique(),
        )
        series = _series_openmeteo_por_municipio(
            setores, municipios_dias_completos=municipios_dias_completos, cache=cache,
        )
    except OpenMeteoFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar a Open-Meteo: {exc}") from exc
    referencia = cruzado.attrs["referencia"]

    meta = {
        "fonte": "openmeteo",
        "referencia": referencia.isoformat(),
        "total_setores": len(cruzado),
        "total_municipios": len(series),
        "horizonte_previsao_horas": HORIZONTE_PREVISAO_HORAS,
    }
    return cruzado, series, previsao, meta


def data_setor_mais_recente(datas: pd.Series) -> str | None:
    """Maior `data_setor` como AAAA-MM-DD, ou `None` se nenhuma for legível.

    O BELUGA entrega `data_setor` como texto `AAAA-MM-DD`, mas o caminho
    numérico fica: o ArcGIS da CPRM/SGB entregava a data como milissegundos
    desde 1970 e, sem `unit="ms"`, o pandas lê o número como nanossegundos e
    tudo vira 01/01/1970. Custa nada e documenta a armadilha.
    """
    if pd.api.types.is_numeric_dtype(datas):
        convertidas = pd.to_datetime(datas, unit="ms", errors="coerce")
    else:
        convertidas = pd.to_datetime(datas, errors="coerce")
    if not convertidas.notna().any():
        return None
    return convertidas.max().strftime("%Y-%m-%d")


def _manifesto_beluga(diretorio_dados: Path) -> dict:
    caminho = caminho_manifesto_beluga(diretorio_dados)
    if not caminho.exists():
        logger.warning("Manifesto do BELUGA ausente em %s; selo de frescor sem data.", caminho)
        return {}
    try:
        manifesto = json.loads(caminho.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Manifesto do BELUGA ilegível em %s; selo de frescor sem data.", caminho)
        return {}
    return manifesto if isinstance(manifesto, dict) else {}


def _bloco_setores(setores: gpd.GeoDataFrame, uf: str, diretorio_dados: Path) -> dict:
    """Bloco `setores` do meta: quando o BELUGA coletou, qual o setor mais
    recente e quais fontes aparecem nesta UF.

    `coletado_em` vem do `gerado_em` do manifest do BELUGA, que é gravado
    depois de todos os GeoJSON, então é carimbo confiável da coleta. Não vem do
    dado, e é por isso que ele tem de vir de algum lugar: o detector de dado
    velho do front-end só avisa quando a data existe, então data ausente seria
    coleta parada sem ninguém ver.

    `fontes` lista só as fontes presentes nesta UF, da que tem mais setores
    para a que tem menos. Qualquer ausência vira `None`/lista vazia: o selo
    perde detalhe, a exportação não quebra.
    """
    manifesto = _manifesto_beluga(diretorio_dados)
    entrada = manifesto.get("ufs", {}).get(uf.lower()) or {}
    por_fonte = entrada.get("por_fonte") or {}
    catalogo = {
        f["id"]: f for f in manifesto.get("fontes", [])
        if isinstance(f, dict) and isinstance(f.get("id"), str)
    }

    fontes = []
    for id_fonte, setores_da_fonte in sorted(por_fonte.items(), key=lambda kv: (-kv[1], kv[0])):
        ficha = catalogo.get(id_fonte, {})
        # No manifest a licença é um objeto {nome, url, observacao}; o contrato
        # permite texto simples, então os dois casos entram.
        licenca = ficha.get("licenca")
        fontes.append({
            "id": id_fonte,
            "nome": ficha.get("nome"),
            "orgao": ficha.get("orgao"),
            "licenca": licenca.get("nome") if isinstance(licenca, dict) else licenca,
            "setores": setores_da_fonte,
        })

    mais_recente = None
    if "data_setor" in setores.columns:
        mais_recente = data_setor_mais_recente(setores["data_setor"])

    return {
        "coletado_em": manifesto.get("gerado_em"),
        "mais_recente": mais_recente,
        "contrato": manifesto.get("contrato"),
        "fontes": fontes,
    }


def exportar_dashboard(
    uf: str,
    diretorio_dados: Path,
    saida_dir: Path,
    pontos_grade: list[tuple[float, float]] | None = None,
    cache_openmeteo: CacheOpenMeteo | None = None,
) -> dict:
    """Pré-computa a chuva por setor e grava os arquivos estáticos do dashboard.

    Consulta a Open-Meteo no centroide de cada setor; só precisa dos
    setores já baixados do BELUGA.

    `pontos_grade`, se informado, substitui o centroide de cada setor pelo
    ponto de grade compartilhado (ver `src/processing/grade_espacial.py` e
    `src/export/nacional.py`).

    `cache_openmeteo`, se informado, é repassado para as buscas na
    Open-Meteo (ver src/storage_cache_openmeteo.py).

    Grava em `saida_dir`: `setores_<uf>.geojson`, `series_<uf>.json` (por
    município), `previsao_<uf>.json` e `meta_<uf>.json`. Retorna o conteúdo
    de `meta_<uf>.json`.
    """
    uf_norm = uf.strip().upper()
    caminho_setores_path = caminho_setores_beluga(uf_norm, diretorio_dados)
    if not caminho_setores_path.exists():
        raise ExportacaoDashboardError(
            f"Setores de risco não encontrados em {caminho_setores_path}; "
            f"rode `baixar-beluga --ufs {uf_norm}` primeiro."
        )
    setores = ler_setores(caminho_setores_path)
    saida_dir.mkdir(parents=True, exist_ok=True)

    cruzado, series, previsao, meta = _exportar_openmeteo(
        setores, pontos=pontos_grade, cache=cache_openmeteo,
    )
    meta["gerado_em"] = datetime.now(UTC).isoformat()
    # Blocos por fonte para o selo de atualização do dashboard. `referencia` e
    # `gerado_em` continuam no topo para front-ends antigos ainda em cache.
    meta["setores"] = _bloco_setores(setores, uf_norm, diretorio_dados)
    meta["chuva"] = {
        "fonte": "openmeteo", "ate": meta.get("referencia"), "consultado_em": meta["gerado_em"],
    }
    # Índice da busca nacional do dashboard. Fica no meta, e não num arquivo
    # nacional, porque scripts/mesclar_publicado.py preserva metas por UF: uma UF
    # que falhou hoje continua pesquisável com a lista da véspera.
    meta["municipios"] = sorted({str(m) for m in setores["munic"].dropna()}) if "munic" in setores.columns else []

    _exportar_setores(cruzado, saida_dir / f"setores_{uf_norm.lower()}.geojson")
    (saida_dir / f"series_{uf_norm.lower()}.json").write_text(
        json.dumps(series, ensure_ascii=False, indent=2)
    )
    (saida_dir / f"previsao_{uf_norm.lower()}.json").write_text(
        json.dumps(previsao, ensure_ascii=False, separators=(",", ":"))
    )
    (saida_dir / f"meta_{uf_norm.lower()}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )

    logger.info("Exportados dados do dashboard para %s: %s", uf_norm, meta)
    return meta
