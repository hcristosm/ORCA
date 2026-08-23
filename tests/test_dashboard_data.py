import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src.config import caminho_chuva, caminho_chuva_ana, caminho_setores, LIMIAR_ATENCAO_MM_PADRAO
from src.export.dashboard_data import (
    ExportacaoDashboardError,
    _calcular_chuva_openmeteo,
    _municipios_com_chuva_relevante,
    exportar_dashboard,
)
from src.storage import salvar_chuva, salvar_setores


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


@pytest.fixture
def setores():
    return gpd.GeoDataFrame(
        {
            "num_setor": ["S1", "S2"],
            "munic": ["CIDADE A", "CIDADE B"],
            "grau_risco": ["Alto", "Muito alto"],
        },
        geometry=[_quadrado(-46.60, -23.50), _quadrado(-47.00, -24.00)],
        crs="EPSG:4326",
    )


def _serie_horaria(codigo: str, lat: float, lon: float, nome: str, valores: dict, inicio: str) -> pd.DataFrame:
    horas = pd.date_range(inicio, periods=len(valores), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "data_hora": horas,
            "chuva_mm": list(valores.values()),
            "codigo_estacao": codigo,
            "nome_estacao": nome,
            "uf": "SP",
            "latitude": lat,
            "longitude": lon,
        }
    )


def test_exportar_dashboard_gera_geojson_series_e_meta_so_com_inmet(tmp_path: Path, setores):
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

    geojson_path = saida / "setores_sp.geojson"
    assert geojson_path.exists()
    gdf = gpd.read_file(geojson_path)
    assert len(gdf) == 2
    assert set(gdf["fonte_estacao"]) == {"inmet"}
    assert "chuva_24h" in gdf.columns

    series = json.loads((saida / "series_sp.json").read_text())
    assert set(series.keys()) == {"A701", "A736"}
    assert series["A701"]["fonte"] == "inmet"

    assert meta["total_setores"] == 2
    assert meta["total_estacoes_inmet"] == 2
    assert meta["total_estacoes_ana"] == 0


def test_exportar_dashboard_combina_ana_quando_disponivel(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva_inmet = _serie_horaria("A701", -23.55, -46.65, "INMET LONGE", {0: 1.0}, "2026-08-01 00:00")
    salvar_chuva(chuva_inmet, caminho_chuva("SP", 2026, tmp_path))
    chuva_ana = _serie_horaria("ANA01", -23.5005, -46.6005, "ANA PERTO", {0: 2.0}, "2026-08-01 00:00")
    salvar_chuva(chuva_ana, caminho_chuva_ana("SP", tmp_path))

    saida = tmp_path / "export"
    meta = exportar_dashboard("SP", 2026, tmp_path, saida, fonte="inmet")

    gdf = gpd.read_file(saida / "setores_sp.geojson")
    s1 = gdf[gdf["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "ana"
    assert s1["codigo_estacao"] == "ANA01"

    series = json.loads((saida / "series_sp.json").read_text())
    assert series["ANA01"]["fonte"] == "ana"
    assert meta["total_estacoes_ana"] == 1


def test_exportar_dashboard_recorta_serie_aos_ultimos_30_dias(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    chuva = pd.concat(
        [
            _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {0: 1.0}, "2026-01-01 00:00"),
            _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", {0: 2.0}, "2026-08-05 00:00"),
            _serie_horaria("A736", -24.001, -47.001, "PERTO DE S2", {0: 0.0}, "2026-08-05 00:00"),
        ],
        ignore_index=True,
    )
    salvar_chuva(chuva, caminho_chuva("SP", 2026, tmp_path))

    saida = tmp_path / "export"
    exportar_dashboard("SP", 2026, tmp_path, saida, fonte="inmet")

    series = json.loads((saida / "series_sp.json").read_text())
    assert len(series["A701"]["serie"]) == 1
    assert series["A701"]["serie"][0][1] == 2.0


def test_exportar_dashboard_levanta_erro_se_setores_nao_existem(tmp_path: Path):
    with pytest.raises(ExportacaoDashboardError):
        exportar_dashboard("SP", 2026, tmp_path, tmp_path / "export")


def test_exportar_dashboard_levanta_erro_se_chuva_inmet_nao_existe(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    with pytest.raises(ExportacaoDashboardError):
        exportar_dashboard("SP", 2026, tmp_path, tmp_path / "export", fonte="inmet")


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
        resultado, _ = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora)

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


def test_exportar_dashboard_aceita_cache_openmeteo(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL
    from src.storage_cache_openmeteo import CacheOpenMeteo

    salvar_setores(setores, caminho_setores("SP", tmp_path))
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")

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
        meta = exportar_dashboard(
            "SP", 2026, tmp_path, saida, fonte="openmeteo", cache_openmeteo=cache,
        )

    assert meta["fonte"] == "openmeteo"


def test_exportar_dashboard_fonte_invalida_levanta_erro(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    with pytest.raises(ValueError):
        exportar_dashboard("SP", 2026, tmp_path, tmp_path / "export", fonte="xyz")


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


def test_exportar_dashboard_preserva_bloco_vento_existente_no_meta(tmp_path: Path, setores):
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
    saida.mkdir(parents=True)
    bloco_vento = {"referencia": "2026-01-01T00:00:00+00:00", "total_municipios_sinalizados": 2}
    (saida / "meta_sp.json").write_text(json.dumps({"vento": bloco_vento}))

    exportar_dashboard("SP", 2026, tmp_path, saida, fonte="inmet")

    meta = json.loads((saida / "meta_sp.json").read_text())
    assert meta["vento"] == bloco_vento
    assert meta["total_setores"] == 2
    assert meta["total_estacoes_inmet"] == 2


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


def test_calcular_chuva_openmeteo_grade_reporta_distancia_real_ate_a_celula(
    tmp_path: Path, setores
):
    import responses
    from src.ingest.openmeteo import FORECAST_URL

    agora = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]
    # Os dois setores caem na mesma célula de grade, ancorada no centroide do
    # PRIMEIRO setor: o segundo setor (centroide em -24.00, -47.00) fica a
    # ~0,5° de latitude + ~0,4° de longitude de distância, ou seja, dezenas de
    # km -- não 0,0 como o código antigo reportava.
    pontos_grade = [(-23.50, -46.60), (-23.50, -46.60)]

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST, FORECAST_URL,
            json=[{
                "latitude": -23.5, "longitude": -46.6,
                "hourly": {"time": horas_iso, "precipitation": [1.0] * 61},
            }],
            status=200,
        )
        resultado, _ = _calcular_chuva_openmeteo(
            setores, janelas=(24, 72), agora=agora, pontos=pontos_grade
        )

    assert set(resultado["nome_estacao"]) == {"Open-Meteo (célula de grade)"}
    # setor 1: o ponto de grade É o seu próprio centroide
    assert resultado.iloc[0]["distancia_km"] == pytest.approx(0.0, abs=0.05)
    # setor 2: distância real, ordem de ~69 km (0,5° lat + 0,4° lon nessa latitude)
    assert 60.0 < resultado.iloc[1]["distancia_km"] < 80.0
    # arredondado a 2 casas, como o resto do módulo
    assert resultado.iloc[1]["distancia_km"] == round(resultado.iloc[1]["distancia_km"], 2)


def test_calcular_chuva_openmeteo_sem_pontos_mantem_centro_do_setor(tmp_path: Path, setores):
    import responses
    from src.ingest.openmeteo import FORECAST_URL

    agora = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    horas = pd.date_range("2026-08-08 00:00", periods=61, freq="h", tz="UTC")
    horas_iso = [h.strftime("%Y-%m-%dT%H:%M") for h in horas]

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST, FORECAST_URL,
            json=[
                {"latitude": -23.5, "longitude": -46.6,
                 "hourly": {"time": horas_iso, "precipitation": [1.0] * 61}}
                for _ in range(2)
            ],
            status=200,
        )
        resultado, _ = _calcular_chuva_openmeteo(setores, janelas=(24, 72), agora=agora)

    assert set(resultado["nome_estacao"]) == {"Open-Meteo (centro do setor)"}
    assert set(resultado["distancia_km"]) == {0.0}


def test_calcular_chuva_openmeteo_pontos_de_tamanho_diferente_levanta_erro(setores):
    with pytest.raises(ValueError, match="mesmo tamanho"):
        _calcular_chuva_openmeteo(setores, pontos=[(-23.5, -46.6)])


def test_exportar_dashboard_pontos_grade_com_fonte_inmet_levanta_erro(tmp_path: Path, setores):
    salvar_setores(setores, caminho_setores("SP", tmp_path))
    with pytest.raises(ValueError):
        exportar_dashboard(
            "SP", 2026, tmp_path, tmp_path / "export",
            fonte="inmet", pontos_grade=[(-23.5, -46.6), (-23.5, -46.6)],
        )


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
