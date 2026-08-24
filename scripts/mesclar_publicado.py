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
import os
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

# Fração mínima do escopo que este run precisa ter exportado SOZINHO para
# que a mescla seja permitida (ruling R-12).
#
# Por que um piso aqui, e não só na guarda do workflow: como o índice
# publicado passa a ser a UNIÃO (run + preservadas), `atual >= publicado`
# vale por construção e a guarda anti-regressão fica reduzida a
# "atual != 0". Sem este piso, um run degenerado (1 de 27, como os runs
# #23 e #29) teria as outras 26 completadas do gh-pages e fecharia VERDE,
# sem sinal nenhum -- pior do que antes da mescla, quando pelo menos
# ficava vermelho. `atualizar-nacional` também sai 0 com 1/27 (só falha
# se `not resultados`), então este é o único detector de run degenerado
# que sobra.
#
# Derivação do 0.6: nos 12 runs limpos de 2026-08-10 a 08-23 (spec §2.4)
# a cobertura Open-Meteo oscilou entre 70% e 100%, com o pior caso normal
# em 74% (19/27, run #21). 0.6 fica abaixo desse pior caso com margem --
# não recria a catraca que a mescla veio remover -- e ainda assim barra
# os cenários degenerados reais: 1/27 (4%) e 2/27 (7%). Um piso de 0.9
# dispararia em 4 dos 12 runs limpos e seria aprendido como ruído, que é
# o erro que a spec §4.7 documenta.
PISO_COBERTURA_PADRAO = 0.6


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


def mesclar(publicado_dir: Path, atual_dir: Path, escopo: set[str]) -> tuple[list[str], list[str]]:
    """Copia para `atual_dir` os arquivos das UFs publicadas que o run não gerou.

    Devolve `(preservadas, fora_do_escopo)`, ambas em ordem alfabética.
    Não sobrescreve nada do run atual: dado novo sempre ganha do velho.
    """
    atuais = set(ler_indice(atual_dir / INDICE))
    publicadas = set(ler_indice(publicado_dir / INDICE))

    preservadas: list[str] = []
    fora_do_escopo: list[str] = []
    for uf in sorted(publicadas - atuais):
        if uf not in escopo:
            fora_do_escopo.append(uf)
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

    if fora_do_escopo:
        # A guarda do workflow vai recusar por regressão, com a MESMA
        # mensagem que aparece quando o dados-base veio pela metade.
        # Causas opostas, ações opostas: sem esta anotação o operador não
        # tem como saber qual das duas está vendo.
        print(
            f"::warning::{len(fora_do_escopo)} UF(s) saíram do escopo "
            f"({', '.join(fora_do_escopo)}): estão publicadas mas não têm "
            "GeoPackage em data/. O conjunto publicável encolhe e a guarda "
            "vai recusar por regressão. Se a redução foi deliberada "
            "(UF removida do dados-base), republique com o escopo novo de "
            "propósito; se NÃO foi, o dados-base veio incompleto -- não "
            "rode ingerir-setores.yml, apenas execute este workflow de novo."
        )

    escrever_indice(atual_dir / INDICE, sorted(atuais | set(preservadas)))
    return preservadas, fora_do_escopo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mescla o dashboard publicado no run atual.")
    parser.add_argument("--publicado", required=True, type=Path, help="data/ extraído do gh-pages")
    parser.add_argument("--atual", required=True, type=Path, help="docs/dashboard/data deste run")
    parser.add_argument("--escopo", required=True, type=Path, help="diretório com os risco_<uf>.gpkg")
    parser.add_argument(
        "--piso", type=float,
        default=float(os.environ.get("ORCA_PISO_COBERTURA", PISO_COBERTURA_PADRAO)),
        help="fração mínima do escopo exportada por este run (padrão %(default)s)",
    )
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

    escopo = ufs_no_escopo(args.escopo)
    exportadas = ler_indice(args.atual / INDICE)
    # Escopo desconhecido (nenhum GeoPackage) não é medível: quem barra
    # esse caso é o passo "Baixar setores da branch dados-base", que é
    # fatal. Recusar aqui de novo só trocaria a mensagem certa por uma
    # confusa.
    if escopo:
        minimo = args.piso * len(escopo)
        if len(exportadas) < minimo:
            print(
                f"::error::Run degenerado: {len(exportadas)} de {len(escopo)} UF(s) do escopo "
                f"exportadas nesta execução, abaixo do piso de {args.piso:.0%}. Mesclar "
                "completaria o resto com dado velho e o run fecharia verde sem sinal nenhum. "
                "Mescla e publicação recusadas.",
                file=sys.stderr,
            )
            return 1

    preservadas, _fora = mesclar(args.publicado, args.atual, escopo)
    total = len(ler_indice(args.atual / INDICE))
    print(f"Mescla concluída: {len(preservadas)} UF(s) preservada(s), {total} UF(s) publicáveis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
