import pandas as pd
import pytest

from src.processing.previsao import trajetoria_chuva_72h


def test_trajetoria_chuva_72h_encontra_cruzamento_futuro():
    agora = pd.Timestamp("2026-08-10 00:00", tz="UTC")
    horas_passado = pd.date_range(agora - pd.Timedelta(hours=71), agora, freq="h", tz="UTC")
    horas_futuro = pd.date_range(agora + pd.Timedelta(hours=1), agora + pd.Timedelta(hours=72), freq="h", tz="UTC")
    serie = pd.DataFrame({
        "data_hora": list(horas_passado) + list(horas_futuro),
        "chuva_mm": [0.0] * len(horas_passado) + [5.0] * len(horas_futuro),
    })

    trajetoria = trajetoria_chuva_72h(serie, agora, passo_horas=3, horizonte_horas=72)

    assert len(trajetoria) == 25
    assert trajetoria[0][0] == agora.isoformat()
    assert trajetoria[0][1] == pytest.approx(0.0)
    assert trajetoria[-1][1] > 100


def test_trajetoria_chuva_72h_retorna_none_alem_do_horizonte_de_dados():
    agora = pd.Timestamp("2026-08-10 00:00", tz="UTC")
    horas = pd.date_range(agora, agora + pd.Timedelta(hours=30), freq="h", tz="UTC")
    serie = pd.DataFrame({"data_hora": horas, "chuva_mm": [1.0] * len(horas)})

    trajetoria = trajetoria_chuva_72h(serie, agora, passo_horas=3, horizonte_horas=72)

    pontos_alem = [v for t, v in trajetoria if pd.Timestamp(t) > agora + pd.Timedelta(hours=30)]
    assert all(v is None for v in pontos_alem)
    pontos_dentro = [v for t, v in trajetoria if pd.Timestamp(t) <= agora + pd.Timedelta(hours=30)]
    assert all(v is not None for v in pontos_dentro)
