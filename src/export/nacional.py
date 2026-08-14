"""Orquestra a exportação do dashboard para várias UFs de uma vez.

Diferente de chamar `exportar_dashboard` uma UF por vez, este módulo calcula
UMA grade espacial (ver `src/processing/grade_espacial.py`) sobre os
centroides de TODAS as UFs pedidas antes de exportar cada uma, para que o
tamanho de célula calibrado reflita a densidade nacional (não a densidade de
uma UF isolada) e o total de pontos distintos fique dentro do orçamento
mesmo somando todas as UFs.

Nota de implementação: a busca à Open-Meteo em si ainda acontece por UF
(`exportar_dashboard` chama `_calcular_chuva_openmeteo` uma vez por UF, com
a fatia de pontos de grade daquela UF) — não há uma única chamada HTTP
nacional combinando todas as UFs. Uma célula de grade que caia exatamente na
fronteira entre duas UFs pode então ser consultada duas vezes (uma por UF),
em vez de uma só. Isso não compromete o orçamento (o total de pontos
distintos por UF nunca passa do que a calibração previu) nem a
corretude — é só uma pequena perda de eficiência de rede, aceita aqui para
não precisar reescrever `_calcular_chuva_openmeteo` para trabalhar com séries
pré-buscadas. Ver
docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.config import caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError, exportar_dashboard
from src.processing.cruzamento import centroides_4326
from src.processing.grade_espacial import calibrar_tamanho_celula, mapear_para_grade
from src.storage import ler_setores

logger = logging.getLogger(__name__)

ORCAMENTO_ALVO_PADRAO = 8000


def exportar_nacional(
    ufs: list[str],
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    orcamento_alvo: int = ORCAMENTO_ALVO_PADRAO,
) -> dict[str, dict]:
    """Exporta o dashboard (fonte Open-Meteo) para várias UFs, com 1 grade nacional.

    UFs sem setores ingeridos localmente (`ingest-cprm` ainda não rodou para
    elas) são puladas com um aviso, não interrompem as demais. O mesmo vale
    para UFs cuja exportação individual falhar (ex.: Open-Meteo indisponível
    para aquele lote). Grava `ufs_disponiveis.json` em `saida_dir` com as
    UFs exportadas com sucesso (ordem alfabética), para o front-end popular
    o seletor. Retorna `{uf: meta}` só das UFs exportadas com sucesso.
    """
    setores_por_uf = {}
    for uf in ufs:
        caminho = caminho_setores(uf, diretorio_dados)
        if not caminho.exists():
            logger.warning("Setores de %s não encontrados em %s; pulando.", uf, caminho)
            continue
        setores_por_uf[uf] = ler_setores(caminho)

    if not setores_por_uf:
        raise ValueError("Nenhuma das UFs pedidas tem setores ingeridos localmente.")

    todos_pontos: list[tuple[float, float]] = []
    fatias: dict[str, tuple[int, int]] = {}
    for uf, setores in setores_por_uf.items():
        pontos_uf = [(pt.y, pt.x) for pt in centroides_4326(setores)]
        fatias[uf] = (len(todos_pontos), len(todos_pontos) + len(pontos_uf))
        todos_pontos.extend(pontos_uf)

    tamanho_celula = calibrar_tamanho_celula(todos_pontos, orcamento_alvo)
    pontos_grade = mapear_para_grade(todos_pontos, tamanho_celula)
    total_celulas = len(set(pontos_grade))

    resultados: dict[str, dict] = {}
    for uf, (inicio, fim) in fatias.items():
        try:
            meta = exportar_dashboard(
                uf, ano, diretorio_dados, saida_dir,
                fonte="openmeteo", pontos_grade=pontos_grade[inicio:fim],
            )
        except ExportacaoDashboardError as exc:
            logger.warning("Falha ao exportar %s: %s", uf, exc)
            continue
        meta["tamanho_celula_grade_graus"] = tamanho_celula
        meta["total_celulas_grade"] = total_celulas
        resultados[uf] = meta

    (saida_dir / "ufs_disponiveis.json").write_text(
        json.dumps(sorted(resultados.keys()), ensure_ascii=False, indent=2)
    )
    logger.info(
        "Exportação nacional: %d/%d UF(s) com sucesso, grade de %.5f° (%d células).",
        len(resultados), len(ufs), tamanho_celula, total_celulas,
    )
    return resultados
