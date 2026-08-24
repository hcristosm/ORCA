"""Mescla o dashboard publicado no que este run gerou (spec §4.5).

Existe porque a publicação usa `force_orphan`: o gh-pages passa a ser
EXATAMENTE o conteúdo de `docs/dashboard`, então uma UF que a Open-Meteo
não entregou hoje simplesmente sumiria do ar. A cobertura diária oscila
entre 70% e 100% (18 runs, 2026-08-10 a 08-23), ou seja, sumiço seria o
caso comum, não a exceção.

Mesclando, degradar vira envelhecer (princípio §3.2): a UF que falhou
continua publicada com o dado da véspera, e a guarda anti-regressão do
workflow deixa de recusar um terço das execuções por uma oscilação
normal.

Duas decisões que a mescla NÃO toma sozinha:

1. Só preserva UF que ainda está no escopo desta execução, medido pelos
   GeoPackages em `--escopo` (que vêm da branch dados-base). Uma mescla
   que preservasse tudo para sempre seria tão errada quanto não preservar
   nada: uma UF legitimamente retirada do escopo ficaria imortal no
   dashboard, congelada, sem nenhum jeito de sair.
2. Só copia os arquivos que a exportação atual sabe produzir
   (`PREFIXOS`). Resíduos de gerações anteriores -- os `vento_*.geojson`
   removidos em §4.1 ainda presentes no gh-pages -- não são ressuscitados.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Arquivos por UF que a exportação atual produz (src/export/dashboard_data.py).
# `previsao_` é opcional: nem toda UF tem previsão, e a ausência não impede
# preservar o resto.
PREFIXOS = (
    ("meta_", ".json"),
    ("previsao_", ".json"),
    ("series_", ".json"),
    ("setores_", ".geojson"),
)

INDICE = "ufs_disponiveis.json"


def ler_indice(caminho: Path) -> list[str]:
    """Lê `ufs_disponiveis.json`; devolve [] se ausente ou ilegível.

    O front-end (docs/dashboard/index.html) faz `uf.toLowerCase()` na
    lista, então normalizamos aqui também para não depender de o índice
    publicado ter a mesma caixa do atual.
    """
    try:
        dados = json.loads(caminho.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(dados, list):
        return []
    return [str(uf).lower() for uf in dados if isinstance(uf, str)]


def escrever_indice(caminho: Path, ufs: list[str]) -> None:
    caminho.write_text(json.dumps(sorted(set(ufs)), ensure_ascii=False, indent=2))


def ufs_no_escopo(escopo_dir: Path) -> set[str]:
    """UFs que esta execução tinha o direito de exportar (risco_<uf>.gpkg)."""
    return {p.stem.removeprefix("risco_").lower() for p in escopo_dir.glob("risco_*.gpkg")}


def mesclar(publicado_dir: Path, atual_dir: Path, escopo: set[str]) -> list[str]:
    """Copia para `atual_dir` os arquivos das UFs publicadas que o run não gerou.

    Devolve as UFs preservadas, em ordem alfabética. Não sobrescreve nada
    do run atual: dado novo sempre ganha do velho.
    """
    atuais = set(ler_indice(atual_dir / INDICE))
    publicadas = set(ler_indice(publicado_dir / INDICE))

    preservadas = []
    for uf in sorted(publicadas - atuais):
        if uf not in escopo:
            print(f"UF {uf} está publicada mas saiu do escopo desta execução; não preservada.")
            continue
        copiados = 0
        for prefixo, sufixo in PREFIXOS:
            origem = publicado_dir / f"{prefixo}{uf}{sufixo}"
            if origem.is_file():
                shutil.copy2(origem, atual_dir / origem.name)
                copiados += 1
        if copiados == 0:
            # Índice publicado lista a UF, mas os arquivos dela não estão
            # lá: preservar só o nome no índice daria uma UF quebrada no
            # seletor do front-end.
            print(f"UF {uf} consta do índice publicado mas não tem arquivos; não preservada.")
            continue
        preservadas.append(uf)
        print(f"UF {uf} preservada do gh-pages ({copiados} arquivo(s)); dado mais velho, não ausente.")

    escrever_indice(atual_dir / INDICE, sorted(atuais | set(preservadas)))
    return preservadas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mescla o dashboard publicado no run atual.")
    parser.add_argument("--publicado", required=True, type=Path, help="data/ extraído do gh-pages")
    parser.add_argument("--atual", required=True, type=Path, help="docs/dashboard/data deste run")
    parser.add_argument("--escopo", required=True, type=Path, help="diretório com os risco_<uf>.gpkg")
    args = parser.parse_args(argv)

    # Recusar quando este run não produziu UF nenhuma é a decisão de
    # desenho mais importante daqui. Mesclar nesse caso montaria um
    # conjunto completo feito 100% de dado velho, a guarda anti-regressão
    # o aprovaria como se fosse novo, e o run fecharia verde -- exatamente
    # a degradação silenciosa dos runs #23 e #29. Sem índice e índice
    # vazio são o MESMO caso: `exportar_nacional` grava
    # `ufs_disponiveis.json` mesmo com zero sucessos.
    if not (args.atual / INDICE).is_file():
        print("Este run não gerou ufs_disponiveis.json; recusando mesclar dado inteiramente velho.", file=sys.stderr)
        return 1
    if not ler_indice(args.atual / INDICE):
        print("Este run não exportou UF nenhuma; recusando mesclar dado inteiramente velho.", file=sys.stderr)
        return 1

    preservadas = mesclar(args.publicado, args.atual, ufs_no_escopo(args.escopo))
    total = len(ler_indice(args.atual / INDICE))
    print(f"Mescla concluída: {len(preservadas)} UF(s) preservada(s), {total} UF(s) publicáveis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
