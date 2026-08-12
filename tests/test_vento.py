import pandas as pd
import pytest

from src.processing.vento import classificar_severidade, rajada_max


def test_rajada_max_pega_o_maximo_na_janela():
    referencia = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    serie = pd.DataFrame({
        "data_hora": pd.date_range(referencia - pd.Timedelta(hours=23), referencia, freq="h", tz="UTC"),
        "vento_rajada_kmh": [10.0] * 23 + [95.0],
    })

    assert rajada_max(serie, referencia, 24) == pytest.approx(95.0)


def test_rajada_max_ignora_fora_da_janela():
    referencia = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    serie = pd.DataFrame({
        "data_hora": [referencia - pd.Timedelta(hours=30), referencia],
        "vento_rajada_kmh": [200.0, 20.0],
    })

    assert rajada_max(serie, referencia, 24) == pytest.approx(20.0)


def test_rajada_max_retorna_nan_se_janela_vazia():
    referencia = pd.Timestamp("2026-08-10 12:00", tz="UTC")
    serie = pd.DataFrame({"data_hora": [], "vento_rajada_kmh": []})

    assert pd.isna(rajada_max(serie, referencia, 24))


@pytest.mark.parametrize(
    "rajada_kmh,esperado",
    [
        (0.0, None),
        (61.9, None),
        (62.0, "atencao"),
        (88.9, "atencao"),
        (89.0, "perigo"),
        (117.9, "perigo"),
        (118.0, "grande_perigo"),
        (200.0, "grande_perigo"),
    ],
)
def test_classificar_severidade_faixas(rajada_kmh, esperado):
    assert classificar_severidade(rajada_kmh) == esperado


def test_classificar_severidade_nan_retorna_none():
    assert classificar_severidade(float("nan")) is None
