"""Grade espacial adaptativa para consultas em lote à Open-Meteo.

Em vez de "1 consulta por centroide de setor", agrupa setores próximos numa célula
de grade e consulta 1 ponto por célula ocupada, o que mantém o total de
chamadas diárias à Open-Meteo dentro do orçamento mesmo em escala nacional.
O tamanho da célula é calibrado automaticamente por busca binária contra os
centroides reais (não por limiares de densidade escolhidos à mão): regiões
densas naturalmente produzem mais células nessa resolução, regiões esparsas
produzem poucas.
"""

from __future__ import annotations

TAMANHO_CELULA_MIN_GRAUS = 0.001  # ~100m no equador
TAMANHO_CELULA_MAX_GRAUS = 5.0    # maior que qualquer UF brasileira


def _celula(ponto: tuple[float, float], tamanho: float) -> tuple[int, int]:
    lat, lon = ponto
    return (int(lat // tamanho), int(lon // tamanho))


def contar_celulas_ocupadas(pontos: list[tuple[float, float]], tamanho: float) -> int:
    """Quantas células distintas de tamanho `tamanho` (graus) os `pontos` ocupam."""
    return len({_celula(p, tamanho) for p in pontos})


def calibrar_tamanho_celula(
    pontos: list[tuple[float, float]],
    orcamento_alvo: int,
    tamanho_min: float = TAMANHO_CELULA_MIN_GRAUS,
    tamanho_max: float = TAMANHO_CELULA_MAX_GRAUS,
    iteracoes: int = 30,
) -> float:
    """Busca binária pelo menor tamanho de célula (mais detalhe) cujo total de
    células ocupadas ainda cabe em `orcamento_alvo`.

    Se mesmo `tamanho_max` estourar o orçamento, retorna `tamanho_max` (o
    orçamento é inviável para este conjunto de pontos com uma única célula
    nacional; quem chama decide se reduz o orçamento ou aceita o excesso).
    """
    if not pontos:
        raise ValueError("pontos vazio; nada para calibrar.")

    if contar_celulas_ocupadas(pontos, tamanho_max) > orcamento_alvo:
        return tamanho_max

    baixo, alto = tamanho_min, tamanho_max
    melhor = tamanho_max
    for _ in range(iteracoes):
        meio = (baixo + alto) / 2
        if contar_celulas_ocupadas(pontos, meio) <= orcamento_alvo:
            melhor = meio
            alto = meio
        else:
            baixo = meio
    return melhor


def mapear_para_grade(pontos: list[tuple[float, float]], tamanho: float) -> list[tuple[float, float]]:
    """Mapeia cada ponto para o centro da sua célula de grade (tamanho em graus).

    Pontos na mesma célula recebem exatamente o mesmo ponto de saída, o que
    permite a quem consulta a Open-Meteo deduplicar por célula antes de
    despachar o lote (ver `_calcular_chuva_openmeteo` em
    `src/export/dashboard_data.py`).
    """
    saida = []
    for lat, lon in pontos:
        cel_lat, cel_lon = _celula((lat, lon), tamanho)
        centro_lat = (cel_lat + 0.5) * tamanho
        centro_lon = (cel_lon + 0.5) * tamanho
        saida.append((centro_lat, centro_lon))
    return saida
