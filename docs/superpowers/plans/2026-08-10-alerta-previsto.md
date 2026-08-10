# Alerta previsto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Usar a previsão de chuva da Open-Meteo pra sinalizar, com antecedência de até 3 dias, quais setores ainda não estão em atenção hoje mas devem cruzar o limiar de 72h segundo a previsão — trajetória de janela móvel (passado + futuro), não um número único.

**Architecture:** O cliente Open-Meteo ganha um parâmetro de dias de previsão; a mesma consulta já feita por setor (sem uma segunda chamada à API) alimenta tanto o acumulado observado de sempre quanto uma nova trajetória futura, reaproveitando `_chuva_acumulada` já existente. A trajetória é exportada num arquivo `previsao_<uf>.json` separado, consumido pelo frontend só quando `fonte=openmeteo`.

**Tech Stack:** Python (pandas), JS puro (mesmo padrão do resto do dashboard), pytest + `responses`.

## Global Constraints

- Só funciona com `fonte="openmeteo"` — `fonte="inmet"` nunca gera `previsao_<uf>.json`.
- Trajetória: passos de 3h, horizonte de 72h à frente (25 pontos: 0h, 3h, ..., 72h), reaproveitando `_chuva_acumulada` já existente em `src/processing/cruzamento.py` — sem duplicar a lógica de acumulado.
- Nenhuma segunda chamada à API por causa da previsão — a mesma série já buscada pra chuva observada por setor alimenta a trajetória.
- `dias_previsao` no cliente Open-Meteo tem padrão `1` (preserva o comportamento atual de todo mundo que já chama `fetch_precipitacao_batch` sem esse argumento); só a consulta por setor passa `dias_previsao=3` explicitamente.

---

### Task 1: Backend — trajetória e exportação

**Files:**
- Modify: `src/ingest/openmeteo.py`
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_openmeteo.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Produces: `fetch_precipitacao_batch(..., dias_previsao=1)` (parâmetro novo); `_trajetoria_chuva_72h(serie, agora, passo_horas=3, horizonte_horas=72) -> list[list]`; `_calcular_chuva_openmeteo(...) -> tuple[gpd.GeoDataFrame, dict]` (mudou de retornar só o GeoDataFrame pra retornar uma tupla — Task 2/frontend não é afetado por isso, só consome o arquivo `previsao_<uf>.json` já pronto). `exportar_dashboard` grava `previsao_<uf>.json` quando `fonte="openmeteo"`.

- [ ] **Step 1: Adicionar `dias_previsao` em `_post_lote` e `fetch_precipitacao_batch`**

Em `src/ingest/openmeteo.py`, trocar a assinatura e o corpo de `_post_lote`:

```python
def _post_lote(
    pontos: list[tuple[float, float]],
    dias_historico: int,
    dias_previsao: int,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
    session: requests.Session,
) -> list[dict]:
    """Um único POST para um lote de pontos. Retorna a lista de objetos da resposta (um por ponto)."""
    corpo = {
        "latitude": [lat for lat, _ in pontos],
        "longitude": [lon for _, lon in pontos],
        "hourly": ["precipitation"],
        "past_days": dias_historico,
        "forecast_days": dias_previsao,
    }
```

(o resto do corpo da função não muda). E trocar a assinatura e a chamada interna de `fetch_precipitacao_batch`:

```python
def fetch_precipitacao_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 30,
    dias_previsao: int = 1,
    timeout: float = 60.0,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    pausa_entre_lotes: float = PAUSA_ENTRE_LOTES_PADRAO,
) -> list[pd.DataFrame]:
    """Busca chuva horária para uma lista de pontos `(lat, lon)`.

    Retorna uma lista de DataFrames (`data_hora, chuva_mm`), um por ponto, na
    mesma ordem de `pontos`. `dias_historico` controla quantos dias para trás
    são pedidos e `dias_previsao` quantos dias de previsão para frente (a
    API aceita até 92 e 16 respectivamente) — filtrar por "é passado" ou
    "é futuro" é responsabilidade de quem consome o DataFrame, não deste
    cliente.

    Internamente, `pontos` é dividido em lotes de `tamanho_lote` (padrão 100,
    ver docstring do módulo sobre o limite prático da API), com uma pausa de
    `pausa_entre_lotes` segundos entre as chamadas.
    """
    if not pontos:
        return []

    sess = session or requests.Session()
    dados: list[dict] = []
    for inicio in range(0, len(pontos), tamanho_lote):
        lote = pontos[inicio:inicio + tamanho_lote]
        dados.extend(
            _post_lote(lote, dias_historico, dias_previsao, timeout, max_retries, backoff_factor, sess)
        )
        if inicio + tamanho_lote < len(pontos):
            time.sleep(pausa_entre_lotes)
```

(o resto da função — o loop que monta os DataFrames a partir de `dados` — não muda.)

- [ ] **Step 2: Testar o `dias_previsao` novo em `tests/test_openmeteo.py`**

Adicionar ao final do arquivo:

```python
@responses.activate
def test_fetch_precipitacao_batch_usa_dias_previsao_no_corpo():
    import json as json_module

    resposta = _resposta(["2026-08-10T00:00"], [[1.0]])
    responses.add(responses.POST, FORECAST_URL, json=resposta, status=200)

    fetch_precipitacao_batch([(-23.5, -46.6)], dias_previsao=3)

    corpo_enviado = json_module.loads(responses.calls[0].request.body)
    assert corpo_enviado["forecast_days"] == 3
```

Run: `pytest tests/test_openmeteo.py -v`
Expected: 6 passed (5 existentes + 1 novo), 0 falhas.

- [ ] **Step 3: Adicionar constantes e `_trajetoria_chuva_72h` em `src/export/dashboard_data.py`**

Trocar o import de `src.processing.cruzamento` (já existe, só confirma que segue igual):

```python
from src.processing.cruzamento import CRS_METRICO, _chuva_acumulada, calcular_cruzamento
```

Adicionar as constantes logo depois de `DIAS_HISTORICO_CRUZAMENTO`:

```python
# Horizonte da previsão de "alerta previsto": até 3 dias (72h) à frente,
# amostrado de 3 em 3 horas — depois desse prazo a previsão de chuva fica
# pouco confiável pra esse tipo de sinalização antecipada.
DIAS_PREVISAO_ALERTA = 3
PASSO_PREVISAO_HORAS = 3
HORIZONTE_PREVISAO_HORAS = 72
```

Adicionar `_trajetoria_chuva_72h` logo depois de `_recortar_series` (antes de `_calcular_chuva_openmeteo`):

```python
def _trajetoria_chuva_72h(
    serie: pd.DataFrame,
    agora: pd.Timestamp,
    passo_horas: int = PASSO_PREVISAO_HORAS,
    horizonte_horas: int = HORIZONTE_PREVISAO_HORAS,
) -> list:
    """Acumulado de 72h em cada ponto futuro, combinando chuva já caída + prevista.

    Reaproveita `_chuva_acumulada` (mesma função usada pro acumulado
    observado) chamada em cada ponto futuro `t` — ela soma `chuva_mm` na
    janela `(t - 72h, t]` independente de os pontos serem passados ou
    futuros, já que a série da Open-Meteo já vem contínua (observado +
    previsto misturados na mesma sequência de `data_hora`).

    Retorna `[[timestamp_iso, mm_acumulado_previsto], ...]`, do ponto
    `agora` até `agora + horizonte_horas` em passos de `passo_horas`
    (25 pontos com os valores padrão: 0h, 3h, ..., 72h).
    """
    pontos = []
    passo = pd.Timedelta(hours=passo_horas)
    limite = agora + pd.Timedelta(hours=horizonte_horas)
    t = agora
    while t <= limite:
        valor = _chuva_acumulada(serie, t, 72)
        pontos.append([t.isoformat(), None if pd.isna(valor) else round(float(valor), 2)])
        t += passo
    return pontos
```

- [ ] **Step 4: Atualizar `_calcular_chuva_openmeteo` pra retornar também a previsão**

Substituir a função inteira por:

```python
def _calcular_chuva_openmeteo(
    setores: gpd.GeoDataFrame,
    janelas: tuple[int, ...] = (24, 72),
    dias_historico: int = DIAS_HISTORICO_CRUZAMENTO,
    dias_previsao: int = DIAS_PREVISAO_ALERTA,
    agora: pd.Timestamp | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Consulta a Open-Meteo direto no centroide de cada setor e calcula a chuva acumulada.

    Sem estação: `distancia_km` é sempre 0.0; `codigo_estacao`/`nome_estacao`
    identificam a fonte, não uma estação real. `agora` é parametrizável para
    tornar testes determinísticos — em produção usa o instante atual.

    Retorna `(resultado, previsao)`: `resultado` é o GeoDataFrame de sempre
    (chuva observada em `janelas`); `previsao` é
    `{num_setor: [[iso, mm], ...]}` — a trajetória do acumulado de 72h nas
    próximas horas (ver `_trajetoria_chuva_72h`), calculada a partir da
    mesma série já buscada — sem uma segunda consulta à API.
    """
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")

    centroides_4326 = setores.to_crs(CRS_METRICO).geometry.centroid.to_crs("EPSG:4326")
    pontos = [(pt.y, pt.x) for pt in centroides_4326]

    series = fetch_precipitacao_batch(pontos, dias_historico=dias_historico, dias_previsao=dias_previsao)

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

    previsao = {
        num_setor: _trajetoria_chuva_72h(serie, agora)
        for num_setor, serie in zip(setores["num_setor"], series)
    }

    resultado.attrs["referencia"] = referencia
    return resultado, previsao
```

- [ ] **Step 5: Atualizar `exportar_dashboard` pra gravar `previsao_<uf>.json`**

Trocar o corpo da função (a partir de `if fonte == "openmeteo":`) por:

```python
    previsao = None

    if fonte == "openmeteo":
        try:
            cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72))
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
            "horizonte_previsao_horas": HORIZONTE_PREVISAO_HORAS,
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
    if previsao is not None:
        (saida_dir / f"previsao_{uf_norm.lower()}.json").write_text(
            json.dumps(previsao, ensure_ascii=False, indent=2)
        )
    (saida_dir / f"meta_{uf_norm.lower()}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )

    logger.info("Exportados dados do dashboard (fonte=%s) para %s: %s", fonte, uf_norm, meta)
    return meta
```

- [ ] **Step 6: Atualizar as chamadas existentes de `_calcular_chuva_openmeteo` em `tests/test_dashboard_data.py`**

No teste `test_calcular_chuva_openmeteo_consulta_centroide_e_acumula`, trocar:

```python
        resultado = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora)
```

Por:

```python
        resultado, _ = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora)
```

(o resto do teste não muda — ele só verifica `resultado`.)

- [ ] **Step 7: Adicionar os testes novos em `tests/test_dashboard_data.py`**

Atualizar o import no topo do arquivo:

```python
from src.export.dashboard_data import (
    ExportacaoDashboardError,
    _calcular_chuva_openmeteo,
    _trajetoria_chuva_72h,
    exportar_dashboard,
)
```

Adicionar ao final do arquivo:

```python
def test_trajetoria_chuva_72h_encontra_cruzamento_futuro():
    agora = pd.Timestamp("2026-08-10 00:00", tz="UTC")
    horas_passado = pd.date_range(agora - pd.Timedelta(hours=71), agora, freq="h", tz="UTC")
    horas_futuro = pd.date_range(agora + pd.Timedelta(hours=1), agora + pd.Timedelta(hours=72), freq="h", tz="UTC")
    serie = pd.DataFrame({
        "data_hora": list(horas_passado) + list(horas_futuro),
        "chuva_mm": [0.0] * len(horas_passado) + [5.0] * len(horas_futuro),
    })

    trajetoria = _trajetoria_chuva_72h(serie, agora, passo_horas=3, horizonte_horas=72)

    assert len(trajetoria) == 25
    assert trajetoria[0][0] == agora.isoformat()
    assert trajetoria[0][1] == pytest.approx(0.0)
    assert trajetoria[-1][1] > 100


def test_calcular_chuva_openmeteo_retorna_previsao_por_setor(tmp_path: Path, setores):
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
        _, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora)

    assert set(previsao.keys()) == {"S1", "S2"}
    assert previsao["S1"][0][0] == agora.isoformat()
    assert len(previsao["S1"]) == 25


def test_exportar_dashboard_fonte_openmeteo_gera_previsao(tmp_path: Path, setores):
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

    assert "horizonte_previsao_horas" in meta
    previsao_path = saida / "previsao_sp.json"
    assert previsao_path.exists()
    previsao = json.loads(previsao_path.read_text())
    assert set(previsao.keys()) == {"S1", "S2"}


def test_exportar_dashboard_fonte_inmet_nao_gera_previsao(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva = _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {0: 1.0}, "2026-08-01 00:00")
    salvar_chuva(chuva, caminho_chuva("SP", 2026, tmp_path))

    saida = tmp_path / "export"
    exportar_dashboard("SP", 2026, tmp_path, saida, fonte="inmet")

    assert not (saida / "previsao_sp.json").exists()
```

- [ ] **Step 8: Rodar os testes novos**

Run: `pytest tests/test_dashboard_data.py tests/test_openmeteo.py -v`
Expected: 18 passed (8 já existentes em test_dashboard_data + 4 novos + 6 já existentes em test_openmeteo + 1 novo — 12+6=18), 0 falhas.

- [ ] **Step 9: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 69 passed (64 antes deste plano + 5 novos: 1 em test_openmeteo, 4 em test_dashboard_data), 0 falhas.

- [ ] **Step 10: Commit**

```bash
git add src/ingest/openmeteo.py src/export/dashboard_data.py tests/test_openmeteo.py tests/test_dashboard_data.py
git commit -m "feat(export): compute forecast-based rolling 72h trajectory per setor"
```

---

### Task 2: Frontend — alerta previsto

**Files:**
- Modify: `docs/dashboard/index.html`

**Interfaces:**
- Consumes: `data/previsao_<uf>.json` (Task 1) — `{num_setor: [[iso, mm], ...]}`.

- [ ] **Step 1: Buscar `previsao_<uf>.json` de forma não-crítica**

Trocar o início de `carregarDados()`:

```javascript
  async function carregarDados() {
    const [setoresResp, seriesResp, metaResp] = await Promise.all([
      fetch(`data/setores_${UF}.geojson`),
      fetch(`data/series_${UF}.json`),
      fetch(`data/meta_${UF}.json`),
    ]);
    if (!setoresResp.ok || !seriesResp.ok || !metaResp.ok) {
      document.getElementById("selo").textContent =
        "Não foi possível carregar os dados. Rode `python -m src.cli exportar-dashboard --uf SP` primeiro.";
      return;
    }
    setoresGeoJSON = await setoresResp.json();
    series = await seriesResp.json();
    const meta = await metaResp.json();
```

Por:

```javascript
  async function carregarDados() {
    const [setoresResp, seriesResp, metaResp] = await Promise.all([
      fetch(`data/setores_${UF}.geojson`),
      fetch(`data/series_${UF}.json`),
      fetch(`data/meta_${UF}.json`),
    ]);
    if (!setoresResp.ok || !seriesResp.ok || !metaResp.ok) {
      document.getElementById("selo").textContent =
        "Não foi possível carregar os dados. Rode `python -m src.cli exportar-dashboard --uf SP` primeiro.";
      return;
    }
    setoresGeoJSON = await setoresResp.json();
    series = await seriesResp.json();
    const meta = await metaResp.json();

    try {
      const previsaoResp = await fetch(`data/previsao_${UF}.json`);
      previsao = previsaoResp.ok ? await previsaoResp.json() : null;
    } catch (e) {
      previsao = null;
    }
```

- [ ] **Step 2: Declarar a variável `previsao` no estado do módulo**

Trocar:

```javascript
  const estado = { janela: 72, limiar: 100, municipio: "" };
  let setoresGeoJSON = null;
  let series = {};
  let camadaSetores = null;
  let mapa = null;
  let grafico = null;
```

Por:

```javascript
  const estado = { janela: 72, limiar: 100, municipio: "" };
  let setoresGeoJSON = null;
  let series = {};
  let previsao = null;
  let camadaSetores = null;
  let mapa = null;
  let grafico = null;
```

- [ ] **Step 3: Calcular `alertaPrevisto` em `renderizarTudo`**

Trocar:

```javascript
  function renderizarTudo() {
    const filtrados = setoresFiltrados();
    const emAtencao = filtrados.filter(r => typeof r.chuva === "number" && r.chuva >= estado.limiar);

    renderizarCards(filtrados, emAtencao);
    renderizarMapa(filtrados, emAtencao);
    renderizarTabela(emAtencao);
  }
```

Por:

```javascript
  function primeiroPontoQueCruza(trajetoria, limiar) {
    if (!trajetoria) return null;
    for (const [iso, mm] of trajetoria) {
      if (typeof mm === "number" && mm >= limiar) return iso;
    }
    return null;
  }

  function calcularAlertaPrevisto(filtrados, emAtencao) {
    if (!previsao) return [];
    const jaEmAtencao = new Set(emAtencao.map(r => r.f.properties.num_setor));
    const previsto = [];
    for (const r of filtrados) {
      const numSetor = r.f.properties.num_setor;
      if (jaEmAtencao.has(numSetor)) continue;
      const quando = primeiroPontoQueCruza(previsao[numSetor], estado.limiar);
      if (quando) previsto.push({ f: r.f, quando });
    }
    previsto.sort((a, b) => a.quando.localeCompare(b.quando));
    return previsto;
  }

  function renderizarTudo() {
    const filtrados = setoresFiltrados();
    const emAtencao = filtrados.filter(r => typeof r.chuva === "number" && r.chuva >= estado.limiar);
    const alertaPrevisto = calcularAlertaPrevisto(filtrados, emAtencao);

    renderizarCards(filtrados, emAtencao, alertaPrevisto);
    renderizarMapa(filtrados, emAtencao, alertaPrevisto);
    renderizarTabela(emAtencao, alertaPrevisto);
  }
```

- [ ] **Step 4: Mostrar a contagem de alerta previsto nos cards**

Trocar:

```javascript
  function renderizarCards(filtrados, emAtencao) {
    const grauAlto = filtrados.filter(r => (r.f.properties.grau_risco || "").toLowerCase() === "alto").length;
    const grauMuitoAlto = filtrados.filter(r => (r.f.properties.grau_risco || "").toLowerCase() === "muito alto").length;
    const cards = [
      { rotulo: "Setores no recorte", valor: filtrados.length },
      { rotulo: "Grau alto", valor: grauAlto },
      { rotulo: "Grau muito alto", valor: grauMuitoAlto },
      { rotulo: `Em atenção (≥ ${estado.limiar}mm)`, valor: emAtencao.length },
    ];
    document.getElementById("cards").innerHTML = cards.map(c =>
      `<div class="card"><div class="rotulo">${c.rotulo}</div><div class="valor">${c.valor}</div></div>`
    ).join("");
  }
```

Por:

```javascript
  function renderizarCards(filtrados, emAtencao, alertaPrevisto) {
    const grauAlto = filtrados.filter(r => (r.f.properties.grau_risco || "").toLowerCase() === "alto").length;
    const grauMuitoAlto = filtrados.filter(r => (r.f.properties.grau_risco || "").toLowerCase() === "muito alto").length;
    const cards = [
      { rotulo: "Setores no recorte", valor: filtrados.length },
      { rotulo: "Grau alto", valor: grauAlto },
      { rotulo: "Grau muito alto", valor: grauMuitoAlto },
      { rotulo: `Em atenção (≥ ${estado.limiar}mm)`, valor: emAtencao.length },
    ];
    if (previsao) {
      cards.push({ rotulo: "Alerta previsto (72h)", valor: alertaPrevisto.length });
    }
    document.getElementById("cards").innerHTML = cards.map(c =>
      `<div class="card"><div class="rotulo">${c.rotulo}</div><div class="valor">${c.valor}</div></div>`
    ).join("");
  }
```

- [ ] **Step 5: Contorno tracejado no mapa pros setores com alerta previsto**

Trocar:

```javascript
  function renderizarMapa(filtrados, emAtencao) {
    const codigosAtencao = new Set(emAtencao.map(r => r.f.properties.num_setor));
    const colecao = { type: "FeatureCollection", features: filtrados.map(r => r.f) };

    if (camadaSetores) mapa.removeLayer(camadaSetores);
    camadaSetores = L.geoJSON(colecao, {
      style: feature => {
        const emAtencaoAgora = codigosAtencao.has(feature.properties.num_setor);
        const cor = corPorGrau(feature.properties.grau_risco);
        return {
          fillColor: cor, fillOpacity: 0.75,
          color: emAtencaoAgora ? COR_ATENCAO : cor,
          weight: emAtencaoAgora ? 3 : 1,
        };
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        const campo = estado.janela === 24 ? "chuva_24h" : "chuva_72h";
        const chuva = typeof p[campo] === "number" ? p[campo].toFixed(1) : "—";
        const linhaFonte = p.fonte_estacao === "openmeteo"
          ? `Fonte: ${(p.fonte_estacao || "—").toUpperCase()}<br>`
          : `Estação a ${p.distancia_km != null ? p.distancia_km.toFixed(2) : "—"}km ` +
            `(${(p.fonte_estacao || "—").toUpperCase()})<br>`;
        layer.bindTooltip(
          `<b>${p.munic}</b><br>Setor: ${p.num_setor}<br>Grau: ${p.grau_risco}<br>` +
          linhaFonte +
          `Chuva ${estado.janela}h: ${chuva}mm`
        );
      },
    }).addTo(mapa);

    if (filtrados.length) mapa.fitBounds(camadaSetores.getBounds(), { padding: [20, 20] });
  }
```

Por:

```javascript
  function renderizarMapa(filtrados, emAtencao, alertaPrevisto) {
    const codigosAtencao = new Set(emAtencao.map(r => r.f.properties.num_setor));
    const codigosPrevisto = new Set(alertaPrevisto.map(r => r.f.properties.num_setor));
    const quandoPorSetor = new Map(alertaPrevisto.map(r => [r.f.properties.num_setor, r.quando]));
    const colecao = { type: "FeatureCollection", features: filtrados.map(r => r.f) };

    if (camadaSetores) mapa.removeLayer(camadaSetores);
    camadaSetores = L.geoJSON(colecao, {
      style: feature => {
        const numSetor = feature.properties.num_setor;
        const emAtencaoAgora = codigosAtencao.has(numSetor);
        const previstoAgora = codigosPrevisto.has(numSetor);
        const cor = corPorGrau(feature.properties.grau_risco);
        return {
          fillColor: cor, fillOpacity: 0.75,
          color: emAtencaoAgora ? COR_ATENCAO : cor,
          weight: emAtencaoAgora || previstoAgora ? 3 : 1,
          dashArray: previstoAgora && !emAtencaoAgora ? "6 4" : null,
        };
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        const campo = estado.janela === 24 ? "chuva_24h" : "chuva_72h";
        const chuva = typeof p[campo] === "number" ? p[campo].toFixed(1) : "—";
        const linhaFonte = p.fonte_estacao === "openmeteo"
          ? `Fonte: ${(p.fonte_estacao || "—").toUpperCase()}<br>`
          : `Estação a ${p.distancia_km != null ? p.distancia_km.toFixed(2) : "—"}km ` +
            `(${(p.fonte_estacao || "—").toUpperCase()})<br>`;
        const quando = quandoPorSetor.get(p.num_setor);
        const linhaPrevisao = quando ? `<br><b>Alerta previsto:</b> ${formatarData(quando)}` : "";
        layer.bindTooltip(
          `<b>${p.munic}</b><br>Setor: ${p.num_setor}<br>Grau: ${p.grau_risco}<br>` +
          linhaFonte +
          `Chuva ${estado.janela}h: ${chuva}mm` +
          linhaPrevisao
        );
      },
    }).addTo(mapa);

    if (filtrados.length) mapa.fitBounds(camadaSetores.getBounds(), { padding: [20, 20] });
  }
```

- [ ] **Step 6: Atualizar a legenda do mapa**

Trocar, dentro de `inicializarMapa`:

```javascript
      div.innerHTML =
        '<b>Grau de risco</b><br>' +
        '<span class="amostra" style="background:' + CORES_GRAU["alto"] + '"></span>Alto<br>' +
        '<span class="amostra" style="background:' + CORES_GRAU["muito alto"] + '"></span>Muito alto<br>' +
        '<span style="border:2px solid ' + COR_ATENCAO + ';padding:0 4px">Em atenção</span>';
```

Por:

```javascript
      div.innerHTML =
        '<b>Grau de risco</b><br>' +
        '<span class="amostra" style="background:' + CORES_GRAU["alto"] + '"></span>Alto<br>' +
        '<span class="amostra" style="background:' + CORES_GRAU["muito alto"] + '"></span>Muito alto<br>' +
        '<span style="border:2px solid ' + COR_ATENCAO + ';padding:0 4px">Em atenção</span><br>' +
        '<span style="border:2px dashed ' + COR_ATENCAO + ';padding:0 4px">Alerta previsto</span>';
```

- [ ] **Step 7: Adicionar a seção "Alerta previsto" na tabela (HTML)**

Trocar o bloco da tabela dentro de `<div class="painel-inferior">`:

```html
    <div>
      <h2 id="tituloTabela">Setores em atenção</h2>
      <div class="tabela-scroll">
        <table>
          <thead>
            <tr><th>Município</th><th>Setor</th><th>Grau</th><th>Chuva (mm)</th><th>Fonte</th></tr>
          </thead>
          <tbody id="tabelaCorpo"></tbody>
        </table>
        <div class="vazio" id="tabelaVazia" hidden>Nenhum setor ultrapassa o limiar configurado.</div>
      </div>
    </div>
```

Por:

```html
    <div>
      <h2 id="tituloTabela">Setores em atenção</h2>
      <div class="tabela-scroll">
        <table>
          <thead>
            <tr><th>Município</th><th>Setor</th><th>Grau</th><th>Chuva (mm)</th><th>Fonte</th></tr>
          </thead>
          <tbody id="tabelaCorpo"></tbody>
        </table>
        <div class="vazio" id="tabelaVazia" hidden>Nenhum setor ultrapassa o limiar configurado.</div>
      </div>

      <div id="blocoAlertaPrevisto" hidden style="margin-top: var(--space-6)">
        <h2>Alerta previsto (próximos 3 dias)</h2>
        <div class="tabela-scroll">
          <table>
            <thead>
              <tr><th>Município</th><th>Setor</th><th>Grau</th><th>Quando</th></tr>
            </thead>
            <tbody id="tabelaPrevistoCorpo"></tbody>
          </table>
        </div>
      </div>
    </div>
```

- [ ] **Step 8: Renderizar a tabela de alerta previsto (JS)**

Trocar:

```javascript
  function renderizarTabela(emAtencao) {
    const campo = estado.janela === 24 ? "chuva_24h" : "chuva_72h";
    const ordenado = emAtencao.slice().sort((a, b) => (b.chuva || 0) - (a.chuva || 0));
    const corpo = document.getElementById("tabelaCorpo");
    const vazio = document.getElementById("tabelaVazia");

    if (!ordenado.length) {
      corpo.innerHTML = "";
      vazio.hidden = false;
      return;
    }
    vazio.hidden = true;
    corpo.innerHTML = ordenado.map(r => {
      const p = r.f.properties;
      return `<tr><td>${p.munic}</td><td>${p.num_setor}</td><td>${p.grau_risco}</td>` +
        `<td>${(p[campo] || 0).toFixed(1)}</td><td>${(p.fonte_estacao || "—").toUpperCase()}</td></tr>`;
    }).join("");
  }
```

Por:

```javascript
  function renderizarTabela(emAtencao, alertaPrevisto) {
    const campo = estado.janela === 24 ? "chuva_24h" : "chuva_72h";
    const ordenado = emAtencao.slice().sort((a, b) => (b.chuva || 0) - (a.chuva || 0));
    const corpo = document.getElementById("tabelaCorpo");
    const vazio = document.getElementById("tabelaVazia");

    if (!ordenado.length) {
      corpo.innerHTML = "";
      vazio.hidden = false;
    } else {
      vazio.hidden = true;
      corpo.innerHTML = ordenado.map(r => {
        const p = r.f.properties;
        return `<tr><td>${p.munic}</td><td>${p.num_setor}</td><td>${p.grau_risco}</td>` +
          `<td>${(p[campo] || 0).toFixed(1)}</td><td>${(p.fonte_estacao || "—").toUpperCase()}</td></tr>`;
      }).join("");
    }

    const blocoPrevisto = document.getElementById("blocoAlertaPrevisto");
    if (!previsao || !alertaPrevisto.length) {
      blocoPrevisto.hidden = true;
      return;
    }
    blocoPrevisto.hidden = false;
    document.getElementById("tabelaPrevistoCorpo").innerHTML = alertaPrevisto.map(r => {
      const p = r.f.properties;
      return `<tr><td>${p.munic}</td><td>${p.num_setor}</td><td>${p.grau_risco}</td>` +
        `<td>${formatarData(r.quando)}</td></tr>`;
    }).join("");
  }
```

- [ ] **Step 9: Verificar manualmente**

Se houver dados locais reais exportados (`docs/dashboard/data/previsao_sp.json` existente), servir com
`python -m http.server 8000 --directory docs` e abrir `http://localhost:8000/dashboard/`.
Expected: se `previsao_sp.json` existir, um card extra "Alerta previsto (72h)" aparece, e — se
algum setor cruzar o limiar futuramente — a seção "Alerta previsto" e o contorno tracejado no mapa
aparecem. Se `previsao_sp.json` não existir (dashboard gerado com `--fonte inmet`), nada muda
visualmente em relação a antes.

- [ ] **Step 10: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 69 passed, 0 falhas (este task não adiciona testes Python — frontend sem framework de
teste no projeto, mesmo padrão dos tasks anteriores de UI).

- [ ] **Step 11: Commit**

```bash
git add docs/dashboard/index.html
git commit -m "feat(dashboard): show predicted-alert sectors from rain forecast"
```

---

## Self-Review Notes

- **Spec coverage:** cliente com `dias_previsao` parametrizável (Task 1); trajetória de janela
  móvel reaproveitando `_chuva_acumulada` (Task 1); arquivo `previsao_<uf>.json` só com
  `fonte=openmeteo` (Task 1); contorno tracejado + seção própria na tabela, ordenada pelo
  cruzamento mais cedo (Task 2). Todos os itens do spec
  (`docs/superpowers/specs/2026-08-10-alerta-previsto-design.md`) têm task correspondente.
- **Placeholder scan:** nenhum "TBD"/"TODO" — todo código está escrito por extenso.
- **Consistência de tipos/assinaturas:** `_trajetoria_chuva_72h`, `_calcular_chuva_openmeteo`
  (nova assinatura de retorno `tuple[gpd.GeoDataFrame, dict]`) definidos e usados de forma
  consistente dentro da Task 1; `previsao` (variável JS) e o formato `[[iso, mm], ...]` usados de
  forma consistente entre Task 1 (produtor) e Task 2 (consumidor).
- **Compatibilidade:** `dias_previsao=1` como padrão em `fetch_precipitacao_batch` preserva o
  comportamento da chamada já existente em `_series_openmeteo_por_municipio` (que não passa esse
  argumento). `_calcular_chuva_openmeteo` mudar de retornar `gdf` para `(gdf, previsao)` é uma
  mudança que quebra a única chamada existente (dentro do próprio `exportar_dashboard`, atualizada
  no mesmo task) e o teste existente (atualizado no Step 6) — não há mais nenhum outro chamador no
  código.
