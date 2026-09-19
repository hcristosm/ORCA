import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src.processing.cruzamento import centroides_4326, centroides_municipio, chuva_acumulada


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


@pytest.fixture
def serie():
    """1mm/h constante por 80h a partir de 2026-07-28 00:00 UTC."""
    horas = pd.date_range("2026-07-28 00:00", periods=80, freq="h", tz="UTC")
    return pd.DataFrame({"data_hora": horas, "chuva_mm": [1.0] * 80})


def test_chuva_acumulada_soma_a_janela_pedida(serie):
    referencia = serie["data_hora"].max()
    assert chuva_acumulada(serie, referencia, 24) == pytest.approx(24.0)
    assert chuva_acumulada(serie, referencia, 72) == pytest.approx(72.0)


def test_chuva_acumulada_ignora_leituras_depois_da_referencia(serie):
    referencia = serie["data_hora"].iloc[23]
    assert chuva_acumulada(serie, referencia, 72) == pytest.approx(24.0)


def test_chuva_acumulada_sem_leituras_na_janela_e_nan(serie):
    referencia = serie["data_hora"].min() - pd.Timedelta(days=30)
    assert pd.isna(chuva_acumulada(serie, referencia, 24))


def test_chuva_acumulada_com_buracos_soma_o_que_existe(serie):
    """NaN na série é buraco de medição, não zero: soma o resto em vez de virar NaN."""
    serie.loc[0:9, "chuva_mm"] = float("nan")
    referencia = serie["data_hora"].iloc[23]
    assert chuva_acumulada(serie, referencia, 24) == pytest.approx(14.0)


def test_chuva_acumulada_janela_toda_nan_e_nan(serie):
    serie["chuva_mm"] = float("nan")
    referencia = serie["data_hora"].max()
    assert pd.isna(chuva_acumulada(serie, referencia, 24))


def test_centroides_4326_devolve_um_ponto_por_setor():
    setores = gpd.GeoDataFrame(
        {"num_setor": ["S1", "S2"]},
        geometry=[_quadrado(-46.60, -23.50), _quadrado(-47.00, -24.00)],
        crs="EPSG:4326",
    )

    centroides = centroides_4326(setores)

    assert len(centroides) == 2
    assert centroides.crs.to_string() == "EPSG:4326"
    assert centroides.iloc[0].x == pytest.approx(-46.60, abs=1e-3)
    assert centroides.iloc[0].y == pytest.approx(-23.50, abs=1e-3)


def test_centroides_municipio_agrupa_e_ordena_por_nome():
    setores = gpd.GeoDataFrame(
        {"munic": ["CIDADE B", "CIDADE A", "CIDADE A"]},
        geometry=[_quadrado(-47.0, -24.0), _quadrado(-46.5, -23.5), _quadrado(-46.7, -23.6)],
        crs="EPSG:4326",
    )

    municipios, pontos = centroides_municipio(setores)

    assert municipios == ["CIDADE A", "CIDADE B"]
    assert len(pontos) == 2
    lat_a, lon_a = pontos[0]
    assert -24.0 < lat_a < -23.0
    assert -47.0 < lon_a < -46.0
