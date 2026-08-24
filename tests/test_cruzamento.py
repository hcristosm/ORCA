import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src.processing.cruzamento import (
    calcular_cruzamento,
    encontrar_estacao_mais_proxima,
    encontrar_estacao_mais_proxima_combinada,
    sinalizar_atencao,
)


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> Polygon:
    d = lado / 2
    return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])


@pytest.fixture
def setores():
    return gpd.GeoDataFrame(
        {"num_setor": ["S1", "S2"], "grau_risco": ["Alto", "Muito alto"]},
        geometry=[_quadrado(-46.60, -23.50), _quadrado(-47.00, -24.00)],
        crs="EPSG:4326",
    )


def _serie_horaria(codigo: str, lat: float, lon: float, nome: str, valores: dict, inicio: str):
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


@pytest.fixture
def chuva_df():
    # Estação A perto do setor S1, B perto do setor S2.
    valores_a = {i: 1.0 for i in range(80)}  # 1mm/h constante
    valores_b = {i: 0.0 for i in range(80)}
    serie_a = _serie_horaria("A701", -23.501, -46.601, "PERTO DE S1", valores_a, "2026-07-28 00:00")
    serie_b = _serie_horaria("A736", -24.001, -47.001, "PERTO DE S2", valores_b, "2026-07-28 00:00")
    return pd.concat([serie_a, serie_b], ignore_index=True)


def test_encontrar_estacao_mais_proxima(setores, chuva_df):
    resultado = encontrar_estacao_mais_proxima(setores, chuva_df)

    assert resultado.loc[resultado["num_setor"] == "S1", "codigo_estacao"].iloc[0] == "A701"
    assert resultado.loc[resultado["num_setor"] == "S2", "codigo_estacao"].iloc[0] == "A736"
    assert (resultado["distancia_km"] < 1).all()


def test_calcular_cruzamento_soma_chuva_nas_janelas_corretamente(setores, chuva_df):
    referencia = pd.Timestamp("2026-07-31 07:00", tz="UTC")  # hora 79 da série (1mm/h constante)

    resultado = calcular_cruzamento(setores, chuva_df, referencia=referencia, janelas=(24, 72))

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["chuva_24h"] == pytest.approx(24.0)
    assert s1["chuva_72h"] == pytest.approx(72.0)

    s2 = resultado[resultado["num_setor"] == "S2"].iloc[0]
    assert s2["chuva_24h"] == pytest.approx(0.0)
    assert s2["chuva_72h"] == pytest.approx(0.0)


def test_calcular_cruzamento_usa_ultima_leitura_como_referencia_padrao(setores, chuva_df):
    resultado = calcular_cruzamento(setores, chuva_df, janelas=(24,))

    assert resultado.attrs["referencia"] == chuva_df["data_hora"].max()


def test_calcular_cruzamento_retorna_nan_quando_sem_leituras_na_janela(setores, chuva_df):
    referencia = pd.Timestamp("2026-07-25 00:00", tz="UTC")  # antes de qualquer leitura

    resultado = calcular_cruzamento(setores, chuva_df, referencia=referencia, janelas=(24,))

    assert resultado["chuva_24h"].isna().all()


def test_calcular_cruzamento_levanta_erro_se_chuva_vazia(setores):
    vazio = pd.DataFrame(columns=["data_hora", "chuva_mm", "codigo_estacao", "latitude", "longitude"])

    with pytest.raises(ValueError):
        calcular_cruzamento(setores, vazio)


def test_sinalizar_atencao_marca_setores_acima_do_limiar(setores, chuva_df):
    referencia = pd.Timestamp("2026-07-31 07:00", tz="UTC")
    cruzado = calcular_cruzamento(setores, chuva_df, referencia=referencia, janelas=(72,))

    sinalizado = sinalizar_atencao(cruzado, limiar_mm=50.0, coluna_chuva="chuva_72h")

    assert sinalizado.loc[sinalizado["num_setor"] == "S1", "em_atencao"].iloc[0]
    assert not sinalizado.loc[sinalizado["num_setor"] == "S2", "em_atencao"].iloc[0]


def test_combinada_ana_mais_proxima_vence(setores):
    chuva_inmet = _serie_horaria("A701", -23.55, -46.65, "INMET LONGE DE S1", {0: 1.0}, "2026-07-31 00:00")
    chuva_ana = _serie_horaria("ANA01", -23.5005, -46.6005, "ANA PERTO DE S1", {0: 5.0}, "2026-07-31 00:00")

    resultado = encontrar_estacao_mais_proxima_combinada(setores, chuva_inmet, chuva_ana)

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "ana"
    assert s1["codigo_estacao"] == "ANA01"


def test_combinada_inmet_mais_proxima_vence(setores):
    chuva_inmet = _serie_horaria("A701", -23.5005, -46.6005, "INMET PERTO DE S1", {0: 1.0}, "2026-07-31 00:00")
    chuva_ana = _serie_horaria("ANA01", -23.55, -46.65, "ANA LONGE DE S1", {0: 5.0}, "2026-07-31 00:00")

    resultado = encontrar_estacao_mais_proxima_combinada(setores, chuva_inmet, chuva_ana)

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "inmet"
    assert s1["codigo_estacao"] == "A701"


def test_combinada_desempate_por_recencia_favorece_leitura_mais_nova(setores):
    mesma_lat, mesma_lon = -23.5005, -46.6005
    chuva_inmet = _serie_horaria(
        "A701", mesma_lat, mesma_lon, "INMET EMPATADO MAIS ANTIGO", {0: 1.0}, "2026-07-25 00:00"
    )
    chuva_ana = _serie_horaria(
        "ANA01", mesma_lat, mesma_lon, "ANA EMPATADO MAIS NOVO", {0: 1.0}, "2026-07-31 00:00"
    )

    resultado = encontrar_estacao_mais_proxima_combinada(setores, chuva_inmet, chuva_ana)

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "ana"


def test_combinada_desempate_por_recencia_pode_favorecer_inmet(setores):
    mesma_lat, mesma_lon = -23.5005, -46.6005
    chuva_inmet = _serie_horaria(
        "A701", mesma_lat, mesma_lon, "INMET EMPATADO MAIS NOVO", {0: 1.0}, "2026-07-31 00:00"
    )
    chuva_ana = _serie_horaria(
        "ANA01", mesma_lat, mesma_lon, "ANA EMPATADO MAIS ANTIGO", {0: 1.0}, "2026-07-25 00:00"
    )

    resultado = encontrar_estacao_mais_proxima_combinada(setores, chuva_inmet, chuva_ana)

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "inmet"


def test_calcular_cruzamento_sem_chuva_ana_mantem_comportamento_atual(setores, chuva_df):
    referencia = pd.Timestamp("2026-07-31 07:00", tz="UTC")

    resultado = calcular_cruzamento(setores, chuva_df, referencia=referencia, janelas=(24, 72))

    assert (resultado["fonte_estacao"] == "inmet").all()
    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["chuva_24h"] == pytest.approx(24.0)


def test_calcular_cruzamento_usa_chuva_da_ana_quando_ela_vence(setores):
    referencia = pd.Timestamp("2026-07-31 07:00", tz="UTC")
    chuva_inmet = _serie_horaria(
        "A701", -23.55, -46.65, "INMET LONGE", {i: 1.0 for i in range(80)}, "2026-07-28 00:00"
    )
    chuva_ana = _serie_horaria(
        "ANA01", -23.5005, -46.6005, "ANA PERTO", {i: 2.0 for i in range(80)}, "2026-07-28 00:00"
    )

    resultado = calcular_cruzamento(
        setores, chuva_inmet, chuva_ana=chuva_ana, referencia=referencia, janelas=(24,)
    )

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "ana"
    assert s1["codigo_estacao"] == "ANA01"
    assert s1["chuva_24h"] == pytest.approx(48.0)


def test_calcular_cruzamento_sem_referencia_explicita_usa_leitura_propria_da_ana(setores):
    chuva_inmet = _serie_horaria(
        "A701", -23.55, -46.65, "INMET LONGE E DEFASADO", {i: 1.0 for i in range(24)}, "2026-07-20 00:00"
    )
    chuva_ana = _serie_horaria(
        "ANA01", -23.5005, -46.6005, "ANA PERTO E FRESCA", {i: 2.0 for i in range(24)}, "2026-08-08 00:00"
    )

    resultado = calcular_cruzamento(setores, chuva_inmet, chuva_ana=chuva_ana, janelas=(24,))

    s1 = resultado[resultado["num_setor"] == "S1"].iloc[0]
    assert s1["fonte_estacao"] == "ana"
    assert not pd.isna(s1["chuva_24h"])
    assert s1["chuva_24h"] == pytest.approx(48.0)


def test_centroides_municipio_agrupa_e_ordena_por_nome():
    import geopandas as gpd
    from shapely.geometry import Polygon

    from src.processing.cruzamento import centroides_municipio

    def quadrado(cx, cy, lado=0.01):
        d = lado / 2
        return Polygon([(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)])

    setores = gpd.GeoDataFrame(
        {"munic": ["CIDADE B", "CIDADE A", "CIDADE A"]},
        geometry=[quadrado(-47.0, -24.0), quadrado(-46.5, -23.5), quadrado(-46.7, -23.6)],
        crs="EPSG:4326",
    )

    municipios, pontos = centroides_municipio(setores)

    assert municipios == ["CIDADE A", "CIDADE B"]
    assert len(pontos) == 2
    lat_a, lon_a = pontos[0]
    assert -24.0 < lat_a < -23.0
    assert -47.0 < lon_a < -46.0
