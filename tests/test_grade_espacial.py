import pytest

from src.processing.grade_espacial import (
    calibrar_tamanho_celula,
    contar_celulas_ocupadas,
    mapear_para_grade,
)


def test_contar_celulas_ocupadas_agrupa_pontos_proximos():
    pontos = [(-23.500, -46.600), (-23.501, -46.601), (-23.900, -47.200)]
    # célula bem grossa: os dois primeiros pontos (bem próximos) caem juntos
    assert contar_celulas_ocupadas(pontos, tamanho=1.0) == 2
    # célula bem fina: cada ponto fica isolado
    assert contar_celulas_ocupadas(pontos, tamanho=0.0001) == 3


def test_calibrar_tamanho_celula_atende_orcamento():
    pontos = [(-23.0 - i * 0.001, -46.0 - i * 0.001) for i in range(500)]
    tamanho = calibrar_tamanho_celula(pontos, orcamento_alvo=50)
    assert contar_celulas_ocupadas(pontos, tamanho) <= 50


def test_calibrar_tamanho_celula_orcamento_folgado_preserva_detalhe():
    pontos = [(-23.0 - i * 1.0, -46.0 - i * 1.0) for i in range(5)]  # bem espalhados
    tamanho = calibrar_tamanho_celula(pontos, orcamento_alvo=1000)
    assert contar_celulas_ocupadas(pontos, tamanho) == 5


def test_calibrar_tamanho_celula_pontos_vazio_levanta_erro():
    with pytest.raises(ValueError):
        calibrar_tamanho_celula([], orcamento_alvo=100)


def test_mapear_para_grade_pontos_na_mesma_celula_recebem_mesmo_ponto():
    pontos = [(-23.500, -46.600), (-23.501, -46.601), (-23.900, -47.200)]
    mapeado = mapear_para_grade(pontos, tamanho=1.0)

    assert mapeado[0] == mapeado[1]
    assert mapeado[2] != mapeado[0]
    assert len(mapeado) == len(pontos)
