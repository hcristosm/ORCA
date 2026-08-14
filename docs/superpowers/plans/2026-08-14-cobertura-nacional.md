# Cobertura Nacional (27 UFs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize ORCA from SP-only to all 27 UFs: incremental CPRM ingestion (no full national re-download per sync), a spatial grid that keeps the Open-Meteo rain cross-reference within its free-tier rate limit at national scale, and a multi-UF dashboard/CI.

**Architecture:** Three additive layers on top of the existing per-UF pipeline (`src/ingest/cprm.py`, `src/export/dashboard_data.py`): (1) a watermark manifest makes CPRM ingestion incremental; (2) a new `src/processing/grade_espacial.py` module maps setor centroids to shared grid-cell query points, calibrated by binary search against a call budget; (3) a new `src/export/nacional.py` orchestrator computes one grid over all requested UFs' setores before looping the existing per-UF export, and a new CLI command / CI step drives it across all 27 UFs in one run.

**Tech Stack:** Python 3.11, geopandas/pandas, requests, typer (existing stack, no new dependencies).

**Spec:** [docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md](../specs/2026-08-14-cobertura-nacional-design.md)

## Global Constraints

- No new third-party dependencies; use only what's already in `pyproject.toml` (geopandas, pandas, requests, typer, shapely).
- Open-Meteo free tier: 10.000 calls/dia, 5.000/hora, 600/minuto (confirmado em <https://open-meteo.com/en/pricing>, 14/08/2026) — the national export must stay under this via the grid, not by adding retries/pausas alone.
- CPRM/SGB FeatureServer has no `EditDate`/Sync capability (confirmed via `.../risco/FeatureServer/0?f=json`, 14/08/2026) — incremental ingestion must rely only on `objectid` and `data_setor`, and the known gap (attribute edits without a new `data_setor`) is an accepted limitation, not a bug to fix here.
- INMET/ANA/vento ingestion stay UF-scoped (out of scope for this plan, per the spec's "Fora de escopo" section) — only CPRM ingestion and the Open-Meteo (`fonte="openmeteo"`) dashboard export go national.
- Every new/changed Python module keeps this codebase's style: Portuguese identifiers/docstrings, module-level docstring explaining the "why", explicit exception classes (no bare `except Exception`).

---

### Task 1: Manifest path helper for CPRM watermark

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py` (new file — no existing test file for `config.py`)

**Interfaces:**
- Produces: `caminho_manifesto_cprm(uf: str, data_dir: Path = DATA_DIR) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path

from src.config import caminho_manifesto_cprm


def test_caminho_manifesto_cprm_usa_uf_minuscula():
    caminho = caminho_manifesto_cprm("SP", Path("/tmp/dados"))
    assert caminho == Path("/tmp/dados/cprm_manifest_sp.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'caminho_manifesto_cprm'`

- [ ] **Step 3: Implement**

Add to `src/config.py`, right after `caminho_manifesto_inmet`:

```python
def caminho_manifesto_cprm(uf: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"cprm_manifest_{uf.lower()}.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): add manifest path helper for CPRM watermark"
```

---

### Task 2: Incremental CPRM ingestion (objectid + data_setor watermark)

**Files:**
- Modify: `src/ingest/cprm.py`
- Test: `tests/test_cprm.py`

**Interfaces:**
- Consumes: `caminho_manifesto_cprm(uf, data_dir) -> Path` (Task 1)
- Produces: `ingerir_uf(uf: str, output: Path, manifesto_path: Path | None = None, timeout=30.0, max_retries=3, backoff_factor=1.0) -> gpd.GeoDataFrame` (extends existing signature with an optional `manifesto_path` kwarg — all existing call sites keep working unchanged since it defaults to `None`, which derives the path from `output.parent`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cprm.py` (update `_feature` helper to accept `data_setor`, then add new tests):

```python
def _feature(objectid: int, grau_risco: str = "Alto", data_setor: str | None = None) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-47.61, -22.84], [-47.60, -22.84], [-47.60, -22.85], [-47.61, -22.84]]],
        },
        "properties": {
            "objectid": objectid,
            "uf": "SP",
            "munic": "RIO DAS PEDRAS",
            "grau_risco": grau_risco,
            "num_setor": f"SP_TEST_{objectid}",
            "data_setor": data_setor,
        },
    }


@responses.activate
def test_ingerir_uf_grava_manifesto_apos_primeira_ingestao(tmp_path: Path):
    output = tmp_path / "risco_sp.gpkg"
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1, data_setor="2020-01-01"), _feature(2, data_setor="2021-06-15")],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )

    ingerir_uf("SP", output)

    manifesto_path = tmp_path / "cprm_manifest_sp.json"
    assert manifesto_path.exists()
    manifesto = json.loads(manifesto_path.read_text())
    assert manifesto["last_objectid"] == 2
    assert manifesto["last_data_setor"] == "2021-06-15"


@responses.activate
def test_ingerir_uf_segunda_chamada_usa_where_incremental_e_mescla(tmp_path: Path):
    output = tmp_path / "risco_sp.gpkg"
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1, data_setor="2020-01-01"), _feature(2, data_setor="2021-06-15")],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )
    ingerir_uf("SP", output)
    responses.reset()

    capturado = {}

    def _callback(request):
        from urllib.parse import parse_qs, urlparse
        capturado["where"] = parse_qs(urlparse(request.url).query)["where"][0]
        payload = {
            "type": "FeatureCollection",
            "features": [_feature(3, grau_risco="Muito alto", data_setor="2026-08-01")],
            "properties": {"exceededTransferLimit": False},
        }
        return (200, {}, json.dumps(payload))

    responses.add_callback(responses.GET, FEATURE_LAYER_URL, callback=_callback)

    resultado = ingerir_uf("SP", output)

    assert "objectid > 2" in capturado["where"]
    assert "data_setor > TIMESTAMP '2021-06-15" in capturado["where"]
    assert len(resultado) == 3
    assert set(resultado["objectid"]) == {1, 2, 3}

    manifesto = json.loads((tmp_path / "cprm_manifest_sp.json").read_text())
    assert manifesto["last_objectid"] == 3
    assert manifesto["last_data_setor"] == "2026-08-01"


@responses.activate
def test_ingerir_uf_atualiza_registro_existente_sem_duplicar(tmp_path: Path):
    output = tmp_path / "risco_sp.gpkg"
    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1, grau_risco="Alto", data_setor="2020-01-01")],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )
    ingerir_uf("SP", output)
    responses.reset()

    responses.add(
        responses.GET,
        FEATURE_LAYER_URL,
        json={
            "type": "FeatureCollection",
            "features": [_feature(1, grau_risco="Muito alto", data_setor="2026-08-01")],
            "properties": {"exceededTransferLimit": False},
        },
        status=200,
    )

    resultado = ingerir_uf("SP", output)

    assert len(resultado) == 1
    assert resultado.iloc[0]["grau_risco"] == "Muito alto"
```

Add `import json` at the top of `tests/test_cprm.py` (needed for the new assertions).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cprm.py -v`
Expected: FAIL — `test_ingerir_uf_grava_manifesto_apos_primeira_ingestao` fails because no manifest file is written yet (current `ingerir_uf` doesn't create one); the where-clause and merge tests fail similarly.

- [ ] **Step 3: Implement incremental fetch + merge in `src/ingest/cprm.py`**

Replace the module's query/fetch section to parametrize `where`, and add manifest + merge helpers. Full new content for the relevant parts of `src/ingest/cprm.py`:

```python
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
    # ... (corpo do laço de retry inalterado, só troca a construção de `params["where"]`
    #      que antes vinha embutida aqui e agora é recebida pronta)
```

(Keep the retry loop body identical to today — only the `where` construction moves out of `_query_pagina` into its caller.)

```python
def fetch_setores_risco(
    uf: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    session: requests.Session | None = None,
    where_extra: str | None = None,
) -> gpd.GeoDataFrame:
    """Baixa os setores de risco geológico de uma UF via ArcGIS REST (GeoJSON).

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
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
) -> gpd.GeoDataFrame:
    """Busca (incrementalmente) os setores de risco de uma UF e salva em GeoPackage.

    A partir da segunda execução, consulta só `objectid`/`data_setor` acima
    do marcador d'água salvo em `manifesto_path` (padrão:
    `caminho_manifesto_cprm(uf, output.parent)`), mescla com o GeoPackage
    existente e atualiza o marcador. Uma edição de atributo que não altera
    `data_setor` não é capturada por este filtro — ver
    docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md.

    Se a busca remota falhar e já existir um GeoPackage em cache local
    (`output`), usa o cache e avisa, em vez de quebrar a ingestão inteira.
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
        if output.exists():
            logger.warning(
                "Fonte remota da CPRM/SGB indisponível; usando cache local em %s", output
            )
            return ler_setores(output)
        raise
```

Update the module's imports: add `import json`, `import pandas as pd`, and `from src.config import caminho_manifesto_cprm, validar_uf as _validar_uf` (replacing the existing `validar_uf` import line).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cprm.py -v`
Expected: PASS (all tests, including the pre-existing ones — `_query_pagina`'s signature change is internal, `fetch_setores_risco`'s public signature is backward compatible since `where_extra` defaults to `None`)

- [ ] **Step 5: Commit**

```bash
git add src/ingest/cprm.py tests/test_cprm.py
git commit -m "feat(cprm): incremental ingestion via objectid/data_setor watermark"
```

---

### Task 3: Adaptive spatial grid module

**Files:**
- Create: `src/processing/grade_espacial.py`
- Test: `tests/test_grade_espacial.py`

**Interfaces:**
- Produces:
  - `calibrar_tamanho_celula(pontos: list[tuple[float, float]], orcamento_alvo: int, tamanho_min: float = 0.001, tamanho_max: float = 5.0, iteracoes: int = 30) -> float`
  - `mapear_para_grade(pontos: list[tuple[float, float]], tamanho: float) -> list[tuple[float, float]]`
  - `contar_celulas_ocupadas(pontos: list[tuple[float, float]], tamanho: float) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grade_espacial.py
import pytest

from src.processing.grade_espacial import (
    calibrar_tamanho_celula,
    contar_celulas_ocupadas,
    mapear_para_grade,
)


def test_contar_celulas_ocupadas_agrupa_pontos_proximos():
    pontos = [(-23.500, -46.600), (-23.501, -46.601), (-23.900, -47.200)]
    # célula bem grossa: os dois primeiros pontos (bem próximos) caem juntos
    assert contar_celulas_ocupadas(pontos, tamanho=1.0) == 2
    # célula bem fina: cada ponto fica isolado
    assert contar_celulas_ocupadas(pontos, tamanho=0.0001) == 3


def test_calibrar_tamanho_celula_atende_orcamento():
    pontos = [(-23.0 - i * 0.001, -46.0 - i * 0.001) for i in range(500)]
    tamanho = calibrar_tamanho_celula(pontos, orcamento_alvo=50)
    assert contar_celulas_ocupadas(pontos, tamanho) <= 50


def test_calibrar_tamanho_celula_orcamento_folgado_preserva_detalhe():
    pontos = [(-23.0 - i * 1.0, -46.0 - i * 1.0) for i in range(5)]  # bem espalhados
    tamanho = calibrar_tamanho_celula(pontos, orcamento_alvo=1000)
    assert contar_celulas_ocupadas(pontos, tamanho) == 5


def test_calibrar_tamanho_celula_pontos_vazio_levanta_erro():
    with pytest.raises(ValueError):
        calibrar_tamanho_celula([], orcamento_alvo=100)


def test_mapear_para_grade_pontos_na_mesma_celula_recebem_mesmo_ponto():
    pontos = [(-23.500, -46.600), (-23.501, -46.601), (-23.900, -47.200)]
    mapeado = mapear_para_grade(pontos, tamanho=1.0)

    assert mapeado[0] == mapeado[1]
    assert mapeado[2] != mapeado[0]
    assert len(mapeado) == len(pontos)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_grade_espacial.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.processing.grade_espacial'`

- [ ] **Step 3: Implement**

```python
# src/processing/grade_espacial.py
"""Grade espacial adaptativa para consultas em lote à Open-Meteo.

Ver docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md. Em vez
de "1 consulta por centroide de setor", agrupa setores próximos numa célula
de grade e consulta 1 ponto por célula ocupada, o que mantém o total de
chamadas diárias à Open-Meteo dentro do orçamento mesmo em escala nacional.
O tamanho da célula é calibrado automaticamente por busca binária contra os
centroides reais (não por limiares de densidade escolhidos à mão): regiões
densas naturalmente produzem mais células nessa resolução, regiões esparsas
produzem poucas.
"""

from __future__ import annotations

TAMANHO_CELULA_MIN_GRAUS = 0.001  # ~100m no equador
TAMANHO_CELULA_MAX_GRAUS = 5.0    # maior que qualquer UF brasileira


def _celula(ponto: tuple[float, float], tamanho: float) -> tuple[int, int]:
    lat, lon = ponto
    return (int(lat // tamanho), int(lon // tamanho))


def contar_celulas_ocupadas(pontos: list[tuple[float, float]], tamanho: float) -> int:
    """Quantas células distintas de tamanho `tamanho` (graus) os `pontos` ocupam."""
    return len({_celula(p, tamanho) for p in pontos})


def calibrar_tamanho_celula(
    pontos: list[tuple[float, float]],
    orcamento_alvo: int,
    tamanho_min: float = TAMANHO_CELULA_MIN_GRAUS,
    tamanho_max: float = TAMANHO_CELULA_MAX_GRAUS,
    iteracoes: int = 30,
) -> float:
    """Busca binária pelo menor tamanho de célula (mais detalhe) cujo total de
    células ocupadas ainda cabe em `orcamento_alvo`.

    Se mesmo `tamanho_max` estourar o orçamento, retorna `tamanho_max` (o
    orçamento é inviável para este conjunto de pontos com uma única célula
    nacional; quem chama decide se reduz o orçamento ou aceita o excesso).
    """
    if not pontos:
        raise ValueError("pontos vazio; nada para calibrar.")

    if contar_celulas_ocupadas(pontos, tamanho_max) > orcamento_alvo:
        return tamanho_max

    baixo, alto = tamanho_min, tamanho_max
    melhor = tamanho_max
    for _ in range(iteracoes):
        meio = (baixo + alto) / 2
        if contar_celulas_ocupadas(pontos, meio) <= orcamento_alvo:
            melhor = meio
            alto = meio
        else:
            baixo = meio
    return melhor


def mapear_para_grade(pontos: list[tuple[float, float]], tamanho: float) -> list[tuple[float, float]]:
    """Mapeia cada ponto para o centro da sua célula de grade (tamanho em graus).

    Pontos na mesma célula recebem exatamente o mesmo ponto de saída, o que
    permite a quem consulta a Open-Meteo deduplicar por célula antes de
    despachar o lote (ver `_calcular_chuva_openmeteo` em
    `src/export/dashboard_data.py`).
    """
    saida = []
    for lat, lon in pontos:
        cel_lat, cel_lon = _celula((lat, lon), tamanho)
        centro_lat = (cel_lat + 0.5) * tamanho
        centro_lon = (cel_lon + 0.5) * tamanho
        saida.append((centro_lat, centro_lon))
    return saida
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_grade_espacial.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/processing/grade_espacial.py tests/test_grade_espacial.py
git commit -m "feat(processing): adaptive spatial grid for Open-Meteo query budget"
```

---

### Task 4: Wire the grid into the Open-Meteo cross-reference (dedupe by query point)

**Files:**
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: nothing new from other tasks (this task only changes how `_calcular_chuva_openmeteo` sources its query points; grid calibration itself is wired in Task 5)
- Produces:
  - `_calcular_chuva_openmeteo(setores, janelas=(24,72), dias_historico=..., dias_previsao=..., agora=None, pontos: list[tuple[float,float]] | None = None) -> tuple[gpd.GeoDataFrame, dict]` (adds `pontos`)
  - `_exportar_openmeteo(setores, pontos: list[tuple[float,float]] | None = None) -> tuple[...]` (adds `pontos`, passes through)
  - `exportar_dashboard(uf, ano, diretorio_dados, saida_dir, fonte="openmeteo", pontos_grade: list[tuple[float,float]] | None = None) -> dict` (adds `pontos_grade`; raises `ValueError` if passed with `fonte="inmet"`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard_data.py`:

```python
def test_calcular_chuva_openmeteo_deduplica_pontos_repetidos(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL

    agora = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    # os dois setores recebem o MESMO ponto de consulta (grade grossa) --
    # só deve sair 1 ponto no corpo da chamada, não 2.
    pontos_grade = [(-23.5, -46.6), (-23.5, -46.6)]

    corpo_capturado = {}

    def _callback(request):
        import json as _json
        corpo_capturado.update(_json.loads(request.body))
        resposta = [{
            "latitude": -23.5, "longitude": -46.6,
            "hourly": {"time": horas_iso, "precipitation": [1.0] * 61},
        }]
        return (200, {}, _json.dumps(resposta))

    with responses.RequestsMock() as rsps:
        rsps.add_callback(responses.POST, FORECAST_URL, callback=_callback)
        resultado, _ = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora, pontos=pontos_grade)

    assert len(corpo_capturado["latitude"]) == 1
    assert set(resultado["fonte_estacao"]) == {"openmeteo"}
    assert len(resultado) == 2
    assert resultado.iloc[0]["chuva_24h"] == pytest.approx(24.0)
    assert resultado.iloc[1]["chuva_24h"] == pytest.approx(24.0)


def test_exportar_dashboard_pontos_grade_com_fonte_inmet_levanta_erro(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    with pytest.raises(ValueError):
        exportar_dashboard(
            "SP", 2026, tmp_path, tmp_path / "export",
            fonte="inmet", pontos_grade=[(-23.5, -46.6), (-23.5, -46.6)],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v -k "deduplica or pontos_grade"`
Expected: FAIL — `_calcular_chuva_openmeteo() got an unexpected keyword argument 'pontos'`, and `exportar_dashboard()` raises `TypeError` instead of `ValueError` for the unknown kwarg.

- [ ] **Step 3: Implement**

In `src/export/dashboard_data.py`, replace `_calcular_chuva_openmeteo` with:

```python
def _calcular_chuva_openmeteo(
    setores: gpd.GeoDataFrame,
    janelas: tuple[int, ...] = (24, 72),
    dias_historico: int = DIAS_HISTORICO_CRUZAMENTO,
    dias_previsao: int = DIAS_PREVISAO_ALERTA,
    agora: pd.Timestamp | None = None,
    pontos: list[tuple[float, float]] | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Consulta a Open-Meteo e calcula a chuva acumulada por setor.

    `pontos`, se informado, é usado no lugar do centroide de cada setor
    (uma tupla `(lat, lon)` por setor, mesma ordem) — é como a grade
    espacial nacional (`src/processing/grade_espacial.py`) injeta pontos
    compartilhados entre setores próximos. Pontos repetidos (mesma tupla)
    são deduplicados antes da chamada à Open-Meteo e a série resultante é
    reaproveitada por todos os setores que compartilham o ponto, o que é o
    mecanismo real de economia de chamadas da grade.

    Sem estação: `distancia_km` é sempre 0.0; `codigo_estacao`/`nome_estacao`
    identificam a fonte, não uma estação real. `agora` é parametrizável para
    tornar testes determinísticos, em produção usa o instante atual.

    Retorna `(resultado, previsao)`: `resultado` é o GeoDataFrame de sempre
    (chuva observada em `janelas`); `previsao` é
    `{num_setor: [[iso, mm], ...]}`, a trajetória do acumulado de 72h nas
    próximas horas (ver `src.processing.previsao.trajetoria_chuva_72h`), calculada a partir da
    mesma série já buscada, sem uma segunda consulta à API.
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")

    pontos = pontos if pontos is not None else [(pt.y, pt.x) for pt in centroides_4326(setores)]

    pontos_unicos = sorted(set(pontos))
    indice_por_ponto = {ponto: i for i, ponto in enumerate(pontos_unicos)}
    series_unicas = fetch_precipitacao_batch(pontos_unicos, dias_historico=dias_historico, dias_previsao=dias_previsao)
    series = [series_unicas[indice_por_ponto[ponto]] for ponto in pontos]

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
            chuva_acumulada(serie, referencia, horas) for serie in series
        ]

    previsao = {
        num_setor: trajetoria_chuva_72h(serie, referencia)
        for num_setor, serie in zip(setores["num_setor"], series)
    }

    resultado.attrs["referencia"] = referencia
    return resultado, previsao
```

Update `_exportar_openmeteo` and `exportar_dashboard`:

```python
def _exportar_openmeteo(
    setores: gpd.GeoDataFrame, pontos: list[tuple[float, float]] | None = None
) -> tuple[pd.DataFrame, dict, dict, dict]:
    """Estratégia `fonte="openmeteo"`: consulta direto no centroide de cada setor
    (ou nos pontos de grade compartilhados, se `pontos` for informado).

    Retorna `(cruzado, series, previsao, meta)` prontos para gravação;
    `meta` já traz todos os campos específicos desta fonte, exceto
    `gerado_em` (adicionado por `exportar_dashboard`, comum às duas fontes).
    """
    try:
        cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), pontos=pontos)
        series = _series_openmeteo_por_municipio(setores)
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
```

```python
def exportar_dashboard(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    fonte: str = "openmeteo",
    pontos_grade: list[tuple[float, float]] | None = None,
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
        cruzado, series, previsao, meta = _exportar_openmeteo(setores, pontos=pontos_grade)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: PASS (all tests, including pre-existing ones — default `pontos=None` preserves current per-setor-centroid behavior)

- [ ] **Step 5: Commit**

```bash
git add src/export/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat(export): accept shared grid query points in Open-Meteo cross-reference"
```

---

### Task 5: National export orchestrator (one grid, many UFs)

**Files:**
- Create: `src/export/nacional.py`
- Test: `tests/test_export_nacional.py`

**Interfaces:**
- Consumes:
  - `caminho_setores(uf, data_dir) -> Path`, `UFS_VALIDAS` (`src/config.py`)
  - `ler_setores(caminho) -> gpd.GeoDataFrame` (`src/storage.py`)
  - `centroides_4326(setores) -> gpd.GeoSeries` (`src/processing/cruzamento.py`)
  - `calibrar_tamanho_celula`, `mapear_para_grade` (Task 3)
  - `exportar_dashboard(..., pontos_grade=...)`, `ExportacaoDashboardError` (Task 4)
- Produces: `exportar_nacional(ufs: list[str], ano: int, diretorio_dados: Path, saida_dir: Path, orcamento_alvo: int = 8000) -> dict[str, dict]` — also writes `ufs_disponiveis.json` to `saida_dir`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_export_nacional.py
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import responses
from shapely.geometry import Polygon

from src.config import caminho_setores
from src.export.nacional import exportar_nacional
from src.ingest.openmeteo import FORECAST_URL
from src.storage import salvar_setores


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


def _setores_uf(uf: str, num_setor: str, cx: float, cy: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"num_setor": [num_setor], "munic": ["CIDADE X"], "grau_risco": ["Alto"]},
        geometry=[_quadrado(cx, cy)],
        crs="EPSG:4326",
    )


def _resposta_openmeteo(n_pontos: int) -> list[dict]:
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    return [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 61}}
        for _ in range(n_pontos)
    ]


def test_exportar_nacional_gera_arquivos_por_uf_e_manifesto(tmp_path: Path):
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    salvar_setores(_setores_uf("RJ", "RJ1", -43.20, -22.90), caminho_setores("RJ", tmp_path))

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        # a grade é calibrada uma vez sobre as 2 UFs, mas a busca à Open-Meteo
        # ainda acontece por UF dentro do loop de export (`exportar_dashboard`
        # continua fazendo 1 chamada de setores + 1 de série por município por
        # UF) -- 2 UFs = 4 POSTs, 1 ponto cada (setores de teste bem
        # espalhados, cada um isolado na própria célula).
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP setores
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP município
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ setores
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ município
        resultados = exportar_nacional(["SP", "RJ"], 2026, tmp_path, saida, orcamento_alvo=1000)

    assert set(resultados.keys()) == {"SP", "RJ"}
    assert (saida / "setores_sp.geojson").exists()
    assert (saida / "setores_rj.geojson").exists()

    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["RJ", "SP"]

    for meta in resultados.values():
        assert "tamanho_celula_grade_graus" in meta
        assert "total_celulas_grade" in meta


def test_exportar_nacional_pula_uf_sem_setores_ingeridos(tmp_path: Path):
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        resultados = exportar_nacional(["SP", "RJ"], 2026, tmp_path, saida, orcamento_alvo=1000)

    assert set(resultados.keys()) == {"SP"}
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["SP"]


def test_exportar_nacional_nenhuma_uf_ingerida_levanta_erro(tmp_path: Path):
    with pytest.raises(ValueError):
        exportar_nacional(["SP", "RJ"], 2026, tmp_path, tmp_path / "export")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export_nacional.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.export.nacional'`

- [ ] **Step 3: Implement**

```python
# src/export/nacional.py
"""Orquestra a exportação do dashboard para várias UFs de uma vez.

Diferente de chamar `exportar_dashboard` uma UF por vez, este módulo calcula
UMA grade espacial (ver `src/processing/grade_espacial.py`) sobre os
centroides de TODAS as UFs pedidas antes de exportar cada uma, para que o
tamanho de célula calibrado reflita a densidade nacional (não a densidade de
uma UF isolada) e o total de pontos distintos fique dentro do orçamento
mesmo somando todas as UFs.

Nota de implementação: a busca à Open-Meteo em si ainda acontece por UF
(`exportar_dashboard` chama `_calcular_chuva_openmeteo` uma vez por UF, com
a fatia de pontos de grade daquela UF) — não há uma única chamada HTTP
nacional combinando todas as UFs. Uma célula de grade que caia exatamente na
fronteira entre duas UFs pode então ser consultada duas vezes (uma por UF),
em vez de uma só. Isso não compromete o orçamento (o total de pontos
distintos por UF nunca passa do que a calibração previu) nem a
corretude — é só uma pequena perda de eficiência de rede, aceita aqui para
não precisar reescrever `_calcular_chuva_openmeteo` para trabalhar com séries
pré-buscadas. Ver
docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.config import caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError, exportar_dashboard
from src.processing.cruzamento import centroides_4326
from src.processing.grade_espacial import calibrar_tamanho_celula, mapear_para_grade
from src.storage import ler_setores

logger = logging.getLogger(__name__)

ORCAMENTO_ALVO_PADRAO = 8000


def exportar_nacional(
    ufs: list[str],
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    orcamento_alvo: int = ORCAMENTO_ALVO_PADRAO,
) -> dict[str, dict]:
    """Exporta o dashboard (fonte Open-Meteo) para várias UFs, com 1 grade nacional.

    UFs sem setores ingeridos localmente (`ingest-cprm` ainda não rodou para
    elas) são puladas com um aviso, não interrompem as demais. O mesmo vale
    para UFs cuja exportação individual falhar (ex.: Open-Meteo indisponível
    para aquele lote). Grava `ufs_disponiveis.json` em `saida_dir` com as
    UFs exportadas com sucesso (ordem alfabética), para o front-end popular
    o seletor. Retorna `{uf: meta}` só das UFs exportadas com sucesso.
    """
    setores_por_uf = {}
    for uf in ufs:
        caminho = caminho_setores(uf, diretorio_dados)
        if not caminho.exists():
            logger.warning("Setores de %s não encontrados em %s; pulando.", uf, caminho)
            continue
        setores_por_uf[uf] = ler_setores(caminho)

    if not setores_por_uf:
        raise ValueError("Nenhuma das UFs pedidas tem setores ingeridos localmente.")

    todos_pontos: list[tuple[float, float]] = []
    fatias: dict[str, tuple[int, int]] = {}
    for uf, setores in setores_por_uf.items():
        pontos_uf = [(pt.y, pt.x) for pt in centroides_4326(setores)]
        fatias[uf] = (len(todos_pontos), len(todos_pontos) + len(pontos_uf))
        todos_pontos.extend(pontos_uf)

    tamanho_celula = calibrar_tamanho_celula(todos_pontos, orcamento_alvo)
    pontos_grade = mapear_para_grade(todos_pontos, tamanho_celula)
    total_celulas = len(set(pontos_grade))

    resultados: dict[str, dict] = {}
    for uf, (inicio, fim) in fatias.items():
        try:
            meta = exportar_dashboard(
                uf, ano, diretorio_dados, saida_dir,
                fonte="openmeteo", pontos_grade=pontos_grade[inicio:fim],
            )
        except ExportacaoDashboardError as exc:
            logger.warning("Falha ao exportar %s: %s", uf, exc)
            continue
        meta["tamanho_celula_grade_graus"] = tamanho_celula
        meta["total_celulas_grade"] = total_celulas
        resultados[uf] = meta

    (saida_dir / "ufs_disponiveis.json").write_text(
        json.dumps(sorted(resultados.keys()), ensure_ascii=False, indent=2)
    )
    logger.info(
        "Exportação nacional: %d/%d UF(s) com sucesso, grade de %.5f° (%d células).",
        len(resultados), len(ufs), tamanho_celula, total_celulas,
    )
    return resultados
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export_nacional.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/nacional.py tests/test_export_nacional.py
git commit -m "feat(export): orchestrate multi-UF export with one shared national grid"
```

---

### Task 6: CLI command `atualizar-nacional`

**Files:**
- Modify: `src/cli.py`
- Test: `tests/test_cli.py` (new file — no existing CLI test file)

**Interfaces:**
- Consumes: `ingerir_uf` (Task 2, from `src.ingest.cprm`), `exportar_nacional` (Task 5, from `src.export.nacional`), `UFS_VALIDAS` (`src/config.py`)
- Produces: `atualizar-nacional` typer command, invocable as `python -m src.cli atualizar-nacional --ufs SP,RJ --ano 2026`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path

import responses
from typer.testing import CliRunner

from src.cli import app
from src.config import caminho_setores
from src.ingest.cprm import FEATURE_LAYER_URL
from src.ingest.openmeteo import FORECAST_URL

runner = CliRunner()


def _feature(objectid: int, uf: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-47.61, -22.84], [-47.60, -22.84], [-47.60, -22.85], [-47.61, -22.84]]],
        },
        "properties": {
            "objectid": objectid, "uf": uf, "munic": "CIDADE X",
            "grau_risco": "Alto", "num_setor": f"{uf}_{objectid}", "data_setor": "2020-01-01",
        },
    }


def _resposta_openmeteo(n_pontos: int) -> list[dict]:
    import pandas as pd
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    return [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 61}}
        for _ in range(n_pontos)
    ]


@responses.activate
def test_atualizar_nacional_ingere_e_exporta_varias_ufs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saida = tmp_path / "docs" / "dashboard" / "data"

    for uf in ("SP", "RJ"):
        responses.add(
            responses.GET, FEATURE_LAYER_URL,
            match=[responses.matchers.query_param_matcher({"where": f"uf='{uf}'"}, strict_match=False)],
            json={"type": "FeatureCollection", "features": [_feature(1, uf)], "properties": {"exceededTransferLimit": False}},
            status=200,
        )
    # exportar_dashboard roda por UF (setores + série por município cada) --
    # 2 UFs = 4 POSTs, 1 ponto cada.
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP setores
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # SP município
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ setores
    responses.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # RJ município

    resultado = runner.invoke(
        app, ["atualizar-nacional", "--ufs", "SP,RJ", "--ano", "2026",
              "--diretorio", str(tmp_path / "data"), "--saida", str(saida)],
    )

    assert resultado.exit_code == 0, resultado.output
    assert (saida / "ufs_disponiveis.json").exists()
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == ["RJ", "SP"]
```

Note: this test requires `--diretorio`/`--saida` options on the new command (added below) so the test can point at `tmp_path` instead of the real `data/`/`docs/dashboard/data` directories.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `atualizar-nacional` command doesn't exist yet (`No such command`).

- [ ] **Step 3: Implement**

Add to `src/cli.py` (imports first, then the command):

```python
from src.config import DASHBOARD_DATA_DIR, DATA_DIR, UFS_VALIDAS, caminho_setores
from src.export.nacional import ORCAMENTO_ALVO_PADRAO, exportar_nacional
```

(merge into the existing `from src.config import ...` line rather than duplicating it)

```python
@app.command("atualizar-nacional")
def atualizar_nacional_cmd(
    ufs: str = typer.Option(
        ",".join(sorted(UFS_VALIDAS)), "--ufs",
        help="Lista de UFs separada por vírgula, ex.: SP,RJ,MG. Padrão: todas as 27.",
    ),
    ano: int = typer.Option(
        datetime.now(timezone.utc).year, "--ano", help="Ano dos dados do INMET (não usado pela fonte openmeteo)"
    ),
    orcamento_alvo: int = typer.Option(
        ORCAMENTO_ALVO_PADRAO, "--orcamento-alvo",
        help="Teto de chamadas à Open-Meteo por execução, para calibrar a grade espacial",
    ),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    saida: Path = typer.Option(DASHBOARD_DATA_DIR, "--saida", help="Diretório de saída do dashboard"),
) -> None:
    """Ingere setores da CPRM (incremental) e exporta o dashboard para várias UFs de uma vez,
    compartilhando 1 grade espacial nacional para caber no rate limit da Open-Meteo.

    Não ingere INMET/ANA/vento (essas fontes continuam por UF, via `atualizar`);
    esta é a via nacional só para setores + chuva Open-Meteo, ver
    docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md.
    """
    lista_ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]
    falhas_cprm = []
    for uf in lista_ufs:
        try:
            ingerir_cprm(uf, caminho_setores(uf, diretorio))
        except (CPRMFetchError, ValueError) as exc:
            typer.echo(f"  FALHA na CPRM/SGB ({uf}): {exc}", err=True)
            falhas_cprm.append(uf)

    resultados = exportar_nacional(lista_ufs, ano, diretorio, saida, orcamento_alvo=orcamento_alvo)
    typer.echo(f"{len(resultados)}/{len(lista_ufs)} UF(s) exportada(s) para {saida}.")
    if falhas_cprm:
        typer.echo(f"Falha na ingestão CPRM: {', '.join(falhas_cprm)}", err=True)
    if len(resultados) < len(lista_ufs):
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: PASS (all tests, project-wide)

- [ ] **Step 6: Commit**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat(cli): add atualizar-nacional command for multi-UF ingestion/export"
```

---

### Task 7: Dashboard front-end UF selector

**Files:**
- Modify: `docs/dashboard/index.html`

**Interfaces:**
- Consumes: `data/ufs_disponiveis.json` (written by `exportar_nacional`, Task 5)

- [ ] **Step 1: Add the selector markup**

In `docs/dashboard/index.html`, near the existing header controls (find the block containing the theme toggle button, before `<main>`), add:

```html
<div class="campo campo-uf">
  <label for="ufSelect">UF</label>
  <select id="ufSelect"></select>
</div>
```

- [ ] **Step 2: Make `UF` mutable and load the available-UFs manifest**

Replace `const UF = "sp";` with:

```javascript
let UF = "sp";
let ufsDisponiveis = ["sp"];

async function carregarUfsDisponiveis() {
  try {
    const resp = await fetch("data/ufs_disponiveis.json");
    if (resp.ok) {
      const lista = await resp.json();
      if (Array.isArray(lista) && lista.length > 0) {
        ufsDisponiveis = lista.map((uf) => uf.toLowerCase());
      }
    }
  } catch (e) {
    // manifesto ainda não existe (deploy antigo/dev local só com SP) -- mantém o padrão.
  }
  if (!ufsDisponiveis.includes(UF)) UF = ufsDisponiveis[0];

  const select = document.getElementById("ufSelect");
  select.innerHTML = ufsDisponiveis
    .map((uf) => `<option value="${uf}">${uf.toUpperCase()}</option>`)
    .join("");
  select.value = UF;
  select.addEventListener("change", () => {
    UF = select.value;
    carregarDados();
  });
}
```

- [ ] **Step 3: Wire it into startup**

Find the code that calls `carregarDados()` on page load (near the bottom of the `<script>` block) and change it to await the manifest first:

```javascript
carregarUfsDisponiveis().then(carregarDados);
```

- [ ] **Step 4: Manual verification**

Run: `python -m src.cli exportar-dashboard --uf SP` then, from `docs/dashboard/`, `python -m http.server 8000` and open `http://localhost:8000`.
Expected: page loads SP as before (selector shows just "SP" until `ufs_disponiveis.json` exists with more entries). Manually create a `docs/dashboard/data/ufs_disponiveis.json` with `["RJ", "SP"]` and a copy of the SP files renamed to `_rj` to confirm switching the selector re-fetches and re-renders for the new UF without a page reload.

- [ ] **Step 5: Commit**

```bash
git add docs/dashboard/index.html
git commit -m "feat(dashboard): add UF selector driven by ufs_disponiveis.json"
```

---

### Task 8: CI workflow runs the national update

**Files:**
- Modify: `.github/workflows/atualizar-dados.yml`
- Modify: `scripts/atualizar_dados.py` (check current contents first — see Step 1)

**Interfaces:**
- Consumes: `atualizar-nacional` CLI command (Task 6)

- [ ] **Step 1: Read the current script**

Run: `cat scripts/atualizar_dados.py`

This script currently wraps the single-UF `atualizar` CLI command with the `--uf`/`--ano` args the workflow passes it. Confirm its exact structure before editing (it's not reproduced here since it wasn't read as part of this plan's research — read it fresh before writing Step 2's diff).

- [ ] **Step 2: Point the script at the national command**

Modify `scripts/atualizar_dados.py` so it invokes `python -m src.cli atualizar-nacional --ufs "$UFS" --ano "$ANO"` instead of the single-UF `atualizar` command, accepting a comma-separated `--ufs` argument (plural) in place of the current single `--uf`. Keep the same subprocess-invocation style already used in the file.

- [ ] **Step 3: Update the workflow**

In `.github/workflows/atualizar-dados.yml`:

```yaml
on:
  schedule:
    - cron: "0 9 * * *"
  workflow_dispatch:
    inputs:
      ufs:
        description: "UFs a atualizar, separadas por vírgula (vazio = todas as 27)"
        required: false
        default: ""
      ano:
        description: "Ano dos dados históricos do INMET"
        required: false
        default: "2026"
```

Update the run step:

```yaml
      - name: Rodar atualização nacional
        run: >
          python scripts/atualizar_dados.py
          --ufs "${{ github.event.inputs.ufs || '' }}"
          --ano "${{ github.event.inputs.ano || '2026' }}"
```

(An empty `--ufs` means "all 27" — `atualizar-nacional`'s `--ufs` option already defaults to all of `UFS_VALIDAS` when not passed; `scripts/atualizar_dados.py` should omit the `--ufs` flag entirely when the input is empty, rather than passing `--ufs ""`.)

Update the artifact step's `name` (currently `dados-orca-${{ github.event.inputs.uf || 'SP' }}`) to a fixed name since there's no longer a single UF:

```yaml
      - name: Publicar dados como artefato
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: dados-orca-nacional
          path: |
            data/*.gpkg
            data/*.csv
            data/ultima_atualizacao.txt
          retention-days: 14
```

- [ ] **Step 4: Manual verification**

Run: `python scripts/atualizar_dados.py --ufs SP,RJ --ano 2026` locally.
Expected: exits 0, `data/risco_sp.gpkg`/`data/risco_rj.gpkg` and `docs/dashboard/data/{setores,series,meta}_{sp,rj}.geojson|json` plus `ufs_disponiveis.json` all exist afterward.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/atualizar-dados.yml scripts/atualizar_dados.py
git commit -m "ci: run national multi-UF update instead of single-UF cron"
```

---

## Self-Review Notes

- **Spec coverage:** Component 1 (incremental CPRM) → Tasks 1–2. Component 2 (adaptive grid) → Task 3. Component 3 (multi-UF export/dashboard/CI) → Tasks 4–8. All three spec sections have corresponding tasks.
- **Placeholder scan:** no TBD/TODO; Task 8 Step 1 explicitly asks the executor to read `scripts/atualizar_dados.py` before editing rather than guessing its contents — this is a deliberate "read before write" instruction, not a placeholder, since the file wasn't part of this plan's research and its exact current shape must be read live before writing an accurate diff.
- **Type/signature consistency:** `pontos_grade`/`pontos` naming checked across Tasks 4–6 (`_calcular_chuva_openmeteo(pontos=...)` → `_exportar_openmeteo(pontos=...)` → `exportar_dashboard(pontos_grade=...)` → `exportar_nacional` builds `pontos_grade` from `mapear_para_grade`); `caminho_manifesto_cprm` signature (Task 1) matches its use in Task 2.
