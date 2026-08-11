"""Trajetória de "alerta previsto": acumulado de 72h projetado a partir da previsão de chuva.

Reaproveita a mesma lógica de acumulado usada para chuva observada
(`cruzamento.chuva_acumulada`), aplicada a pontos futuros de uma série que já
mistura chuva observada e prevista (ver `src/ingest/openmeteo.py`). Módulo
separado de `cruzamento.py`: ali é cruzamento espacial (setor → estação),
aqui é projeção temporal (chuva observada → alerta previsto).
"""

from __future__ import annotations

import pandas as pd

from src.processing.cruzamento import chuva_acumulada

# Horizonte da previsão de "alerta previsto": até 3 dias (72h) à frente,
# amostrado de 3 em 3 horas — depois desse prazo a previsão de chuva fica
# pouco confiável pra esse tipo de sinalização antecipada. O valor abaixo é
# 4 (não 3): a Open-Meteo entrega `forecast_days` em dias-calendário GMT
# inteiros, não em horas a partir do instante da consulta — com 3 dias a
# cobertura real pode cair pra ~25h dependendo da hora do dia em que a
# exportação roda. O dia extra é folga pra garantir cobertura de 72h
# completos independente do horário de execução.
DIAS_PREVISAO_ALERTA = 4
PASSO_PREVISAO_HORAS = 3
HORIZONTE_PREVISAO_HORAS = 72


def trajetoria_chuva_72h(
    serie: pd.DataFrame,
    agora: pd.Timestamp,
    passo_horas: int = PASSO_PREVISAO_HORAS,
    horizonte_horas: int = HORIZONTE_PREVISAO_HORAS,
) -> list:
    """Acumulado de 72h em cada ponto futuro, combinando chuva já caída + prevista.

    Reaproveita `chuva_acumulada` (mesma função usada pro acumulado
    observado) chamada em cada ponto futuro `t` — ela soma `chuva_mm` na
    janela `(t - 72h, t]` independente de os pontos serem passados ou
    futuros, já que a série da Open-Meteo já vem contínua (observado +
    previsto misturados na mesma sequência de `data_hora`).

    Pontos além do último dado disponível na série (`serie["data_hora"].max()`)
    recebem `None` em vez de um valor calculado — sem essa checagem,
    `chuva_acumulada` soma só a parte da janela que ainda tem dado e o
    valor decai silenciosamente rumo a zero conforme `t` avança além do
    horizonte real da previsão, em vez de sinalizar "sem dado aqui".

    Retorna `[[timestamp_iso, mm_acumulado_previsto], ...]`, do ponto
    `agora` até `agora + horizonte_horas` em passos de `passo_horas`
    (25 pontos com os valores padrão: 0h, 3h, ..., 72h).
    """
    pontos = []
    passo = pd.Timedelta(hours=passo_horas)
    limite = agora + pd.Timedelta(hours=horizonte_horas)
    dados_validos_ate = serie["data_hora"].max() if not serie.empty else agora
    t = agora
    while t <= limite:
        if t > dados_validos_ate:
            pontos.append([t.isoformat(), None])
        else:
            valor = chuva_acumulada(serie, t, 72)
            pontos.append([t.isoformat(), None if pd.isna(valor) else round(float(valor), 2)])
        t += passo
    return pontos
