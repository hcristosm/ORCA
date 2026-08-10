# Open-Meteo como fonte de chuva do dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar a Open-Meteo como fonte de chuva do dashboard estático — consulta direta por setor (sem "estação mais próxima"), virando a fonte padrão da exportação, sem remover ou alterar o caminho existente de INMET/ANA.

**Architecture:** Um novo cliente sem estado (`src/ingest/openmeteo.py`) consulta a API Open-Meteo via POST em lote (todas as coordenadas de uma vez — validado com as 904 coordenadas de SP numa única chamada). `src/export/dashboard_data.py` ganha um parâmetro `fonte` que bifurca entre o caminho antigo (INMET/ANA, inalterado) e um novo caminho que consulta a Open-Meteo direto no centroide de cada setor (mapa/tabela) e num ponto por município (gráfico). CLI e frontend recebem ajustes mínimos para expor a nova fonte.

**Tech Stack:** Python 3.11+, `requests` (POST em lote, retry/backoff), `geopandas`/`shapely` (centroides), `pandas` (acumulado de chuva), `pytest` + `responses` (testes com HTTP mockado).

## Global Constraints

- `src/ingest/inmet.py`, `src/ingest/ana.py` e `src/processing/cruzamento.py` não são modificados por este plano.
- A API Open-Meteo é consultada via `POST https://api.open-meteo.com/v1/forecast` com `latitude`/`longitude` como arrays JSON — **nunca GET com muitas coordenadas na query string** (confirmado: `HTTP 414 URI Too Long` com 904 coordenadas via GET). Sem o parâmetro `timezone` no corpo (a API exige array por coordenada nesse modo; omitir faz ela responder em GMT, equivalente a UTC).
- Sem cache/armazenamento local para a Open-Meteo — toda consulta é ao vivo, no momento da exportação.
- `exportar_dashboard(uf, ano, diretorio_dados, saida_dir, fonte="openmeteo")`: `fonte="inmet"` mantém exatamente o comportamento atual; `fonte="openmeteo"` (novo padrão) só precisa dos setores (CPRM), não de INMET/ANA terem sido ingeridos.
- Setores exportados com `fonte="openmeteo"` usam `distancia_km=0.0`, `codigo_estacao="openmeteo"`, `nome_estacao="Open-Meteo (centro do setor)"`, `fonte_estacao="openmeteo"` — mesmo schema de `PROPRIEDADES_SETOR` já existente, sem mudança de colunas.
- Série temporal (gráfico) com `fonte="openmeteo"` é agrupada por **município**, não por setor nem por estação — chave do dicionário é o nome do município.

---

### Task 1: Cliente Open-Meteo (`src/ingest/openmeteo.py`)

**Files:**
- Create: `src/ingest/openmeteo.py`
- Test: `tests/test_openmeteo.py`

**Interfaces:**
- Produces: `OpenMeteoFetchError` (exceção), `FORECAST_URL` (constante, para os testes mockarem), `fetch_precipitacao_batch(pontos: list[tuple[float, float]], dias_historico: int = 30, timeout: float = 60.0, max_retries: int = 3, backoff_factor: float = 2.0, session: requests.Session | None = None) -> list[pd.DataFrame]` — cada DataFrame tem colunas `data_hora` (tz-aware UTC) e `chuva_mm`, na mesma ordem de `pontos`. Usado por Task 2.

- [ ] **Step 1: Criar `src/ingest/openmeteo.py`**

```python
"""Cliente da API Open-Meteo — chuva horária por coordenada, quase em tempo real.

Diferente do INMET (ZIP anual, dias de defasagem) e da ANA (rede de estações
telemétricas, cobertura parcial), a Open-Meteo (https://open-meteo.com/) não
tem o conceito de estação: qualquer coordenada pode ser consultada
diretamente. Isso permite computar a chuva acumulada no próprio centro de
cada setor de risco, sem precisar de "estação mais próxima" (ver
src/export/dashboard_data.py).

Investigação em 10/08/2026 (requisições reais): a API aceita todas as ~900
coordenadas de um estado numa única requisição POST (testado com os 904
setores de SP: ~2s, sem paginar). GET com muitas coordenadas na query string
esbarra em HTTP 414 (URI Too Long) bem antes disso — por isso este cliente
usa POST. O parâmetro `timezone` não pode ser enviado como string simples
nesse modo (a API exige um array, um valor por coordenada); omiti-lo faz a
API responder em GMT, equivalente a UTC para os fins deste projeto.

Sem cache/armazenamento local: cada exportação consulta a API ao vivo, o que
é viável porque o custo por chamada é baixo — não há aqui o problema de
"baixar o ano inteiro de novo" que motivou a ingestão incremental do INMET.
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoFetchError(RuntimeError):
    """Erro ao buscar dados de chuva da Open-Meteo."""


def fetch_precipitacao_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 30,
    timeout: float = 60.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
) -> list[pd.DataFrame]:
    """Busca chuva horária para uma lista de pontos `(lat, lon)`, numa única requisição.

    Retorna uma lista de DataFrames (`data_hora, chuva_mm`), um por ponto, na
    mesma ordem de `pontos`. `dias_historico` controla quantos dias para trás
    são pedidos (a API aceita até 92); `forecast_days=1` garante que a hora
    mais recente disponível entra na resposta — filtrar por "não é futuro" é
    responsabilidade de quem consome o DataFrame, não deste cliente.
    """
    if not pontos:
        return []

    sess = session or requests.Session()
    corpo = {
        "latitude": [lat for lat, _ in pontos],
        "longitude": [lon for _, lon in pontos],
        "hourly": ["precipitation"],
        "past_days": dias_historico,
        "forecast_days": 1,
    }

    resposta_ok = None
    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = sess.post(FORECAST_URL, json=corpo, timeout=timeout)
            resp.raise_for_status()
            resposta_ok = resp
            break
        except requests.RequestException as exc:
            last_exc = exc
            espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao consultar a Open-Meteo (tentativa %d/%d): %s. Aguardando %.1fs.",
                tentativa, max_retries, exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)

    if resposta_ok is None:
        raise OpenMeteoFetchError(
            f"Não foi possível consultar a Open-Meteo após {max_retries} tentativas"
        ) from last_exc

    dados = resposta_ok.json()
    series = []
    for item in dados:
        horario = item.get("hourly", {})
        horas = horario.get("time", [])
        precipitacoes = horario.get("precipitation", [])
        df = pd.DataFrame(
            {
                "data_hora": pd.to_datetime(horas, utc=True),
                "chuva_mm": precipitacoes,
            }
        )
        series.append(df)
    return series
```

- [ ] **Step 2: Criar `tests/test_openmeteo.py`**

```python
import pandas as pd
import pytest
import responses

from src.ingest.openmeteo import FORECAST_URL, OpenMeteoFetchError, fetch_precipitacao_batch


def _resposta(horas: list[str], series_chuva: list[list]) -> list[dict]:
    return [
        {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "precipitation": chuva}}
        for chuva in series_chuva
    ]


@responses.activate
def test_fetch_precipitacao_batch_parseia_lista_na_ordem_dos_pontos():
    horas = ["2026-08-10T00:00", "2026-08-10T01:00"]
    resposta = _resposta(horas, [[0.0, 1.2], [0.5, None]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    series = fetch_precipitacao_batch([(-23.5, -46.6), (-22.9, -43.2)])

    assert len(series) == 2
    assert list(series[0]["chuva_mm"]) == [0.0, 1.2]
    assert series[1]["chuva_mm"].isna().iloc[1]
    assert series[0]["data_hora"].dt.tz is not None


def test_fetch_precipitacao_batch_lista_vazia_retorna_vazio():
    assert fetch_precipitacao_batch([]) == []


@responses.activate
def test_fetch_precipitacao_batch_retry_recupera_apos_falha_transitoria():
    responses.add(responses.POST, FORECAST_URL, status=500)
    resposta = _resposta(["2026-08-10T00:00"], [[3.0]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    series = fetch_precipitacao_batch([(-23.5, -46.6)], max_retries=2, backoff_factor=0.01)

    assert len(series) == 1
    assert series[0]["chuva_mm"].iloc[0] == 3.0


@responses.activate
def test_fetch_precipitacao_batch_falha_persistente_levanta_erro():
    responses.add(responses.POST, FORECAST_URL, status=500)

    with pytest.raises(OpenMeteoFetchError):
        fetch_precipitacao_batch([(-23.5, -46.6)], max_retries=2, backoff_factor=0.01)
```

- [ ] **Step 3: Rodar os testes novos**

Run: `pytest tests/test_openmeteo.py -v`
Expected: 4 passed, 0 falhas.

- [ ] **Step 4: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 60 passed (56 antes deste plano + 4 novos), 0 falhas.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/openmeteo.py tests/test_openmeteo.py
git commit -m "feat(ingest): add Open-Meteo client for per-coordinate rainfall"
```

---

### Task 2: `exportar_dashboard` com fonte Open-Meteo

**Files:**
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `fetch_precipitacao_batch`, `OpenMeteoFetchError` (Task 1); `CRS_METRICO`, `_chuva_acumulada` de `src.processing.cruzamento` (já existentes, importados — não modificados).
- Produces: `exportar_dashboard(uf, ano, diretorio_dados, saida_dir, fonte="openmeteo") -> dict` — assinatura estendida (parâmetro `fonte` novo, com esse valor padrão). `meta_<uf>.json` ganha a chave `"fonte"`; com `fonte="openmeteo"`, ganha `"total_municipios"` no lugar de `"total_estacoes_inmet"`/`"total_estacoes_ana"`.

- [ ] **Step 1: Atualizar os imports no topo de `src/export/dashboard_data.py`**

Trocar:

```python
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.config import caminho_chuva, caminho_chuva_ana, caminho_setores
from src.processing.cruzamento import calcular_cruzamento
from src.storage import chuva_existe, ler_chuva, ler_setores
```

Por:

```python
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
```

- [ ] **Step 2: Adicionar `_calcular_chuva_openmeteo` e `_series_openmeteo_por_municipio`**

Inserir logo depois de `_recortar_series` (antes de `exportar_dashboard`):

```python
def _calcular_chuva_openmeteo(
    setores: gpd.GeoDataFrame,
    janelas: tuple[int, ...] = (24, 72),
    dias_historico: int = JANELA_SERIE_DIAS,
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
```

- [ ] **Step 3: Reescrever `exportar_dashboard` com o parâmetro `fonte`**

Substituir a função `exportar_dashboard` inteira por:

```python
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
```

- [ ] **Step 4: Adicionar os testes novos em `tests/test_dashboard_data.py`**

Atualizar o import no topo do arquivo (acrescentar `pandas as pd` já está presente; acrescentar a nova importação):

```python
from src.export.dashboard_data import (
    ExportacaoDashboardError,
    _calcular_chuva_openmeteo,
    exportar_dashboard,
)
```

Adicionar ao final do arquivo:

```python
def test_calcular_chuva_openmeteo_consulta_centroide_e_acumula(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL

    agora = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    resposta = [
        {"latitude": -23.50, "longitude": -46.60, "hourly": {"time": horas_iso, "precipitation": [1.0] * 61}},
        {"latitude": -24.00, "longitude": -47.00, "hourly": {"time": horas_iso, "precipitation": [0.0] * 61}},
    ]

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        resultado = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora)

    assert set(resultado["fonte_estacao"]) == {"openmeteo"}
    assert set(resultado["distancia_km"]) == {0.0}
    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["chuva_24h"] == pytest.approx(24.0)
    s2 = resultado[resultado["num_setor"] == "S2"].iloc[0]
    assert s2["chuva_24h"] == pytest.approx(0.0)


def test_exportar_dashboard_fonte_openmeteo_fim_a_fim(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL

    salvar_setores(setores, caminho_setores("SP", tmp_path))

    agora = pd.Timestamp.now(tz="UTC").floor("h")
    horas = pd.date_range(agora - pd.Timedelta(hours=47), periods=48, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]

    def _resposta_para(n_pontos: int) -> list[dict]:
        return [
            {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 48}}
            for _ in range(n_pontos)
        ]

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_para(2), status=200)  # setores
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_para(2), status=200)  # municípios
        meta = exportar_dashboard("SP", 2026, tmp_path, saida, fonte="openmeteo")

    assert meta["fonte"] == "openmeteo"
    assert meta["total_setores"] == 2
    assert meta["total_municipios"] == 2
    assert "total_estacoes_inmet" not in meta

    gdf = gpd.read_file(saida / "setores_sp.geojson")
    assert set(gdf["fonte_estacao"]) == {"openmeteo"}
    assert set(gdf["codigo_estacao"]) == {"openmeteo"}

    series = json.loads((saida / "series_sp.json").read_text())
    assert set(series.keys()) == {"CIDADE A", "CIDADE B"}
    assert series["CIDADE A"]["fonte"] == "openmeteo"


def test_exportar_dashboard_fonte_inmet_continua_igual(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva = pd.concat(
        [
            _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {i: 1.0 for i in range(40)}, "2026-08-01 00:00"),
            _serie_horaria("A736", -24.001, -47.001, "PERTO DE S2", {i: 0.0 for i in range(40)}, "2026-08-01 00:00"),
        ],
        ignore_index=True,
    )
    salvar_chuva(chuva, caminho_chuva("SP", 2026, tmp_path))

    saida = tmp_path / "export"
    meta = exportar_dashboard("SP", 2026, tmp_path, saida, fonte="inmet")

    assert meta["fonte"] == "inmet"
    assert meta["total_estacoes_inmet"] == 2
    assert "total_municipios" not in meta


def test_exportar_dashboard_fonte_invalida_levanta_erro(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    with pytest.raises(ValueError):
        exportar_dashboard("SP", 2026, tmp_path, tmp_path / "export", fonte="xyz")
```

(Os testes usam `responses.RequestsMock()` como bloco `with` em vez do decorador `@responses.activate` porque cada teste faz **duas** chamadas `POST` mockadas em sequência — para o mesmo host, mas com respostas diferentes por chamada; `RequestsMock` deixa isso explícito no escopo do bloco. Isso é consistente com o resto da suíte, que já usa `responses.activate`/`responses.add` para casos de uma chamada só.)

- [ ] **Step 5: Rodar os testes novos**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 9 passed (5 já existentes + 4 novos), 0 falhas.

- [ ] **Step 6: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 64 passed (60 do Task 1 + 4 novos), 0 falhas.

- [ ] **Step 7: Commit**

```bash
git add src/export/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat(export): add openmeteo as default dashboard rain source"
```

---

### Task 3: CLI (`--fonte`) e ajustes de frontend

**Files:**
- Modify: `src/cli.py`
- Modify: `docs/dashboard/index.html`

**Interfaces:**
- Consumes: `exportar_dashboard(..., fonte=...)` (Task 2).

- [ ] **Step 1: Adicionar `--fonte` em `exportar-dashboard`**

Em `src/cli.py`, trocar a função `exportar_dashboard_cmd`:

```python
@app.command("exportar-dashboard")
def exportar_dashboard_cmd(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(
        datetime.now(timezone.utc).year, "--ano", help="Ano dos dados do INMET a exportar (só usado com --fonte inmet)"
    ),
    fonte: str = typer.Option(
        "openmeteo", "--fonte", help="Fonte de chuva: 'openmeteo' (consulta direta por setor) ou 'inmet' (estação mais próxima, INMET+ANA)"
    ),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    saida: Path = typer.Option(
        None, "--saida", help="Diretório de saída (padrão: docs/dashboard/data/)"
    ),
) -> None:
    """Pré-computa a chuva por setor e gera os arquivos estáticos do dashboard (GeoJSON/JSON)."""
    saida_dir = saida or DASHBOARD_DATA_DIR
    meta = exportar_dashboard(uf, ano, diretorio, saida_dir, fonte=fonte)
    typer.echo(f"{meta['total_setores']} setores exportados para {saida_dir} (fonte: {meta['fonte']})")
```

- [ ] **Step 2: Adicionar `--fonte` em `atualizar`**

Trocar a assinatura de `atualizar`:

```python
@app.command()
def atualizar(
    uf: str = typer.Option(..., "--uf", help="Sigla da UF, ex.: SP"),
    ano: int = typer.Option(..., "--ano", help="Ano dos dados históricos do INMET"),
    fonte: str = typer.Option(
        "openmeteo", "--fonte", help="Fonte de chuva do dashboard exportado: 'openmeteo' ou 'inmet'"
    ),
) -> None:
```

E trocar a chamada de exportação dentro dela:

```python
    typer.echo(f"[{datetime.now(timezone.utc).isoformat()}] Exportando dados do dashboard ({uf_norm}, fonte={fonte})...")
    try:
        meta = exportar_dashboard(uf_norm, ano, DATA_DIR, DASHBOARD_DATA_DIR, fonte=fonte)
        typer.echo(f"  {meta['total_setores']} setores exportados para {DASHBOARD_DATA_DIR}.")
    except (ExportacaoDashboardError, ValueError) as exc:
        typer.echo(f"  FALHA na exportação do dashboard: {exc}", err=True)
        falhas.append("dashboard")
```

- [ ] **Step 3: Verificar a CLI manualmente**

Run: `python -m src.cli exportar-dashboard --help`
Expected: mostra `--fonte` com o texto de ajuda acima, padrão `openmeteo`, sem traceback.

Run: `python -m src.cli atualizar --help`
Expected: mostra `--fonte`, sem traceback.

- [ ] **Step 4: Ajustar o selo do topo em `docs/dashboard/index.html`**

Trocar:

```javascript
    document.getElementById("selo").innerHTML =
      `<b>Referência da chuva:</b> ${formatarData(meta.referencia)} · ` +
      `<b>Dados gerados em:</b> ${formatarData(meta.gerado_em)} · ` +
      `${meta.total_estacoes_inmet} estações INMET, ${meta.total_estacoes_ana} estações ANA`;
```

Por:

```javascript
    const detalheFonte = meta.fonte === "openmeteo"
      ? "Fonte: Open-Meteo (consulta direta por setor)"
      : `${meta.total_estacoes_inmet} estações INMET, ${meta.total_estacoes_ana} estações ANA`;
    document.getElementById("selo").innerHTML =
      `<b>Referência da chuva:</b> ${formatarData(meta.referencia)} · ` +
      `<b>Dados gerados em:</b> ${formatarData(meta.gerado_em)} · ` +
      detalheFonte;
```

- [ ] **Step 5: Esconder a linha de distância no tooltip quando a fonte é Open-Meteo**

Trocar, dentro de `renderizarMapa`:

```javascript
        layer.bindTooltip(
          `<b>${p.munic}</b><br>Setor: ${p.num_setor}<br>Grau: ${p.grau_risco}<br>` +
          `Estação a ${p.distancia_km != null ? p.distancia_km.toFixed(2) : "—"}km ` +
          `(${(p.fonte_estacao || "—").toUpperCase()})<br>Chuva ${estado.janela}h: ${chuva}mm`
        );
```

Por:

```javascript
        const linhaFonte = p.fonte_estacao === "openmeteo"
          ? `Fonte: ${(p.fonte_estacao || "—").toUpperCase()}<br>`
          : `Estação a ${p.distancia_km != null ? p.distancia_km.toFixed(2) : "—"}km ` +
            `(${(p.fonte_estacao || "—").toUpperCase()})<br>`;
        layer.bindTooltip(
          `<b>${p.munic}</b><br>Setor: ${p.num_setor}<br>Grau: ${p.grau_risco}<br>` +
          linhaFonte +
          `Chuva ${estado.janela}h: ${chuva}mm`
        );
```

- [ ] **Step 6: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 64 passed, 0 falhas (este task não adiciona testes — CLI e frontend não têm suíte automatizada própria no projeto, mesmo padrão dos tasks anteriores de CLI/dashboard).

- [ ] **Step 7: Testar a exportação real contra a API (rede)**

Run: `python -m src.cli exportar-dashboard --uf SP` (usa `--fonte openmeteo` por padrão; requer `data/risco_sp.gpkg` já existente de uma ingestão anterior)
Expected: termina sem erro, imprime `<N> setores exportados para .../docs/dashboard/data (fonte: openmeteo)`; `docs/dashboard/data/meta_sp.json` tem `"fonte": "openmeteo"` e uma `"referencia"` de poucas horas atrás (não dias, como o INMET).

- [ ] **Step 8: Commit**

```bash
git add src/cli.py docs/dashboard/index.html
git commit -m "feat(cli,dashboard): expose --fonte flag and adapt UI for openmeteo"
```

---

## Self-Review Notes

- **Spec coverage:** cliente Open-Meteo sem cache (Task 1); cálculo por setor + série por município + `fonte` em `exportar_dashboard` (Task 2); CLI `--fonte` em `exportar-dashboard`/`atualizar` + ajustes de frontend (Task 3). Todos os itens do spec (`docs/superpowers/specs/2026-08-10-openmeteo-fonte-dashboard-design.md`) têm task correspondente.
- **Placeholder scan:** nenhum "TBD"/"TODO" — todo código está escrito por extenso.
- **Consistência de tipos/assinaturas:** `fetch_precipitacao_batch`, `OpenMeteoFetchError`, `FORECAST_URL` definidos na Task 1 e usados com a mesma assinatura na Task 2. `_calcular_chuva_openmeteo`/`_series_openmeteo_por_municipio` definidos e usados dentro do mesmo arquivo (Task 2). `exportar_dashboard(..., fonte=...)` definido na Task 2 e consumido com a mesma assinatura pela CLI (Task 3).
- **Compatibilidade:** `fonte="inmet"` preserva exatamente o schema de `meta_<uf>.json` que já existia antes deste plano (sem a chave nova `"fonte"` antes, mas isso é aditivo — nenhum consumidor existente lia essa chave). Chamadas antigas de `exportar_dashboard(uf, ano, diretorio, saida)` sem o argumento `fonte` continuam funcionando (novo parâmetro tem valor padrão) — mas agora **mudam de comportamento** (padrão passa a ser `openmeteo`, não mais `inmet`), exatamente como decidido com o usuário.
