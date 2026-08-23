# Triagem por chuva prevista para a série de 30 dias por município — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir o volume/tempo da busca de 30 dias de histórico por
município na exportação `fonte="openmeteo"`, pedindo os 30 dias completos só
para municípios com chuva forte prevista (reaproveitando um dado que já é
calculado sem chamada extra), e 4 dias (mesma janela dos setores) para os
demais.

**Architecture:** `_calcular_chuva_openmeteo` já roda antes de
`_series_openmeteo_por_municipio` dentro de `_exportar_openmeteo` e já
retorna `previsao` (trajetória de 72h prevista por setor). Uma nova função
pura agrega `previsao` por município (máximo entre os setores daquele
município) contra `LIMIAR_ATENCAO_MM_PADRAO`; `_series_openmeteo_por_municipio`
passa a fazer até duas chamadas de lote (uma por grupo) em vez de uma.

**Tech Stack:** Python, pandas, geopandas, pytest, `responses` (mock HTTP).

**Spec:** docs/superpowers/specs/2026-08-23-triagem-chuva-serie-municipio-design.md

## Global Constraints

- Reaproveitar `LIMIAR_ATENCAO_MM_PADRAO` (`src/config.py`, valor 100.0) como
  limiar — não criar uma constante nova para o mesmo valor.
- Nenhuma chamada nova à Open-Meteo: o sinal de triagem vem só de `previsao`,
  já calculado por `_calcular_chuva_openmeteo`.
- Município com trajetória vazia ou só valores `None` (sem previsão de
  futuro disponível para nenhum setor daquele município) fica no grupo
  reduzido (não há sinal de "chuva forte prevista" para promovê-lo).
- `_series_openmeteo_por_municipio` e `_municipios_com_chuva_relevante` são
  funções privadas (prefixo `_`) de `src/export/dashboard_data.py` — sem
  preocupação de compatibilidade externa, mas mantendo o retorno de
  `_series_openmeteo_por_municipio` (`dict` por município) inalterado.
- Grupo vazio (nenhum município nele) não deve gerar chamada a
  `fetch_precipitacao_batch`.

---

### Task 1: Agregação de município por chuva prevista

**Files:**
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `setores["num_setor"]`, `setores["munic"]` (já existentes no
  GeoDataFrame de setores); `previsao: dict[str, list[list]]` no formato
  retornado por `_calcular_chuva_openmeteo` (chave `num_setor`, valor lista
  de `[iso_str, mm_ou_None]`, ver `src.processing.previsao.trajetoria_chuva_72h`).
- Produces: `_municipios_com_chuva_relevante(setores, previsao, limiar_mm=LIMIAR_ATENCAO_MM_PADRAO) -> set[str]`,
  usada pela Task 2.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar em `tests/test_dashboard_data.py` (import `LIMIAR_ATENCAO_MM_PADRAO`
de `src.config` e `_municipios_com_chuva_relevante` de
`src.export.dashboard_data` no topo do arquivo, junto dos imports já
existentes de `_calcular_chuva_openmeteo`/`exportar_dashboard`):

```python
def test_municipios_com_chuva_relevante_marca_quem_passa_do_limiar(setores):
    previsao = {
        "S1": [["2026-08-10T00:00", 40.0], ["2026-08-10T03:00", 120.0]],
        "S2": [["2026-08-10T00:00", 10.0], ["2026-08-10T03:00", 20.0]],
    }

    relevantes = _municipios_com_chuva_relevante(setores, previsao)

    assert relevantes == {"CIDADE A"}


def test_municipios_com_chuva_relevante_usa_o_maximo_entre_setores_do_municipio(setores):
    # Dois setores no mesmo município (CIDADE A); só um deles passa do limiar.
    dois_setores_mesmo_municipio = setores.copy()
    dois_setores_mesmo_municipio["munic"] = ["CIDADE A", "CIDADE A"]
    previsao = {
        "S1": [["2026-08-10T00:00", 10.0]],
        "S2": [["2026-08-10T00:00", 150.0]],
    }

    relevantes = _municipios_com_chuva_relevante(dois_setores_mesmo_municipio, previsao)

    assert relevantes == {"CIDADE A"}


def test_municipios_com_chuva_relevante_ignora_trajetoria_so_com_none(setores):
    previsao = {
        "S1": [["2026-08-10T00:00", None], ["2026-08-10T03:00", None]],
        "S2": [["2026-08-10T00:00", 10.0]],
    }

    relevantes = _municipios_com_chuva_relevante(setores, previsao)

    assert relevantes == set()


def test_municipios_com_chuva_relevante_respeita_limiar_customizado(setores):
    previsao = {
        "S1": [["2026-08-10T00:00", 50.0]],
        "S2": [["2026-08-10T00:00", 10.0]],
    }

    relevantes = _municipios_com_chuva_relevante(setores, previsao, limiar_mm=40.0)

    assert relevantes == {"CIDADE A"}
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k municipios_com_chuva_relevante -v`
Expected: FAIL com `ImportError` ou `AttributeError` (`_municipios_com_chuva_relevante` ainda não existe).

- [ ] **Step 3: Implementar `_municipios_com_chuva_relevante`**

Em `src/export/dashboard_data.py`, adicionar o import de
`LIMIAR_ATENCAO_MM_PADRAO` (`from src.config import ...`, junto da linha que
já importa `caminho_chuva, caminho_chuva_ana, caminho_setores`) e a função
logo abaixo de `_calcular_chuva_openmeteo` (antes de
`_series_openmeteo_por_municipio`):

```python
def _municipios_com_chuva_relevante(
    setores: gpd.GeoDataFrame, previsao: dict, limiar_mm: float = LIMIAR_ATENCAO_MM_PADRAO,
) -> set[str]:
    """Municípios com ao menos um setor cuja trajetória de 72h prevista
    (`previsao`, ver `_calcular_chuva_openmeteo`) ultrapassa `limiar_mm` em
    algum ponto futuro -- usado por `_series_openmeteo_por_municipio` para
    decidir quem pede JANELA_SERIE_DIAS completos vs. DIAS_HISTORICO_CRUZAMENTO
    (ver docs/superpowers/specs/2026-08-23-triagem-chuva-serie-municipio-design.md).
    """
    relevantes: set[str] = set()
    for num_setor, munic in zip(setores["num_setor"], setores["munic"]):
        trajetoria = previsao.get(num_setor, [])
        valores = [mm for _, mm in trajetoria if mm is not None]
        if valores and max(valores) >= limiar_mm:
            relevantes.add(munic)
    return relevantes
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k municipios_com_chuva_relevante -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add src/export/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat(dashboard_data): agregar municípios com chuva forte prevista"
```

---

### Task 2: Dois grupos de busca em `_series_openmeteo_por_municipio`

**Files:**
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `_municipios_com_chuva_relevante` (Task 1); `centroides_municipio`
  (`src.processing.cruzamento`, já importado); `fetch_precipitacao_batch`
  (`src.ingest.openmeteo`, já importado); `DIAS_HISTORICO_CRUZAMENTO`,
  `JANELA_SERIE_DIAS` (já definidos em `dashboard_data.py`).
- Produces: `_series_openmeteo_por_municipio(setores, municipios_dias_completos=None, agora=None, cache=None) -> dict`
  — assinatura nova (substitui o parâmetro `dias_historico` antigo, que não
  tinha nenhum chamador externo além de `_exportar_openmeteo`, alterado na
  Task 3). `municipios_dias_completos: set[str] | None`; `None` (padrão)
  preserva o comportamento anterior (todos os municípios pedem
  `JANELA_SERIE_DIAS`).

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_dashboard_data.py`:

```python
def test_series_openmeteo_por_municipio_divide_em_dois_grupos(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL
    from src.export.dashboard_data import _series_openmeteo_por_municipio, JANELA_SERIE_DIAS, DIAS_HISTORICO_CRUZAMENTO

    agora = pd.Timestamp.now(tz="UTC").floor("h")
    horas = pd.date_range(agora - pd.Timedelta(hours=23), periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]

    corpos_capturados = []

    def _callback(request):
        import json as _json
        corpos_capturados.append(_json.loads(request.body))
        resposta = [
            {"latitude": lat, "longitude": lon, "hourly": {"time": horas_iso, "precipitation": [1.0] * 24}}
            for lat, lon in zip(_json.loads(request.body)["latitude"], _json.loads(request.body)["longitude"])
        ]
        return (200, {}, _json.dumps(resposta))

    with responses.RequestsMock() as rsps:
        rsps.add_callback(responses.POST, FORECAST_URL, callback=_callback)
        series = _series_openmeteo_por_municipio(
            setores, municipios_dias_completos={"CIDADE A"}, agora=agora,
        )

    assert set(series.keys()) == {"CIDADE A", "CIDADE B"}
    assert len(corpos_capturados) == 2
    past_days_por_chamada = sorted(c["past_days"] for c in corpos_capturados)
    assert past_days_por_chamada == sorted([JANELA_SERIE_DIAS, DIAS_HISTORICO_CRUZAMENTO])


def test_series_openmeteo_por_municipio_grupo_vazio_nao_gera_chamada(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL
    from src.export.dashboard_data import _series_openmeteo_por_municipio

    agora = pd.Timestamp.now(tz="UTC").floor("h")
    horas = pd.date_range(agora - pd.Timedelta(hours=23), periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]

    def _resposta_para(n_pontos: int) -> list[dict]:
        return [
            {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 24}}
            for _ in range(n_pontos)
        ]

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_para(2), status=200)
        series = _series_openmeteo_por_municipio(
            setores, municipios_dias_completos=set(), agora=agora,
        )

    assert len(rsps.calls) == 1
    assert set(series.keys()) == {"CIDADE A", "CIDADE B"}


def test_series_openmeteo_por_municipio_sem_filtro_mantem_comportamento_antigo(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL
    from src.export.dashboard_data import _series_openmeteo_por_municipio, JANELA_SERIE_DIAS

    agora = pd.Timestamp.now(tz="UTC").floor("h")
    horas = pd.date_range(agora - pd.Timedelta(hours=23), periods=24, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]

    corpos_capturados = []

    def _callback(request):
        import json as _json
        corpos_capturados.append(_json.loads(request.body))
        resposta = [
            {"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas_iso, "precipitation": [1.0] * 24}}
            for _ in range(len(_json.loads(request.body)["latitude"]))
        ]
        return (200, {}, _json.dumps(resposta))

    with responses.RequestsMock() as rsps:
        rsps.add_callback(responses.POST, FORECAST_URL, callback=_callback)
        series = _series_openmeteo_por_municipio(setores, agora=agora)

    assert len(corpos_capturados) == 1
    assert corpos_capturados[0]["past_days"] == JANELA_SERIE_DIAS
    assert set(series.keys()) == {"CIDADE A", "CIDADE B"}
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k series_openmeteo_por_municipio -v`
Expected: FAIL (`TypeError`: `_series_openmeteo_por_municipio` ainda não
aceita `municipios_dias_completos`).

- [ ] **Step 3: Implementar a divisão em grupos**

Substituir a função `_series_openmeteo_por_municipio` inteira em
`src/export/dashboard_data.py`:

```python
def _series_openmeteo_por_municipio(
    setores: gpd.GeoDataFrame,
    municipios_dias_completos: set[str] | None = None,
    agora: pd.Timestamp | None = None,
    cache: CacheOpenMeteo | None = None,
) -> dict:
    """Um ponto por município (média dos centroides dos setores daquele município).

    `municipios_dias_completos`, se informado, restringe quais municípios
    pedem `JANELA_SERIE_DIAS` (30) dias de histórico; os demais pedem só
    `DIAS_HISTORICO_CRUZAMENTO` (4) -- ver
    docs/superpowers/specs/2026-08-23-triagem-chuva-serie-municipio-design.md.
    `None` (padrão) mantém o comportamento anterior: todos pedem 30 dias.
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    municipios, pontos = centroides_municipio(setores)

    if municipios_dias_completos is None:
        grupos = [(municipios, pontos, JANELA_SERIE_DIAS)]
    else:
        completos_idx = [i for i, m in enumerate(municipios) if m in municipios_dias_completos]
        reduzidos_idx = [i for i, m in enumerate(municipios) if m not in municipios_dias_completos]
        grupos = []
        if completos_idx:
            grupos.append((
                [municipios[i] for i in completos_idx],
                [pontos[i] for i in completos_idx],
                JANELA_SERIE_DIAS,
            ))
        if reduzidos_idx:
            grupos.append((
                [municipios[i] for i in reduzidos_idx],
                [pontos[i] for i in reduzidos_idx],
                DIAS_HISTORICO_CRUZAMENTO,
            ))

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
                "serie": [
                    [ts.isoformat(), (None if pd.isna(mm) else round(float(mm), 2))]
                    for ts, mm in zip(recente["data_hora"], recente["chuva_mm"])
                ],
            }
    return series
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k series_openmeteo_por_municipio -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Rodar a suíte inteira (checar regressão nos testes e2e existentes)**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -v`
Expected: PASS em todos -- os testes e2e existentes usam chuva constante de
1.0mm/h (pico de 72h ≈ 72mm, abaixo do limiar de 100mm), então os dois
municípios da fixture caem no mesmo grupo (reduzido) e continuam gerando
exatamente 1 chamada de lote para a série por município, como antes.

- [ ] **Step 6: Commit**

```bash
git add src/export/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat(dashboard_data): dividir busca de série por município em dois grupos por dias_historico"
```

---

### Task 3: Ligar a triagem em `_exportar_openmeteo`

**Files:**
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `_municipios_com_chuva_relevante` (Task 1),
  `_series_openmeteo_por_municipio` com `municipios_dias_completos` (Task 2).
- Produces: `_exportar_openmeteo` sem mudança de assinatura externa (mesmo
  `(cruzado, series, previsao, meta)`), mas agora repassando a triagem
  internamente.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_dashboard_data.py` -- fixture com dois municípios,
um recebendo chuva prevista forte (> 100mm/72h) e outro fraca, confirmando
que a exportação fim-a-fim faz 3 chamadas (setores + 2 grupos de município)
com os `past_days` esperados:

```python
def test_exportar_dashboard_openmeteo_triagem_municipio_por_chuva_prevista(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL
    from src.export.dashboard_data import JANELA_SERIE_DIAS, DIAS_HISTORICO_CRUZAMENTO

    salvar_setores(setores, caminho_setores("SP", tmp_path))

    agora = pd.Timestamp.now(tz="UTC").floor("h")
    # S1 (CIDADE A) recebe uma janela com chuva forte o bastante pra passar
    # de 100mm/72h; S2 (CIDADE B) fica bem abaixo.
    horas_forte = pd.date_range(agora - pd.Timedelta(hours=47), periods=48, freq="h", tz="UTC")
    horas_forte_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas_forte]
    horas_fraca = horas_forte_iso

    corpos_capturados = []

    def _callback(request):
        import json as _json
        corpo = _json.loads(request.body)
        corpos_capturados.append(corpo)
        lats = corpo["latitude"]
        lons = corpo["longitude"]
        # Setor/ponto de CIDADE A fica perto de -23.5,-46.6; CIDADE B perto
        # de -24.0,-47.0 (ver fixture `setores`).
        resposta = []
        for lat, lon in zip(lats, lons):
            forte = abs(lat - (-23.5)) < 0.5 and abs(lon - (-46.6)) < 0.5
            valores = [5.0] * len(horas_forte_iso) if forte else [0.1] * len(horas_fraca)
            resposta.append({
                "latitude": lat, "longitude": lon,
                "hourly": {"time": horas_forte_iso, "precipitation": valores},
            })
        return (200, {}, _json.dumps(resposta))

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        rsps.add_callback(responses.POST, FORECAST_URL, callback=_callback)  # setores
        rsps.add_callback(responses.POST, FORECAST_URL, callback=_callback)  # município (completo)
        rsps.add_callback(responses.POST, FORECAST_URL, callback=_callback)  # município (reduzido)
        meta = exportar_dashboard("SP", 2026, tmp_path, saida, fonte="openmeteo")

    assert len(corpos_capturados) == 3
    # A 1a chamada é sempre a de setores (dias_historico=DIAS_HISTORICO_CRUZAMENTO).
    assert corpos_capturados[0]["past_days"] == DIAS_HISTORICO_CRUZAMENTO
    past_days_municipio = sorted(c["past_days"] for c in corpos_capturados[1:])
    assert past_days_municipio == sorted([JANELA_SERIE_DIAS, DIAS_HISTORICO_CRUZAMENTO])
    assert meta["total_municipios"] == 2
```

`exportar_dashboard` não aceita `agora` (usa o relógio real internamente,
mesmo padrão dos testes e2e existentes como
`test_exportar_dashboard_fonte_openmeteo_fim_a_fim`) -- por isso `agora` só
é usado aqui para montar a janela de horas do mock, capturado no início do
teste com `pd.Timestamp.now(tz="UTC").floor("h")`, sem passá-lo para
`exportar_dashboard`.

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k triagem_municipio -v`
Expected: FAIL (hoje `_exportar_openmeteo` sempre pede `JANELA_SERIE_DIAS`
para todos os municípios, então as 3 chamadas não vão bater com os
`past_days` esperados -- provavelmente só 2 chamadas no total, ambas com o
mesmo `past_days` para município).

- [ ] **Step 3: Ligar a triagem em `_exportar_openmeteo`**

Em `src/export/dashboard_data.py`, dentro de `_exportar_openmeteo`, trocar:

```python
        cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), pontos=pontos, cache=cache)
        series = _series_openmeteo_por_municipio(setores, cache=cache)
```

por:

```python
        cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), pontos=pontos, cache=cache)
        municipios_dias_completos = _municipios_com_chuva_relevante(setores, previsao)
        series = _series_openmeteo_por_municipio(
            setores, municipios_dias_completos=municipios_dias_completos, cache=cache,
        )
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k triagem_municipio -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte inteira do projeto**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS em todos os testes (nenhuma regressão).

- [ ] **Step 6: Commit**

```bash
git add src/export/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat(dashboard_data): ligar triagem por chuva prevista na exportação openmeteo"
```
