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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.config import caminho_setores
from src.export.dashboard_data import ExportacaoDashboardError, exportar_dashboard
from src.processing.cruzamento import centroides_4326
from src.processing.grade_espacial import calibrar_tamanho_celula, mapear_para_grade
from src.storage import ler_setores

logger = logging.getLogger(__name__)

# O orçamento cobre só os pontos de grade distintos dos setores. A série por
# município (`_series_openmeteo_por_municipio`, um ponto por município com
# setor de risco) e eventuais retries ficam FORA dessa conta. 6000 é uma
# reserva conservadora, não um cálculo preciso: deixa ~4000 de folga no teto
# de 10.000 chamadas/dia da Open-Meteo para essas duas parcelas não
# contabilizadas. Ver
# docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md.
ORCAMENTO_ALVO_PADRAO = 6000

UF_WORKERS_PADRAO = 4


def exportar_nacional(
    ufs: list[str],
    ano: int,
    diretorio_dados: Path,
    saida_dir: Path,
    orcamento_alvo: int = ORCAMENTO_ALVO_PADRAO,
    max_workers_uf: int = UF_WORKERS_PADRAO,
) -> dict[str, dict]:
    """Exporta o dashboard (fonte Open-Meteo) para várias UFs, com 1 grade nacional.

    UFs sem setores ingeridos localmente (`ingest-cprm` ainda não rodou para
    elas) são puladas com um aviso, não interrompem as demais. O mesmo vale
    para UFs cuja exportação individual falhar (ex.: Open-Meteo indisponível
    para aquele lote) — mas essas ganham uma 2a tentativa em série, ao final
    da 1a passada concorrente: na prática, uma fração pequena de UFs esgota
    os retries por rate limiting momentâneo da Open-Meteo mesmo com o
    limiter global (ver `src/ingest/rate_limiter.py`), e essa 2a passada,
    sem a concorrência das outras UFs, recupera a maioria delas. Grava
    `ufs_disponiveis.json` em `saida_dir` com as UFs exportadas com sucesso
    (ordem alfabética, mesmo se vazio), para o front-end popular o seletor.
    Retorna `{uf: meta}` só das UFs exportadas com sucesso (após as 2
    passadas).

    `orcamento_alvo` calibra APENAS a quantidade de pontos de grade distintos
    usados para os setores. A série por município
    (`_series_openmeteo_por_municipio`, buscada por UF dentro de
    `exportar_dashboard`) NÃO é coberta por esse orçamento e soma centenas a
    milhares de consultas extras no total nacional; o padrão conservador de
    `ORCAMENTO_ALVO_PADRAO` existe justamente para deixar folga para ela.

    `max_workers_uf` UFs são exportadas concorrentemente (thread pool); quem
    garante não estourar os tetos de hora/minuto da Open-Meteo (5.000/hora,
    600/minuto) é `LIMITER_PADRAO` em `src/ingest/openmeteo.py`, compartilhado
    por todo o processo (entre UFs e entre lotes dentro de cada UF), não uma
    pausa fixa aqui; ver docs/superpowers/specs/2026-08-14-cobertura-nacional-design.md.
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

    def _exportar_uf(uf: str) -> tuple[str, dict | None]:
        inicio, fim = fatias[uf]
        try:
            meta = exportar_dashboard(
                uf, ano, diretorio_dados, saida_dir,
                fonte="openmeteo", pontos_grade=pontos_grade[inicio:fim],
            )
        except (ExportacaoDashboardError, OSError, ValueError) as exc:
            logger.warning("Falha ao exportar %s: %s", uf, exc)
            return uf, None
        meta["tamanho_celula_grade_graus"] = tamanho_celula
        meta["total_celulas_grade"] = total_celulas
        return uf, meta

    resultados: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers_uf) as executor:
        for uf, meta in executor.map(_exportar_uf, fatias.keys()):
            if meta is not None:
                resultados[uf] = meta

    # UFs que esgotaram os retries na 1a passada (ex.: rate limiting
    # momentâneo da Open-Meteo) ganham uma 2a chance em série, ao final: sem
    # concorrência das outras UFs disputando o mesmo teto de requisições, dá
    # tempo pra qualquer limitação temporária passar. Reduziu na prática as
    # UFs que ficavam faltando do dashboard sem essa segunda passada.
    falhas = [uf for uf in fatias if uf not in resultados]
    if falhas:
        logger.info("Reexportando %d UF(s) que falharam na 1a passada: %s", len(falhas), ", ".join(falhas))
        for uf in falhas:
            _, meta = _exportar_uf(uf)
            if meta is not None:
                resultados[uf] = meta

    saida_dir.mkdir(parents=True, exist_ok=True)
    (saida_dir / "ufs_disponiveis.json").write_text(
        json.dumps(sorted(resultados.keys()), ensure_ascii=False, indent=2)
    )
    logger.info(
        "Exportação nacional: %d/%d UF(s) com sucesso, grade de %.5f° (%d células).",
        len(resultados), len(ufs), tamanho_celula, total_celulas,
    )
    return resultados
