import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from src.dashboard.app import COR_PADRAO, CORES_GRAU_RISCO, _construir_mapa, _cor_por_grau


def test_cor_por_grau_reconhece_variacoes_de_caixa_e_espaco():
    assert _cor_por_grau("Alto") == CORES_GRAU_RISCO["alto"]
    assert _cor_por_grau("  MUITO ALTO ") == CORES_GRAU_RISCO["muito alto"]


def test_cor_por_grau_usa_padrao_para_grau_desconhecido_ou_ausente():
    assert _cor_por_grau(None) == COR_PADRAO
    assert _cor_por_grau("baixo") == COR_PADRAO


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


def test_construir_mapa_gera_um_mapa_folium_centrado_nos_setores():
    cruzado = gpd.GeoDataFrame(
        {
            "munic": ["RIO DAS PEDRAS", "SANTOS"],
            "num_setor": ["S1", "S2"],
            "grau_risco": ["Alto", "Muito alto"],
            "distancia_km": [1.234, 5.678],
            "chuva_24h": [10.0, 20.0],
            "chuva_72h": [30.0, 150.0],
            "em_atencao": [False, True],
        },
        geometry=[_quadrado(-46.60, -23.50), _quadrado(-46.30, -24.00)],
        crs="EPSG:4326",
    )

    mapa = _construir_mapa(cruzado)

    bounds = cruzado.total_bounds
    centro_esperado = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    assert mapa.location == centro_esperado
