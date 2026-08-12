"""Rajada máxima de vento por ponto e classificação de severidade.

Módulo irmão de `cruzamento.py` (chuva) e `previsao.py` (trajetória de
chuva) — vento é um risco com geografia própria (área urbana exposta,
não talude), não um atributo dos setores geológicos, então fica
desacoplado deles (ver
.superpowers/specs/2026-08-12-camada-vento-design.md).
"""

from __future__ import annotations

import pandas as pd

# Faixas de severidade — escala Beaufort simplificada (padrão OMM),
# ilustrativa, não é um critério oficial brasileiro calibrado para
# vento urbano. `(rotulo, limite_inferior_kmh)`, em ordem crescente:
#   sem_risco      < 62 km/h  — sem efeito relevante
#   atencao      62–88 km/h  — galhos quebram, danos leves a estruturas frágeis
#   perigo      89–117 km/h  — árvores caem, danos estruturais consideráveis
#   grande_perigo  >= 118 km/h — devastação
FAIXAS_SEVERIDADE_VENTO: tuple[tuple[str, float], ...] = (
    ("sem_risco", 0.0),
    ("atencao", 62.0),
    ("perigo", 89.0),
    ("grande_perigo", 118.0),
)


def rajada_max(serie: pd.DataFrame, referencia: pd.Timestamp, horas: int) -> float:
    """Maior rajada (`vento_rajada_kmh`) na janela `(referencia - horas, referencia]`.

    Mesmo formato de janela de `cruzamento.chuva_acumulada`, mas usa o
    máximo em vez da soma — vento não acumula, o que importa é o pico.
    Retorna `NaN` se a janela não tiver dado.
    """
    if serie.empty:
        return float("nan")
    janela = serie[
        (serie["data_hora"] > referencia - pd.Timedelta(hours=horas))
        & (serie["data_hora"] <= referencia)
    ]
    if janela.empty or janela["vento_rajada_kmh"].isna().all():
        return float("nan")
    return float(janela["vento_rajada_kmh"].max(skipna=True))


def classificar_severidade(rajada_kmh: float) -> str | None:
    """Classifica `rajada_kmh` numa faixa de `FAIXAS_SEVERIDADE_VENTO`.

    Retorna `None` se `rajada_kmh` for `NaN` (sem dado) ou cair em
    `sem_risco` — só severidades acionáveis são retornadas; quem chama
    decide não exportar pontos sem risco.
    """
    if pd.isna(rajada_kmh):
        return None
    severidade = FAIXAS_SEVERIDADE_VENTO[0][0]
    for rotulo, limite in FAIXAS_SEVERIDADE_VENTO:
        if rajada_kmh >= limite:
            severidade = rotulo
    return None if severidade == "sem_risco" else severidade
