import json
import threading
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import responses
from shapely.geometry import Polygon

import src.export.nacional as nacional
import src.ingest.openmeteo as openmeteo
from src.config import caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError
from src.export.nacional import exportar_nacional
from src.ingest.openmeteo import FORECAST_URL
from src.storage import salvar_setores
from src.storage_cache_openmeteo import CacheOpenMeteo


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


def _resposta_openmeteo_ancorada_em_agora(n_pontos: int) -> list[dict]:
    """Como `_resposta_openmeteo`, mas com horas ancoradas no relógio real
    (de agora-6d até agora+1d), para testes que dependem do cache de uma
    execução servir à execução seguinte."""
    inicio = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(days=6)
    horas = pd.date_range(inicio, periods=7 * 24 + 1, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    return [
        {
            "latitude": -23.5, "longitude": -46.6,
            "hourly": {"time": horas_iso, "precipitation": [1.0] * len(horas_iso)},
        }
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

    # O sinal de que houve UMA grade nacional compartilhada (e não 27 grades
    # independentes, uma por UF) é que as duas UFs reportam exatamente o mesmo
    # tamanho de célula e o mesmo total de células.
    assert (
        resultados["SP"]["tamanho_celula_grade_graus"]
        == resultados["RJ"]["tamanho_celula_grade_graus"]
    )
    assert resultados["SP"]["total_celulas_grade"] == resultados["RJ"]["total_celulas_grade"]


@responses.activate
def test_exportar_nacional_segunda_execucao_pede_menos_historico(tmp_path: Path):
    """A 2a execução não faz menos chamadas (a janela recente/previsão é
    sempre buscada ao vivo, ver docs/superpowers/specs/2026-08-22-cache-
    openmeteo-design.md), mas o past_days de cada chamada encolhe porque o
    histórico da 1a execução já está cacheado.
    """
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    saida = tmp_path / "export"

    # `exportar_nacional` não recebe `agora` (só as funções de baixo nível
    # recebem), então a janela consultada é o relógio real -- a resposta
    # simulada precisa cobrir horas reais, senão nada do que a 1a execução
    # cacheia serve para a 2a.
    resposta = _resposta_openmeteo_ancorada_em_agora(1)

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)  # setores
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)  # município
        exportar_nacional(["SP"], 2026, tmp_path, saida, orcamento_alvo=1000, cache_openmeteo=cache)
        past_days_1a_execucao = json.loads(rsps.calls[0].request.body)["past_days"]

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        rsps.add(responses.POST, FORECAST_URL, json=resposta, status=200)
        exportar_nacional(["SP"], 2026, tmp_path, saida, orcamento_alvo=1000, cache_openmeteo=cache)
        past_days_2a_execucao = json.loads(rsps.calls[0].request.body)["past_days"]

    assert past_days_2a_execucao < past_days_1a_execucao


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


def test_exportar_nacional_reexporta_uf_que_falhou_na_primeira_passada(tmp_path: Path, monkeypatch):
    """Reproduz o padrão observado em produção: uma UF específica esgota os
    retries na 1a passada (rate limiting momentâneo da Open-Meteo), mas uma
    segunda tentativa, em série e ao final, dá tempo pra isso passar e
    recupera a UF em vez de ela sair faltando do dashboard.
    """
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    salvar_setores(_setores_uf("RJ", "RJ1", -43.20, -22.90), caminho_setores("RJ", tmp_path))

    chamadas: dict[str, int] = {"SP": 0, "RJ": 0}

    def fake_exportar_dashboard(uf, ano, diretorio_dados, saida_dir, fonte, pontos_grade, cache_openmeteo=None):
        chamadas[uf] += 1
        if uf == "SP" and chamadas[uf] == 1:
            raise ExportacaoDashboardError("falha simulada na 1a passada")
        return {"uf": uf}

    monkeypatch.setattr(nacional, "exportar_dashboard", fake_exportar_dashboard)

    saida = tmp_path / "export"
    resultados = exportar_nacional(["SP", "RJ"], 2026, tmp_path, saida, orcamento_alvo=1000)

    assert set(resultados.keys()) == {"SP", "RJ"}
    assert chamadas["SP"] == 2
    assert chamadas["RJ"] == 1


def test_exportar_nacional_reexportacao_tambem_falha_mantem_uf_de_fora(tmp_path: Path, monkeypatch):
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))

    def sempre_falha(uf, ano, diretorio_dados, saida_dir, fonte, pontos_grade, cache_openmeteo=None):
        raise ExportacaoDashboardError("falha simulada persistente")

    monkeypatch.setattr(nacional, "exportar_dashboard", sempre_falha)

    saida = tmp_path / "export"
    resultados = exportar_nacional(["SP"], 2026, tmp_path, saida, orcamento_alvo=1000)

    assert resultados == {}
    disponiveis = json.loads((saida / "ufs_disponiveis.json").read_text())
    assert disponiveis == []


def test_exportar_nacional_exporta_ufs_concorrentemente(tmp_path: Path, monkeypatch):
    """As UFs não esperam uma pela outra: são exportadas em paralelo.

    A prova é determinística, não cronometrada: cada resposta simulada só é
    liberada quando 3 threads estiverem simultaneamente dentro do callback
    (`threading.Barrier`). Se a exportação for sequencial, a primeira thread
    espera sozinha, a barreira estoura no timeout e o teste falha -- sem
    depender de relógio de parede (a versão anterior afirmava
    `decorrido < 0.5` e era flaky em runner compartilhado).

    `exportar_dashboard` faz 2 POSTs por UF (setores + série por município),
    então 3 UFs geram 6 passagens pela barreira: 2 rodadas completas de 3.
    O espaçamento mínimo entre requisições do `LIMITER_PADRAO` (ver
    `src/ingest/openmeteo.py`) é uma preocupação à parte (coberta em
    `tests/test_rate_limiter.py`); aqui ele é neutralizado para isolar só a
    concorrência do thread pool.
    """
    monkeypatch.setattr(openmeteo.LIMITER_PADRAO, "acquire", lambda: None)
    monkeypatch.setattr(openmeteo.LIMITER_PADRAO, "release", lambda: None)
    salvar_setores(_setores_uf("SP", "SP1", -46.60, -23.50), caminho_setores("SP", tmp_path))
    salvar_setores(_setores_uf("RJ", "RJ1", -43.20, -22.90), caminho_setores("RJ", tmp_path))
    salvar_setores(_setores_uf("MG", "MG1", -44.00, -19.90), caminho_setores("MG", tmp_path))

    barreira = threading.Barrier(3, timeout=30)
    quebrou: list[str] = []

    def callback(request):
        try:
            barreira.wait()
        except threading.BrokenBarrierError:
            # Sequencial: ninguém mais chegou à barreira dentro do timeout.
            quebrou.append(request.url)
        return (200, {}, json.dumps(_resposta_openmeteo(1)[0]))

    saida = tmp_path / "export"
    with responses.RequestsMock() as rsps:
        for _ in range(6):
            rsps.add_callback(responses.POST, FORECAST_URL, callback=callback, content_type="application/json")

        resultados = exportar_nacional(
            ["SP", "RJ", "MG"], 2026, tmp_path, saida, orcamento_alvo=1000, max_workers_uf=3
        )

    assert not quebrou, "as UFs não estavam dentro da exportação ao mesmo tempo"
    assert set(resultados.keys()) == {"SP", "RJ", "MG"}
