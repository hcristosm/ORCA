# Cache local incremental para a Open-Meteo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar uma camada de cache SQLite incremental para as 3 séries horárias buscadas na Open-Meteo (chuva por setor, chuva por município, rajada de vento), reduzindo o `dias_historico` efetivamente pedido à API em execuções subsequentes, e persistindo o cache entre execuções efêmeras do CI via o branch `gh-pages`.

**Architecture:** Um módulo novo (`src/storage_cache_openmeteo.py`) expõe uma classe `CacheOpenMeteo` sobre um arquivo SQLite (`(lat, lon, variavel, data_hora) -> valor`). `src/ingest/openmeteo.py` ganha um parâmetro opcional `cache` em `_fetch_variavel_batch`/`fetch_precipitacao_batch`/`fetch_vento_batch`: antes de cada POST, calcula quanto do histórico pedido já está cacheado e encolhe `past_days` de acordo; depois de uma resposta bem-sucedida, grava as horas retornadas no cache; a série devolvida ao chamador é sempre a janela completa pedida, reconstruída mesclando a resposta da API com o que faltava do cache. O parâmetro é opcional e `None` em todo lugar reproduz o comportamento atual exatamente (sem cache) — nenhum teste existente deveria precisar mudar por causa disso. `src/export/nacional.py` e `src/cli.py` constroem uma única instância por execução e a repassam para as 3 séries. O CI baixa o arquivo de cache do `gh-pages` antes de rodar e publica a versão atualizada de volta depois, com `concurrency:` no workflow para impedir duas execuções escrevendo ao mesmo tempo.

**Tech Stack:** Python 3.11+, `sqlite3` (biblioteca padrão), `pandas`, `pytest` + `responses` (já usados no projeto).

**Spec:** `docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md`

## Global Constraints

- `cache=None` (ou parâmetro omitido) em qualquer função tocada precisa reproduzir exatamente o comportamento de hoje — nenhum teste existente pode precisar de alteração por causa deste plano, exceto onde uma assinatura ganha um novo parâmetro opcional com default que preserva o comportamento antigo.
- Falha ao abrir/ler/escrever o arquivo de cache nunca pode derrubar uma exportação: sempre degrada para "cache vazio" com um `logger.warning`, nunca levanta exceção para quem chama.
- Precisão de arredondamento de `lat`/`lon` na chave do cache é fixa (4 casas decimais) e independente do tamanho de célula recalibrado em `src/processing/grade_espacial.py` (ver spec, seção 1).
- A janela "sempre expira" (últimas 3h + toda a previsão) nunca é servida do cache — sempre buscada ao vivo.

---

## Task 1: Módulo de cache (`CacheOpenMeteo`)

**Files:**
- Create: `src/storage_cache_openmeteo.py`
- Test: `tests/test_cache_openmeteo.py`

**Interfaces:**
- Produces: `CacheOpenMeteo(caminho: Path)`, `.horas_faltantes(pontos: list[tuple[float, float]], variavel: str, horas: list[str]) -> dict[tuple[float, float], list[str]]`, `.ler(pontos: list[tuple[float, float]], variavel: str, horas: list[str]) -> dict[tuple[float, float], dict[str, float | None]]`, `.gravar(registros: list[tuple[tuple[float, float], str, float | None]], variavel: str, buscado_em: str) -> None`, `CAMINHO_PADRAO: Path`, `PRECISAO_DECIMAIS: int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cache_openmeteo.py
from pathlib import Path

import pytest

from src.storage.cache_openmeteo import CacheOpenMeteo


def test_horas_faltantes_cache_vazio_retorna_tudo(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00", "2026-08-10T01:00"])
    assert faltando == {(-23.5, -46.6): ["2026-08-10T00:00", "2026-08-10T01:00"]}


def test_gravar_depois_horas_faltantes_reflete_o_que_foi_gravado(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", 1.2)], "chuva_mm", "2026-08-10T05:00")

    faltando = cache.horas_faltantes([ponto], "chuva_mm", ["2026-08-10T00:00", "2026-08-10T01:00"])

    assert faltando == {ponto: ["2026-08-10T01:00"]}


def test_gravar_e_ler_preserva_valor_null(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", None)], "chuva_mm", "2026-08-10T05:00")

    lido = cache.ler([ponto], "chuva_mm", ["2026-08-10T00:00"])

    assert lido == {ponto: {"2026-08-10T00:00": None}}


def test_gravar_upsert_sobrescreve_valor_existente(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")
    cache.gravar([(ponto, "2026-08-10T00:00", 2.0)], "chuva_mm", "2026-08-10T06:00")

    lido = cache.ler([ponto], "chuva_mm", ["2026-08-10T00:00"])

    assert lido == {ponto: {"2026-08-10T00:00": 2.0}}


def test_variaveis_diferentes_nao_se_confundem(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    faltando_vento = cache.horas_faltantes([ponto], "vento_rajada_kmh", ["2026-08-10T00:00"])

    assert faltando_vento == {ponto: ["2026-08-10T00:00"]}


def test_pontos_proximos_arredondam_para_a_mesma_chave(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    cache.gravar([((-23.50001, -46.60001), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00"])

    assert faltando == {}


def test_arquivo_corrompido_degrada_para_cache_vazio(tmp_path: Path, caplog):
    caminho = tmp_path / "cache.sqlite"
    caminho.write_bytes(b"nao e um sqlite valido")

    cache = CacheOpenMeteo(caminho)
    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00"])
    cache.gravar([((-23.5, -46.6), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    assert faltando == {(-23.5, -46.6): ["2026-08-10T00:00"]}


def test_diretorio_pai_e_criado_automaticamente(tmp_path: Path):
    caminho = tmp_path / "subdir" / "cache.sqlite"
    cache = CacheOpenMeteo(caminho)
    cache.gravar([((-23.5, -46.6), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")
    assert caminho.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cache_openmeteo.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'src.storage.cache_openmeteo'`.

- [ ] **Step 3: Write the implementation**

```python
# src/storage_cache_openmeteo.py
"""Cache local incremental para respostas horárias da Open-Meteo.

Ver docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md. Uma tabela
SQLite `(lat, lon, variavel, data_hora) -> valor`: hora passada não muda
mais, então uma vez cacheada nunca precisa ser rebuscada — quem decide o que
ainda é elegível para vir do cache é `src/ingest/openmeteo.py`, não este
módulo (aqui só existe leitura/escrita por chave exata).

Se o arquivo estiver ausente, corrompido ou ilegível, o módulo degrada para
cache vazio (loga um warning, nunca levanta exceção) — o cache nunca pode
derrubar uma exportação.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

PRECISAO_DECIMAIS = 4  # ~11m no equador; fixo e independente da grade
                        # espacial recalibrada por execução (ver spec).
CAMINHO_PADRAO = Path("data/cache/openmeteo.sqlite")

Ponto = tuple[float, float]


def _arredondar(ponto: Ponto) -> Ponto:
    lat, lon = ponto
    return (round(lat, PRECISAO_DECIMAIS), round(lon, PRECISAO_DECIMAIS))


class CacheOpenMeteo:
    """Cache thread-safe (lock próprio) sobre um arquivo SQLite."""

    def __init__(self, caminho: Path = CAMINHO_PADRAO) -> None:
        self._caminho = caminho
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = self._abrir()

    def _abrir(self) -> sqlite3.Connection | None:
        try:
            self._caminho.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._caminho, check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache_horario ("
                "lat REAL NOT NULL, lon REAL NOT NULL, variavel TEXT NOT NULL, "
                "data_hora TEXT NOT NULL, valor REAL, buscado_em TEXT NOT NULL, "
                "PRIMARY KEY (lat, lon, variavel, data_hora))"
            )
            conn.commit()
            return conn
        except sqlite3.Error as exc:
            logger.warning(
                "Falha ao abrir cache Open-Meteo em %s: %s. Operando sem cache.",
                self._caminho, exc,
            )
            return None

    def horas_faltantes(
        self, pontos: list[Ponto], variavel: str, horas: list[str],
    ) -> dict[Ponto, list[str]]:
        """Para cada ponto, quais `horas` (ISO 8601, ex. "2026-08-10T00:00")
        ainda não estão cacheadas para `variavel`."""
        if self._conn is None or not horas:
            return {p: list(horas) for p in pontos} if horas else {}
        placeholders = ",".join("?" * len(horas))
        faltando: dict[Ponto, list[str]] = {}
        with self._lock:
            for ponto in pontos:
                lat, lon = _arredondar(ponto)
                try:
                    cursor = self._conn.execute(
                        f"SELECT data_hora FROM cache_horario WHERE lat = ? AND lon = ? "
                        f"AND variavel = ? AND data_hora IN ({placeholders})",
                        (lat, lon, variavel, *horas),
                    )
                    presentes = {row[0] for row in cursor.fetchall()}
                except sqlite3.Error as exc:
                    logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando ponto como não cacheado.", exc)
                    presentes = set()
                faltantes_ponto = [h for h in horas if h not in presentes]
                if faltantes_ponto:
                    faltando[ponto] = faltantes_ponto
        return faltando

    def ler(
        self, pontos: list[Ponto], variavel: str, horas: list[str],
    ) -> dict[Ponto, dict[str, float | None]]:
        """O que já está cacheado para `pontos`/`variavel`/`horas`."""
        resultado: dict[Ponto, dict[str, float | None]] = {}
        if self._conn is None or not horas:
            return resultado
        placeholders = ",".join("?" * len(horas))
        with self._lock:
            for ponto in pontos:
                lat, lon = _arredondar(ponto)
                try:
                    cursor = self._conn.execute(
                        f"SELECT data_hora, valor FROM cache_horario WHERE lat = ? AND lon = ? "
                        f"AND variavel = ? AND data_hora IN ({placeholders})",
                        (lat, lon, variavel, *horas),
                    )
                    linhas = {row[0]: row[1] for row in cursor.fetchall()}
                except sqlite3.Error as exc:
                    logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando ponto como não cacheado.", exc)
                    linhas = {}
                if linhas:
                    resultado[ponto] = linhas
        return resultado

    def gravar(
        self, registros: list[tuple[Ponto, str, float | None]], variavel: str, buscado_em: str,
    ) -> None:
        """Upsert em lote: cada item é `(ponto, data_hora, valor)`."""
        if self._conn is None or not registros:
            return
        with self._lock:
            try:
                self._conn.executemany(
                    "INSERT INTO cache_horario (lat, lon, variavel, data_hora, valor, buscado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (lat, lon, variavel, data_hora) DO UPDATE SET "
                    "valor = excluded.valor, buscado_em = excluded.buscado_em",
                    [
                        (*_arredondar(ponto), variavel, hora, valor, buscado_em)
                        for ponto, hora, valor in registros
                    ],
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                logger.warning(
                    "Falha ao gravar no cache Open-Meteo: %s. Dado desta execução não foi persistido.", exc,
                )
```

**Nota de estrutura:** `src/storage.py` hoje é um arquivo único, não um pacote — `src/storage_cache_openmeteo.py` fica como arquivo irmão dele (não um subpacote `src/storage/`), para não forçar uma migração de `storage.py` para pacote como efeito colateral deste plano. O import em todos os passos seguintes é `from src.storage_cache_openmeteo import CacheOpenMeteo, CAMINHO_PADRAO`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cache_openmeteo.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/storage_cache_openmeteo.py tests/test_cache_openmeteo.py
git commit -m "feat(cache): módulo de cache SQLite incremental para a Open-Meteo"
```

---

## Task 2: Cálculo de `dias_historico` efetivo em `src/ingest/openmeteo.py`

**Files:**
- Modify: `src/ingest/openmeteo.py`
- Test: `tests/test_openmeteo.py`

**Interfaces:**
- Consumes: `CacheOpenMeteo` (Task 1) — `.horas_faltantes(pontos, variavel, horas) -> dict[Ponto, list[str]]`.
- Produces: `JANELA_SEMPRE_EXPIRA_HORAS: int`, `DIAS_HISTORICO_MINIMO: int`, `_horas_no_intervalo(inicio: pd.Timestamp, fim: pd.Timestamp) -> list[str]`, `_dias_historico_efetivo(pontos: list[tuple[float, float]], variavel: str, dias_historico: int, cache: CacheOpenMeteo | None, agora: pd.Timestamp) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# adicionar em tests/test_openmeteo.py
import pandas as pd

from src.ingest.openmeteo import DIAS_HISTORICO_MINIMO, _dias_historico_efetivo, _horas_no_intervalo
from src.storage_cache_openmeteo import CacheOpenMeteo


def test_horas_no_intervalo_gera_uma_por_hora_exclusive_no_fim():
    inicio = pd.Timestamp("2026-08-10T00:00", tz="UTC")
    fim = pd.Timestamp("2026-08-10T03:00", tz="UTC")
    assert _horas_no_intervalo(inicio, fim) == [
        "2026-08-10T00:00", "2026-08-10T01:00", "2026-08-10T02:00",
    ]


def test_horas_no_intervalo_fim_antes_do_inicio_retorna_vazio():
    inicio = pd.Timestamp("2026-08-10T03:00", tz="UTC")
    fim = pd.Timestamp("2026-08-10T00:00", tz="UTC")
    assert _horas_no_intervalo(inicio, fim) == []


def test_dias_historico_efetivo_sem_cache_retorna_original():
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    resultado = _dias_historico_efetivo([(-23.5, -46.6)], "chuva_mm", 30, None, agora)
    assert resultado == 30


def test_dias_historico_efetivo_cache_vazio_retorna_original(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    resultado = _dias_historico_efetivo([(-23.5, -46.6)], "chuva_mm", 30, cache, agora)
    assert resultado == 30


def test_dias_historico_efetivo_tudo_cacheado_retorna_minimo(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    horas = _horas_no_intervalo(
        agora.floor("h") - pd.Timedelta(days=30),
        agora.floor("h") - pd.Timedelta(hours=3),
    )
    cache.gravar([(ponto, h, 1.0) for h in horas], "chuva_mm", agora.isoformat())

    resultado = _dias_historico_efetivo([ponto], "chuva_mm", 30, cache, agora)

    assert resultado == DIAS_HISTORICO_MINIMO


def test_dias_historico_efetivo_so_ultimo_dia_faltando(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    # Cacheia tudo exceto o último dia antes da janela "sempre expira".
    horas_cacheadas = _horas_no_intervalo(
        agora.floor("h") - pd.Timedelta(days=30),
        agora.floor("h") - pd.Timedelta(days=1),
    )
    cache.gravar([(ponto, h, 1.0) for h in horas_cacheadas], "chuva_mm", agora.isoformat())

    resultado = _dias_historico_efetivo([ponto], "chuva_mm", 30, cache, agora)

    assert resultado <= 2  # só falta ~1 dia + a janela sempre-expira, não os 30 originais
    assert resultado >= DIAS_HISTORICO_MINIMO


def test_dias_historico_efetivo_ponto_nunca_visto_retorna_original(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    resultado = _dias_historico_efetivo([(-23.5, -46.6)], "chuva_mm", 30, cache, agora)
    assert resultado == 30


def test_dias_historico_efetivo_pior_caso_entre_varios_pontos_domina(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto_cacheado = (-23.5, -46.6)
    ponto_novo = (-22.9, -43.2)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    horas = _horas_no_intervalo(
        agora.floor("h") - pd.Timedelta(days=30),
        agora.floor("h") - pd.Timedelta(hours=3),
    )
    cache.gravar([(ponto_cacheado, h, 1.0) for h in horas], "chuva_mm", agora.isoformat())

    resultado = _dias_historico_efetivo([ponto_cacheado, ponto_novo], "chuva_mm", 30, cache, agora)

    assert resultado == 30  # ponto_novo nunca foi cacheado, domina o pior caso
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_openmeteo.py -k "horas_no_intervalo or dias_historico_efetivo" -v`
Expected: FAIL — `ImportError: cannot import name '_horas_no_intervalo'`.

- [ ] **Step 3: Write the implementation**

Adicionar em `src/ingest/openmeteo.py`, logo abaixo de `LIMITER_PADRAO`:

```python
from src.storage_cache_openmeteo import CacheOpenMeteo

JANELA_SEMPRE_EXPIRA_HORAS = 3
DIAS_HISTORICO_MINIMO = 1


def _horas_no_intervalo(inicio: pd.Timestamp, fim: pd.Timestamp) -> list[str]:
    """Horas (ISO 8601, ex. "2026-08-10T00:00") de `inicio` até `fim`, exclusive no fim."""
    if fim <= inicio:
        return []
    return pd.date_range(inicio, fim, freq="h", inclusive="left").strftime("%Y-%m-%dT%H:%M").tolist()


def _dias_historico_efetivo(
    pontos: list[tuple[float, float]],
    variavel: str,
    dias_historico: int,
    cache: CacheOpenMeteo | None,
    agora: pd.Timestamp,
) -> int:
    """Quanto de `dias_historico` ainda precisa ser pedido à API, dado o que já
    está cacheado para `pontos`. Sem cache, ou sem nada cacheado, retorna
    `dias_historico` inalterado (comportamento de hoje).
    """
    if cache is None:
        return dias_historico
    corte = agora.floor("h") - pd.Timedelta(hours=JANELA_SEMPRE_EXPIRA_HORAS)
    inicio = agora.floor("h") - pd.Timedelta(days=dias_historico)
    horas_esperadas = _horas_no_intervalo(inicio, corte)
    if not horas_esperadas:
        return dias_historico
    faltantes = cache.horas_faltantes(pontos, variavel, horas_esperadas)
    if not faltantes:
        return DIAS_HISTORICO_MINIMO
    hora_mais_antiga = min(h for horas in faltantes.values() for h in horas)
    inicio_faltante = pd.Timestamp(hora_mais_antiga).tz_localize("UTC")
    dias_necessarios = -(-(corte - inicio_faltante).total_seconds() // 86400)  # ceil
    return int(max(DIAS_HISTORICO_MINIMO, min(dias_historico, dias_necessarios)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_openmeteo.py -k "horas_no_intervalo or dias_historico_efetivo" -v`
Expected: 8 passed.

- [ ] **Step 5: Run full test suite to check nothing else broke**

Run: `.venv/bin/pytest tests/ -q`
Expected: all previous tests still passing (novo import não usado em produção ainda, sem efeito colateral).

- [ ] **Step 6: Commit**

```bash
git add src/ingest/openmeteo.py tests/test_openmeteo.py
git commit -m "feat(openmeteo): calcular dias_historico efetivo a partir do cache"
```

---

## Task 3: Encolher o POST e reconstruir a série completa com o cache

**Files:**
- Modify: `src/ingest/openmeteo.py`
- Test: `tests/test_openmeteo.py`

**Interfaces:**
- Consumes: `_dias_historico_efetivo` (Task 2), `CacheOpenMeteo.ler`/`.gravar` (Task 1).
- Produces: `_fetch_variavel_batch(..., cache: CacheOpenMeteo | None = None, agora: pd.Timestamp | None = None)`, `_serie_do_gap(ponto, variavel_hourly, coluna_saida, dias_historico, dias_historico_lote, cache, agora) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing tests**

```python
# adicionar em tests/test_openmeteo.py
import json as json_module

import responses

from src.ingest.openmeteo import FORECAST_URL, _fetch_variavel_batch
from src.storage_cache_openmeteo import CacheOpenMeteo


@responses.activate
def test_fetch_variavel_batch_usa_cache_para_encolher_past_days(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")

    # Pré-popula o cache com 29 dos 30 dias de histórico pedidos.
    horas_cacheadas = [
        h for h in pd.date_range(
            agora.floor("h") - pd.Timedelta(days=30), agora.floor("h") - pd.Timedelta(days=1), freq="h",
        ).strftime("%Y-%m-%dT%H:%M")
    ]
    cache.gravar([(ponto, h, 1.0) for h in horas_cacheadas], "precipitation", agora.isoformat())

    corpos_recebidos = []

    def callback(request):
        corpo = json_module.loads(request.body)
        corpos_recebidos.append(corpo)
        horas = ["2026-08-10T10:00", "2026-08-10T11:00"]
        return (200, {}, json_module.dumps({
            "latitude": ponto[0], "longitude": ponto[1],
            "hourly": {"time": horas, "precipitation": [5.0, 6.0]},
        }))

    responses.add_callback(responses.POST, FORECAST_URL, callback=callback, content_type="application/json")

    series = _fetch_variavel_batch(
        [ponto], "precipitation", "chuva_mm",
        dias_historico=30, dias_previsao=1, timeout=60.0, max_retries=1, backoff_factor=0.01,
        session=None, tamanho_lote=50, cache=cache, agora=agora,
    )

    assert corpos_recebidos[0]["past_days"] <= 2  # bem menor que os 30 originais
    total_horas = len(series[0])
    assert total_horas > 700  # ~29 dias cacheados (696h) + as horas novas da API, série completa preservada


@responses.activate
def test_fetch_variavel_batch_grava_resposta_no_cache(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    agora = pd.Timestamp("2026-08-10T12:00", tz="UTC")
    horas = ["2026-08-10T09:00", "2026-08-10T10:00"]
    responses.add(
        responses.POST, FORECAST_URL, status=200,
        json={"latitude": ponto[0], "longitude": ponto[1], "hourly": {"time": horas, "precipitation": [1.0, 2.0]}},
    )

    _fetch_variavel_batch(
        [ponto], "precipitation", "chuva_mm",
        dias_historico=1, dias_previsao=1, timeout=60.0, max_retries=1, backoff_factor=0.01,
        session=None, tamanho_lote=50, cache=cache, agora=agora,
    )

    lido = cache.ler([ponto], "precipitation", horas)
    assert lido == {ponto: {"2026-08-10T09:00": 1.0, "2026-08-10T10:00": 2.0}}


@responses.activate
def test_fetch_variavel_batch_sem_cache_comportamento_identico_a_hoje():
    horas = ["2026-08-10T00:00"]
    responses.add(
        responses.POST, FORECAST_URL, status=200,
        json={"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "precipitation": [1.0]}},
    )

    series = _fetch_variavel_batch(
        [(-23.5, -46.6)], "precipitation", "chuva_mm",
        dias_historico=30, dias_previsao=1, timeout=60.0, max_retries=1, backoff_factor=0.01,
        session=None, tamanho_lote=50,
    )

    assert len(series) == 1
    assert list(series[0]["chuva_mm"]) == [1.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_openmeteo.py -k "usa_cache_para_encolher or grava_resposta_no_cache" -v`
Expected: FAIL — `TypeError: _fetch_variavel_batch() got an unexpected keyword argument 'cache'`.

- [ ] **Step 3: Write the implementation**

Substituir `_fetch_variavel_batch` inteira em `src/ingest/openmeteo.py`:

```python
def _serie_do_gap(
    ponto: tuple[float, float],
    variavel_hourly: str,
    coluna_saida: str,
    dias_historico: int,
    dias_historico_lote: int,
    cache: CacheOpenMeteo | None,
    agora: pd.Timestamp,
) -> pd.DataFrame:
    """Horas que o POST (encolhido para `dias_historico_lote`) não cobriu, mas
    o chamador pediu (`dias_historico`), reconstruídas a partir do cache."""
    vazio = pd.DataFrame(columns=["data_hora", coluna_saida])
    if cache is None or dias_historico_lote >= dias_historico:
        return vazio
    corte = agora.floor("h") - pd.Timedelta(hours=JANELA_SEMPRE_EXPIRA_HORAS)
    inicio_completo = agora.floor("h") - pd.Timedelta(days=dias_historico)
    inicio_lote = agora.floor("h") - pd.Timedelta(days=dias_historico_lote)
    horas_gap = _horas_no_intervalo(inicio_completo, min(inicio_lote, corte))
    if not horas_gap:
        return vazio
    cacheado = cache.ler([ponto], variavel_hourly, horas_gap)
    linhas = cacheado.get(ponto, {})
    if not linhas:
        return vazio
    return pd.DataFrame({
        "data_hora": pd.to_datetime(list(linhas.keys()), utc=True),
        coluna_saida: list(linhas.values()),
    })


def _fetch_variavel_batch(
    pontos: list[tuple[float, float]],
    variavel_hourly: str,
    coluna_saida: str,
    dias_historico: int,
    dias_previsao: int,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
    session: requests.Session | None,
    tamanho_lote: int,
    max_workers_lote: int = LOTE_WORKERS_PADRAO,
    cache: CacheOpenMeteo | None = None,
    agora: pd.Timestamp | None = None,
) -> list[pd.DataFrame]:
    """Busca uma variável horária da Open-Meteo para uma lista de pontos, em lotes.

    Compartilhada por `fetch_precipitacao_batch` (variavel="precipitation") e
    `fetch_vento_batch` (variavel="windgusts_10m"), mesma paginação, retry e
    tratamento de 429, só muda qual campo é pedido/lido da resposta.

    `cache`, se informado, encolhe o `past_days` de cada lote para só o que
    ainda falta (ver `_dias_historico_efetivo`) e reconstrói a série completa
    pedida mesclando a resposta da API com o que faltava vir do cache (ver
    `_serie_do_gap`) — quem chama sempre recebe a janela completa que pediu,
    igual a hoje, só que parte dela pode ter vindo do cache em vez da rede.
    `cache=None` (padrão) reproduz o comportamento de hoje: sem cache, sem
    encolhimento, série inteira sempre vem da API.

    Os lotes são disparados concorrentemente (thread pool), não um a um com
    pausa fixa: quem espaça as chamadas de verdade é `LIMITER_PADRAO`
    (compartilhado por todo o processo, inclusive entre UFs em
    `src/export/nacional.py`), não este laço.
    """
    if not pontos:
        return []

    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    sess = session or requests.Session()
    lotes = [pontos[inicio:inicio + tamanho_lote] for inicio in range(0, len(pontos), tamanho_lote)]

    def _buscar_lote(lote: list[tuple[float, float]]) -> list[tuple[tuple[float, float], dict, int]]:
        dias_historico_lote = _dias_historico_efetivo(lote, variavel_hourly, dias_historico, cache, agora)
        payload = _post_lote(
            lote, [variavel_hourly], dias_historico_lote, dias_previsao,
            timeout, max_retries, backoff_factor, sess,
        )
        if cache is not None:
            registros = [
                (ponto, hora, valor)
                for ponto, item in zip(lote, payload)
                for hora, valor in zip(
                    item.get("hourly", {}).get("time", []),
                    item.get("hourly", {}).get(variavel_hourly, []),
                )
            ]
            cache.gravar(registros, variavel_hourly, agora.isoformat())
        return [(ponto, item, dias_historico_lote) for ponto, item in zip(lote, payload)]

    with ThreadPoolExecutor(max_workers=max_workers_lote) as executor:
        resultados_lotes = list(executor.map(_buscar_lote, lotes))
    pares = [par for resultado_lote in resultados_lotes for par in resultado_lote]

    series = []
    for ponto, item, dias_historico_lote in pares:
        horario = item.get("hourly", {})
        df_api = pd.DataFrame({
            "data_hora": pd.to_datetime(horario.get("time", []), utc=True),
            coluna_saida: horario.get(variavel_hourly, []),
        })
        df_gap = _serie_do_gap(ponto, variavel_hourly, coluna_saida, dias_historico, dias_historico_lote, cache, agora)
        serie = pd.concat([df_gap, df_api], ignore_index=True) if not df_gap.empty else df_api
        series.append(serie.sort_values("data_hora").reset_index(drop=True))
    return series
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_openmeteo.py -v`
Expected: all passed, incluindo os 3 novos e todos os pré-existentes (`cache=None` preserva o comportamento antigo).

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/ingest/openmeteo.py tests/test_openmeteo.py
git commit -m "feat(openmeteo): encolher past_days via cache e reconstruir série completa"
```

---

## Task 4: Expor `cache`/`agora` em `fetch_precipitacao_batch`/`fetch_vento_batch`

**Files:**
- Modify: `src/ingest/openmeteo.py`
- Test: `tests/test_openmeteo.py`

**Interfaces:**
- Consumes: `_fetch_variavel_batch(..., cache, agora)` (Task 3).
- Produces: `fetch_precipitacao_batch(..., cache: CacheOpenMeteo | None = None, agora: pd.Timestamp | None = None)`, `fetch_vento_batch(..., cache: CacheOpenMeteo | None = None, agora: pd.Timestamp | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em tests/test_openmeteo.py
@responses.activate
def test_fetch_precipitacao_batch_aceita_cache_e_agora(tmp_path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    horas = ["2026-08-10T00:00"]
    responses.add(
        responses.POST, FORECAST_URL, status=200,
        json={"latitude": -23.5, "longitude": -46.6, "hourly": {"time": horas, "precipitation": [1.0]}},
    )

    series = fetch_precipitacao_batch(
        [(-23.5, -46.6)], cache=cache, agora=pd.Timestamp("2026-08-10T05:00", tz="UTC"),
    )

    assert list(series[0]["chuva_mm"]) == [1.0]
    assert cache.ler([(-23.5, -46.6)], "precipitation", horas) != {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_openmeteo.py -k aceita_cache_e_agora -v`
Expected: FAIL — `TypeError: fetch_precipitacao_batch() got an unexpected keyword argument 'cache'`.

- [ ] **Step 3: Write the implementation**

```python
# src/ingest/openmeteo.py — substituir as assinaturas de fetch_precipitacao_batch e fetch_vento_batch
def fetch_precipitacao_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 30,
    dias_previsao: int = 1,
    timeout: float = 60.0,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    max_workers_lote: int = LOTE_WORKERS_PADRAO,
    cache: CacheOpenMeteo | None = None,
    agora: pd.Timestamp | None = None,
) -> list[pd.DataFrame]:
    """Busca chuva horária para uma lista de pontos `(lat, lon)`.

    Retorna uma lista de DataFrames (`data_hora, chuva_mm`), um por ponto, na
    mesma ordem de `pontos`. `dias_historico` controla quantos dias para trás
    são pedidos e `dias_previsao` quantos dias de previsão para frente (a
    API aceita até 92 e 16 respectivamente); filtrar por "é passado" ou
    "é futuro" é responsabilidade de quem consome o DataFrame, não deste
    cliente.

    Internamente, `pontos` é dividido em lotes de `tamanho_lote` (padrão 100,
    ver docstring do módulo sobre o limite prático da API), buscados em
    paralelo (`max_workers_lote` threads) e pautados por `LIMITER_PADRAO`.
    `cache`, se informado, reduz o histórico de fato pedido à API (ver
    `_fetch_variavel_batch`); `agora` é parametrizável para testes
    determinísticos, em produção usa o instante atual.
    """
    return _fetch_variavel_batch(
        pontos, "precipitation", "chuva_mm", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, max_workers_lote,
        cache, agora,
    )


def fetch_vento_batch(
    pontos: list[tuple[float, float]],
    dias_historico: int = 4,
    dias_previsao: int = 1,
    timeout: float = 60.0,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
    tamanho_lote: int = TAMANHO_LOTE_PADRAO,
    max_workers_lote: int = LOTE_WORKERS_PADRAO,
    cache: CacheOpenMeteo | None = None,
    agora: pd.Timestamp | None = None,
) -> list[pd.DataFrame]:
    """Busca rajada de vento (`windgusts_10m`) horária para uma lista de pontos `(lat, lon)`.

    Mesmo cliente/lote/retry de `fetch_precipitacao_batch`, reaproveita
    `_fetch_variavel_batch`. Retorna uma lista de DataFrames
    (`data_hora, vento_rajada_kmh`), um por ponto, na mesma ordem de `pontos`.
    """
    return _fetch_variavel_batch(
        pontos, "windgusts_10m", "vento_rajada_kmh", dias_historico, dias_previsao,
        timeout, max_retries, backoff_factor, session, tamanho_lote, max_workers_lote,
        cache, agora,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_openmeteo.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/openmeteo.py tests/test_openmeteo.py
git commit -m "feat(openmeteo): expor cache/agora em fetch_precipitacao_batch e fetch_vento_batch"
```

---

## Task 5: Wire em `src/export/dashboard_data.py`

**Files:**
- Modify: `src/export/dashboard_data.py`
- Test: `tests/test_dashboard_data.py` (arquivo já existe — confirmar nome exato com `ls tests/` antes de editar; se o nome real for diferente, usar o existente em vez de criar um novo)

**Interfaces:**
- Consumes: `fetch_precipitacao_batch(..., cache, agora)` (Task 4).
- Produces: `_calcular_chuva_openmeteo(..., cache: CacheOpenMeteo | None = None)`, `_series_openmeteo_por_municipio(..., cache: CacheOpenMeteo | None = None)`, `_exportar_openmeteo(..., cache: CacheOpenMeteo | None = None)`, `exportar_dashboard(..., cache_openmeteo: CacheOpenMeteo | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao arquivo de teste existente de dashboard_data (confirmar path com `ls tests/test_dashboard*`)
import responses

from src.export.dashboard_data import exportar_dashboard
from src.ingest.openmeteo import FORECAST_URL
from src.storage_cache_openmeteo import CacheOpenMeteo


@responses.activate
def test_exportar_dashboard_aceita_cache_openmeteo(tmp_path):
    # Reaproveitar os helpers já existentes neste arquivo de teste
    # (_setores_uf ou equivalente) para popular 1 UF com 1 setor, igual aos
    # testes vizinhos de exportar_dashboard/_calcular_chuva_openmeteo.
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        meta = exportar_dashboard(
            "SP", 2026, tmp_path, tmp_path / "export", fonte="openmeteo", cache_openmeteo=cache,
        )

    assert meta["fonte"] == "openmeteo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -k aceita_cache_openmeteo -v` (ajustar nome do arquivo conforme `ls tests/`)
Expected: FAIL — `TypeError: exportar_dashboard() got an unexpected keyword argument 'cache_openmeteo'`.

- [ ] **Step 3: Write the implementation**

Em `src/export/dashboard_data.py`, adicionar `cache: CacheOpenMeteo | None = None` (ou `cache_openmeteo` no nível de `exportar_dashboard`, renomeado para `cache` internamente) e repassar em cada nível:

```python
# import no topo do arquivo
from src.storage_cache_openmeteo import CacheOpenMeteo

# _calcular_chuva_openmeteo: adicionar parâmetro e repassar
def _calcular_chuva_openmeteo(
    setores: gpd.GeoDataFrame,
    janelas: tuple[int, ...] = (24, 72),
    dias_historico: int = DIAS_HISTORICO_CRUZAMENTO,
    dias_previsao: int = DIAS_PREVISAO_ALERTA,
    agora: pd.Timestamp | None = None,
    pontos: list[tuple[float, float]] | None = None,
    cache: CacheOpenMeteo | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    # ... corpo inalterado até a chamada de fetch_precipitacao_batch ...
    series_unicas = fetch_precipitacao_batch(
        pontos_unicos, dias_historico=dias_historico, dias_previsao=dias_previsao,
        cache=cache, agora=agora,
    )
    # ... resto do corpo inalterado ...

# _series_openmeteo_por_municipio: adicionar parâmetro e repassar
def _series_openmeteo_por_municipio(
    setores: gpd.GeoDataFrame,
    dias_historico: int = JANELA_SERIE_DIAS,
    agora: pd.Timestamp | None = None,
    cache: CacheOpenMeteo | None = None,
) -> dict:
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    municipios, pontos = centroides_municipio(setores)
    series_brutas = fetch_precipitacao_batch(pontos, dias_historico=dias_historico, cache=cache, agora=agora)
    # ... resto do corpo inalterado ...

# _exportar_openmeteo: adicionar parâmetro e repassar para os dois acima
def _exportar_openmeteo(
    setores: gpd.GeoDataFrame,
    pontos: list[tuple[float, float]] | None = None,
    cache: CacheOpenMeteo | None = None,
) -> tuple[pd.DataFrame, dict, dict, dict]:
    try:
        cruzado, previsao = _calcular_chuva_openmeteo(setores, janelas=(24, 72), pontos=pontos, cache=cache)
        series = _series_openmeteo_por_municipio(setores, cache=cache)
    except OpenMeteoFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar a Open-Meteo: {exc}") from exc
    # ... resto do corpo inalterado ...

# exportar_dashboard: adicionar cache_openmeteo e repassar só quando fonte="openmeteo"
def exportar_dashboard(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    fonte: str = "openmeteo",
    pontos_grade: list[tuple[float, float]] | None = None,
    cache_openmeteo: CacheOpenMeteo | None = None,
) -> dict:
    # ... docstring existente + uma linha nova:
    # `cache_openmeteo`, se informado, é repassado para as buscas na Open-Meteo
    # (só relevante com fonte="openmeteo"; ver src/storage_cache_openmeteo.py).
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
    # ... resto do corpo inalterado ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_dashboard_data.py -v` (nome real do arquivo)
Expected: all passed.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/export/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat(dashboard_data): repassar cache_openmeteo até fetch_precipitacao_batch"
```

---

## Task 6: Wire em `src/export/vento_data.py`

**Files:**
- Modify: `src/export/vento_data.py`
- Test: `tests/test_vento_data.py` (confirmar nome real com `ls tests/test_vento*`)

**Interfaces:**
- Consumes: `fetch_vento_batch(..., cache, agora)` (Task 4).
- Produces: `exportar_vento(..., cache_openmeteo: CacheOpenMeteo | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao arquivo de teste existente de vento_data
from src.storage_cache_openmeteo import CacheOpenMeteo


def test_exportar_vento_aceita_cache_openmeteo(tmp_path, ...):  # reaproveitar fixtures/mocks já usados nos testes vizinhos deste arquivo (IBGE + Open-Meteo)
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    # ... mesmo setup de mock de fetch_municipios/fetch_nomes_municipios/fetch_vento_batch
    # já usado nos outros testes de exportar_vento neste arquivo ...
    resultado = exportar_vento("SP", 2026, tmp_path, tmp_path / "export", cache_openmeteo=cache)
    assert resultado is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_vento_data.py -k aceita_cache_openmeteo -v`
Expected: FAIL — `TypeError: exportar_vento() got an unexpected keyword argument 'cache_openmeteo'`.

- [ ] **Step 3: Write the implementation**

```python
# src/export/vento_data.py
from src.storage_cache_openmeteo import CacheOpenMeteo  # novo import no topo

def exportar_vento(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    agora: pd.Timestamp | None = None,
    cache_openmeteo: CacheOpenMeteo | None = None,
) -> dict:
    # docstring existente + uma linha: `cache_openmeteo`, se informado, reduz
    # o histórico de fato pedido à Open-Meteo (ver src/storage_cache_openmeteo.py).
    agora = agora if agora is not None else pd.Timestamp.now(tz="UTC")
    uf_norm = uf.strip().upper()
    saida_dir.mkdir(parents=True, exist_ok=True)

    try:
        municipios_gdf = fetch_municipios(uf_norm)
        nomes = fetch_nomes_municipios(uf_norm)
    except IBGEFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar a malha municipal do IBGE: {exc}") from exc

    codareas, pontos = centroides_ibge(municipios_gdf)
    try:
        series = fetch_vento_batch(pontos, dias_historico=4, dias_previsao=1, cache=cache_openmeteo, agora=agora)
    except OpenMeteoFetchError as exc:
        raise ExportacaoDashboardError(f"Falha ao consultar vento na Open-Meteo: {exc}") from exc
    # ... resto do corpo inalterado ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_vento_data.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/export/vento_data.py tests/test_vento_data.py
git commit -m "feat(vento_data): repassar cache_openmeteo até fetch_vento_batch"
```

---

## Task 7: Wire em `src/export/nacional.py` + teste de integração (2ª execução faz menos chamadas)

**Files:**
- Modify: `src/export/nacional.py`
- Test: `tests/test_export_nacional.py`

**Interfaces:**
- Consumes: `exportar_dashboard(..., cache_openmeteo)` (Task 5).
- Produces: `exportar_nacional(..., cache_openmeteo: CacheOpenMeteo | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em tests/test_export_nacional.py
from src.storage_cache_openmeteo import CacheOpenMeteo


@responses.activate
def test_exportar_nacional_segunda_execucao_faz_menos_chamadas_http(tmp_path: Path):
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    saida = tmp_path / "export"
    agora = pd.Timestamp("2026-08-22T12:00", tz="UTC")

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # setores
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)  # município
        exportar_nacional(["SP"], 2026, tmp_path, saida, orcamento_alvo=1000, cache_openmeteo=cache)
        chamadas_1a_execucao = len(rsps.calls)

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        rsps.add(responses.POST, FORECAST_URL, json=_resposta_openmeteo(1), status=200)
        exportar_nacional(["SP"], 2026, tmp_path, saida, orcamento_alvo=1000, cache_openmeteo=cache)
        chamadas_2a_execucao = len(rsps.calls)

    assert chamadas_2a_execucao <= chamadas_1a_execucao
```

Nota: este teste verifica só que o número de chamadas não aumenta (é uma checagem de regressão fraca porque o mock não modela `past_days` variando — a asserção forte de redução real de `past_days` já está coberta pelo teste `test_fetch_variavel_batch_usa_cache_para_encolher_past_days` da Task 3). O objetivo aqui é garantir que a integração `exportar_nacional` → `exportar_dashboard` → `fetch_precipitacao_batch` não perde o `cache_openmeteo` pelo caminho.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_export_nacional.py -k segunda_execucao_faz_menos_chamadas -v`
Expected: FAIL — `TypeError: exportar_nacional() got an unexpected keyword argument 'cache_openmeteo'`.

- [ ] **Step 3: Write the implementation**

Em `src/export/nacional.py`:

```python
# import no topo
from src.storage_cache_openmeteo import CacheOpenMeteo

def exportar_nacional(
    ufs: list[str],
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    orcamento_alvo: int = ORCAMENTO_ALVO_PADRAO,
    max_workers_uf: int = UF_WORKERS_PADRAO,
    cache_openmeteo: CacheOpenMeteo | None = None,
) -> dict[str, dict]:
    # docstring existente + parágrafo novo:
    # `cache_openmeteo`, se informado, é repassado para `exportar_dashboard`
    # de cada UF — mesma instância compartilhada entre todas, para que o
    # cache de uma UF beneficie a leitura/escrita das outras (ver
    # docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md).
    setores_por_uf = {}
    # ... corpo inalterado até _exportar_uf ...

    def _exportar_uf(uf: str) -> tuple[str, dict | None]:
        inicio, fim = fatias[uf]
        try:
            meta = exportar_dashboard(
                uf, ano, diretorio_dados, saida_dir,
                fonte="openmeteo", pontos_grade=pontos_grade[inicio:fim],
                cache_openmeteo=cache_openmeteo,
            )
        except (ExportacaoDashboardError, OSError, ValueError) as exc:
            logger.warning("Falha ao exportar %s: %s", uf, exc)
            return uf, None
        meta["tamanho_celula_grade_graus"] = tamanho_celula
        meta["total_celulas_grade"] = total_celulas
        return uf, meta

    # ... resto do corpo inalterado ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_export_nacional.py -v`
Expected: all passed.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/export/nacional.py tests/test_export_nacional.py
git commit -m "feat(nacional): repassar cache_openmeteo compartilhado entre UFs"
```

---

## Task 8: Wire no CLI + `.gitignore`

**Files:**
- Modify: `src/cli.py`, `.gitignore`

**Interfaces:**
- Consumes: `exportar_dashboard(..., cache_openmeteo)` (Task 5), `exportar_vento(..., cache_openmeteo)` (Task 6), `exportar_nacional(..., cache_openmeteo)` (Task 7), `CacheOpenMeteo`, `CAMINHO_PADRAO` (Task 1).
- Produces: nenhuma interface nova exposta a outros módulos — só fiação interna do CLI.

- [ ] **Step 1: Confirmar comportamento atual via teste manual (sem teste automatizado novo — CLI já é coberto por testes de integração dos módulos abaixo dele)**

Rodar `.venv/bin/orca atualizar-nacional --help` antes de editar, para conferir que os flags existentes continuam batendo com o que está documentado abaixo (sem regressão de interface).

Run: `.venv/bin/python -m src.cli atualizar-nacional --help`
Expected: help text mostra `--ufs`, `--ano`, `--orcamento-alvo`, `--diretorio`, `--saida` (sem erro).

- [ ] **Step 2: Editar `src/cli.py`**

```python
# topo do arquivo, junto aos outros imports de src.export/src.ingest
from src.storage_cache_openmeteo import CacheOpenMeteo

# dentro de exportar_dashboard_cmd, antes da chamada a exportar_dashboard:
    cache = CacheOpenMeteo()
    meta = exportar_dashboard(uf, ano, diretorio, saida_dir, fonte=fonte, cache_openmeteo=cache)

# dentro de atualizar (loop por UF), antes da chamada a exportar_dashboard:
        cache = CacheOpenMeteo()
        meta = exportar_dashboard(uf_norm, ano, DATA_DIR, DASHBOARD_DATA_DIR, fonte=fonte, cache_openmeteo=cache)

# dentro de atualizar_nacional_cmd, antes da chamada a exportar_nacional:
    cache = CacheOpenMeteo()
    try:
        resultados = exportar_nacional(
            lista_ufs, ano, diretorio, saida,
            orcamento_alvo=orcamento_alvo, cache_openmeteo=cache,
        )
    except ValueError as exc:
        typer.echo(f"FALHA na exportação nacional: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{len(resultados)}/{len(lista_ufs)} UF(s) exportada(s) para {saida}.")

    falhas_vento = []
    for uf in resultados:
        try:
            exportar_vento(uf, ano, diretorio, saida, cache_openmeteo=cache)
        except (ExportacaoDashboardError, ValueError) as exc:
            typer.echo(f"  FALHA na exportação de vento ({uf}): {exc}", err=True)
            falhas_vento.append(uf)
```

Cada comando constrói sua própria `CacheOpenMeteo()` (path padrão `data/cache/openmeteo.sqlite`, mesmo arquivo entre execuções sucessivas do CLI local) — dentro de `atualizar_nacional_cmd` a MESMA instância é reaproveitada entre `exportar_nacional` e todos os `exportar_vento`, para as 3 séries compartilharem 1 conexão.

- [ ] **Step 3: Adicionar entrada no `.gitignore`**

```
# .gitignore — adicionar linha
data/cache/
```

- [ ] **Step 4: Rodar a suíte inteira**

Run: `.venv/bin/pytest tests/ -q`
Expected: all passed (nenhum teste do CLI hoje instancia esses comandos de ponta a ponta contra a rede real, então não deveria haver I/O de cache real durante os testes).

- [ ] **Step 5: Commit**

```bash
git add src/cli.py .gitignore
git commit -m "feat(cli): construir e repassar CacheOpenMeteo nos comandos de exportação"
```

---

## Task 9: Sincronização do cache via `gh-pages` no workflow

**Files:**
- Modify: `.github/workflows/atualizar-dados.yml`

**Interfaces:**
- Consumes: nada do código Python — só o caminho de arquivo padrão `data/cache/openmeteo.sqlite` (Task 1) e a convenção de publicar `docs/dashboard/` como `publish_dir` já existente.

- [ ] **Step 1: Editar o workflow**

```yaml
# .github/workflows/atualizar-dados.yml — arquivo completo atualizado

name: Atualizar dados do ORCA

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

# Impede duas execuções (agendada + manual) rodando ao mesmo tempo: além de
# disputar cota de rate limit da Open-Meteo (observado em 22/08/2026), duas
# escritas concorrentes no arquivo de cache fariam a última a publicar
# apagar silenciosamente o progresso da outra (ver
# docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md).
concurrency:
  group: atualizar-dados
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  atualizar:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v7
        with:
          python-version: "3.11"

      - name: Instalar dependências
        run: pip install -e .

      - name: Baixar cache da Open-Meteo publicado (gh-pages)
        # Ausência do arquivo (1a execução, ou branch gh-pages ainda não
        # existe) não é erro: src/storage_cache_openmeteo.py já trata
        # arquivo ausente/corrompido como cache vazio.
        run: |
          mkdir -p data/cache
          git fetch origin gh-pages 2>/dev/null && \
            git show origin/gh-pages:cache/openmeteo.sqlite > data/cache/openmeteo.sqlite 2>/dev/null || \
            echo "Sem cache publicado ainda (1a execução ou branch gh-pages não existe); seguindo com cache vazio."

      - name: Rodar atualização nacional
        run: >
          python scripts/atualizar_dados.py
          --ufs "${{ github.event.inputs.ufs || '' }}"
          --ano "${{ github.event.inputs.ano || '2026' }}"

      - name: Publicar dados como artefato
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: dados-orca-nacional
          path: |
            data/*.gpkg
            data/*.csv
            data/ultima_atualizacao.txt
          retention-days: 14

      - name: Preparar cache para publicação
        # `peaceiris/actions-gh-pages` com force_orphan publica só o que
        # estiver dentro de publish_dir no momento do deploy; o cache
        # precisa estar copiado pra lá pra sobreviver ao próximo run.
        # `always()` porque mesmo uma execução com UFs faltando ainda
        # avançou o cache das UFs que deram certo — vale publicar assim
        # mesmo.
        if: always()
        run: |
          mkdir -p docs/dashboard/cache
          if [ -f data/cache/openmeteo.sqlite ]; then
            cp data/cache/openmeteo.sqlite docs/dashboard/cache/openmeteo.sqlite
          fi

      - name: Publicar dashboard no GitHub Pages
        if: always()
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs/dashboard
          publish_branch: gh-pages
          force_orphan: true
          user_name: "github-actions[bot]"
          user_email: "github-actions[bot]@users.noreply.github.com"
          commit_message: "chore(dashboard): publicar dados atualizados"
```

- [ ] **Step 2: Validar sintaxe do YAML localmente**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/atualizar-dados.yml'))"`
Expected: sem erro (sintaxe válida).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/atualizar-dados.yml
git commit -m "feat(ci): sincronizar cache da Open-Meteo via gh-pages entre execuções"
```

- [ ] **Step 4: Validação em produção (fora do escopo de teste automatizado)**

Disparar o workflow manualmente (`gh workflow run atualizar-dados.yml`) duas vezes seguidas depois do deploy deste plano, e conferir no log da 2ª execução que os POSTs à Open-Meteo têm `past_days` menor que os da 1ª (grep por `"past_days"` não é possível direto no log — mas o volume de warnings de 429/timeout na 2ª execução deve ser visivelmente menor, e `docs/dashboard/cache/openmeteo.sqlite` deve aparecer publicado em `gh-pages` depois da 1ª execução).

---

## Self-Review (preenchido nesta escrita do plano)

**Cobertura da spec:**
- Componente 1 (schema + módulo) → Task 1. ✓
- Componente 2 (busca incremental, `dias_historico` por lote) → Tasks 2-3. ✓
- Componente 3 (sincronização via gh-pages + `concurrency:`) → Task 9. ✓
- Componente 4 (uso local sem sincronização) → Task 8 (cada comando CLI constrói seu próprio `CacheOpenMeteo()` no path padrão, sem nenhum passo de sync — é o próprio código de produção, não precisa de nada especial pro caso local). ✓
- Componente 5 (fallback de UF que esgota retries, idade do dado no front-end) → **fora deste plano**, como já sinalizado na spec ("fica detalhado no plano de implementação, não é bloqueante"); não incluído aqui, fica pra um plano futuro que também cobre a mudança de front-end.

**Ambiguidade resolvida durante a escrita:** `src/storage.py` é hoje um módulo único, não um pacote — o módulo novo virou `src/storage_cache_openmeteo.py` (arquivo irmão) em vez de `src/storage/cache_openmeteo.py`, pra não forçar uma migração de `storage.py` pra pacote como efeito colateral deste plano (ver nota na Task 1).

**Nomes de arquivo de teste incertos:** Tasks 5 e 6 referenciam `tests/test_dashboard_data.py` e `tests/test_vento_data.py` por convenção, mas não foram confirmados nesta escrita — o executor de cada uma dessas tasks deve rodar `ls tests/test_dashboard* tests/test_vento*` primeiro e ajustar o nome se divergir.
